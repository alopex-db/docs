# Alopex Skulk 技術仕様書

**バージョン**: 1.0
**最終更新日**: 2025-11-29
**ステータス**: Draft

---

## 1. 技術概要

### 1.1 技術スタック

| レイヤー | 技術 | 備考 |
|---------|------|------|
| プログラミング言語 | Rust 1.75+ | Alopex DB と統一 |
| 非同期ランタイム | Tokio | Alopex Core から継承 |
| ストレージ基盤 | alopex-core | WAL, MemTable, Compaction |
| 圧縮 | Gorilla (自前実装) + LZ4 | 時系列最適化 |
| クラスタ通信 | alopex-chirps | Raft Consensus API, SWIM, QUIC |
| クエリパーサー | nom (PromQL), sqlparser-rs拡張 (SQL-TS) | - |
| シリアライゼーション | bincode, serde | 内部通信 |
| エラーハンドリング | thiserror + anyhow | Alopex と統一 |
| メトリクス | prometheus (client) | self-monitoring |

### 1.2 アーキテクチャ原則

**TSDB-AP-001: Alopex Core基盤**
```
alopex-core (共通基盤)
    │
    ├── WAL ─────────────────────────────────┐
    │                                        │
    ├── MemTable (trait) ──────────┐         │
    │                              │         │
    └── Compaction (trait) ───┐    │         │
                              │    │         │
                              ▼    ▼         ▼
                         alopex-skulk (専用実装)
                         - TimeSeriesMemTable
                         - TSMCompactor
                         - GorillaCompression
```

**TSDB-AP-002: 時刻ベースパーティショニング**
- 全データは時刻パーティション単位で物理分離
- TTL削除はパーティション単位（行削除なし）
- Compactionもパーティション内で完結

**TSDB-AP-003: ストリーミングファースト**
- 書き込みはバッチ最適化（バッファリング）
- 読み取りはストリーミングイテレータ
- メモリ使用量を一定に保つ

### 1.3 モジュール構成

```
alopex-skulk/
├── Cargo.toml
├── src/
│   ├── lib.rs
│   │
│   ├── storage/
│   │   ├── mod.rs
│   │   ├── memtable.rs       # TimeSeriesMemTable
│   │   ├── tsm/
│   │   │   ├── mod.rs
│   │   │   ├── writer.rs     # TSMファイル書き込み
│   │   │   ├── reader.rs     # TSMファイル読み取り
│   │   │   └── index.rs      # シリーズインデックス
│   │   ├── wal.rs            # alopex-core WAL利用
│   │   └── compaction.rs     # 時系列Compaction
│   │
│   ├── compression/
│   │   ├── mod.rs
│   │   ├── gorilla.rs        # Gorilla圧縮
│   │   ├── delta.rs          # Delta-of-Delta
│   │   └── dictionary.rs     # ラベル辞書圧縮
│   │
│   ├── lifecycle/
│   │   ├── mod.rs
│   │   ├── ttl.rs            # TTL管理
│   │   ├── downsample.rs     # ダウンサンプリング
│   │   └── retention.rs      # 保持ポリシー
│   │
│   ├── query/
│   │   ├── mod.rs
│   │   ├── promql/
│   │   │   ├── parser.rs     # PromQLパーサー
│   │   │   ├── ast.rs        # PromQL AST
│   │   │   └── eval.rs       # PromQL評価
│   │   ├── sqlts/
│   │   │   ├── parser.rs     # SQL-TS拡張パーサー
│   │   │   └── functions.rs  # 時系列関数
│   │   ├── planner.rs        # クエリプランナー
│   │   └── executor.rs       # クエリ実行
│   │
│   ├── ingest/
│   │   ├── mod.rs
│   │   ├── line_protocol.rs  # Line Protocolパーサー
│   │   ├── remote_write.rs   # Prometheus Remote Write
│   │   └── batch.rs          # バッチ処理
│   │
│   ├── alert/
│   │   ├── mod.rs
│   │   ├── engine.rs         # アラートエンジン
│   │   ├── rule.rs           # ルール定義
│   │   └── notifier.rs       # 通知
│   │
│   ├── cluster/
│   │   ├── mod.rs
│   │   ├── shard.rs          # シャーディング
│   │   ├── router.rs         # クエリルーティング
│   │   └── replication.rs    # Chirps Raft API連携 (ShardStateMachine)
│   │
│   ├── server/
│   │   ├── mod.rs
│   │   ├── http.rs           # HTTP API
│   │   └── metrics.rs        # Prometheusメトリクス
│   │
│   └── embedded/
│       ├── mod.rs
│       └── api.rs            # Embedded API
│
└── tests/
    ├── integration/
    └── benchmarks/
```

---

## 2. Alopex Core連携仕様

### 2.1 WAL連携

```rust
use alopex_core::wal::{WriteAheadLog, WalEntry, WalConfig};

/// TSDB用WALエントリ
#[derive(Serialize, Deserialize)]
pub enum TSDBWalEntry {
    /// データポイント書き込み
    Write {
        series_id: u64,
        timestamp: i64,
        value: f64,
    },

    /// バッチ書き込み（効率化）
    WriteBatch {
        points: Vec<DataPoint>,
    },

    /// シリーズ登録
    RegisterSeries {
        series_id: u64,
        metric_name: String,
        labels: Vec<(String, String)>,
    },

    /// パーティション削除（TTL）
    DropPartition {
        partition: TimePartition,
    },
}

impl WalEntry for TSDBWalEntry {
    fn serialize(&self) -> Vec<u8> {
        bincode::serialize(self).unwrap()
    }

    fn deserialize(data: &[u8]) -> Result<Self> {
        bincode::deserialize(data).map_err(Into::into)
    }
}

/// WAL設定（時系列最適化）
pub fn tsdb_wal_config() -> WalConfig {
    WalConfig {
        // バッチ書き込み最適化
        sync_mode: SyncMode::BatchSync {
            max_batch_size: 10_000,
            max_wait_ms: 100,
        },
        // セグメントサイズ（時間ベースローテーション）
        segment_size: 64 * 1024 * 1024,  // 64MB
        // 保持セグメント数
        max_segments: 8,
    }
}
```

### 2.1.1 バックプレッシャ制御

Pebble/TiKV を参考に、L0 セクション数と Compaction 負債に基づくバックプレッシャを実装する。

```rust
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::time::Duration;

/// バックプレッシャ設定
#[derive(Clone)]
pub struct BackpressureConfig {
    /// L0 セクション数ソフトリミット（超過で遅延開始）
    pub soft_limit_sections: usize,
    /// L0 セクション数ハードリミット（超過でブロック）
    pub hard_limit_sections: usize,
    /// Compaction 負債閾値 (bytes)
    pub compaction_debt_threshold: u64,
    /// 最大遅延時間
    pub max_delay: Duration,
}

impl Default for BackpressureConfig {
    fn default() -> Self {
        Self {
            soft_limit_sections: 12,
            hard_limit_sections: 20,
            compaction_debt_threshold: 256 * 1024 * 1024, // 256MB
            max_delay: Duration::from_millis(500),
        }
    }
}

/// バックプレッシャコントローラ
pub struct BackpressureController {
    /// 未 Compaction の L0 セクション数
    pending_sections: AtomicUsize,
    /// Compaction 負債（推定バイト数）
    compaction_debt: AtomicU64,
    /// 設定
    config: BackpressureConfig,
}

impl BackpressureController {
    pub fn new(config: BackpressureConfig) -> Self {
        Self {
            pending_sections: AtomicUsize::new(0),
            compaction_debt: AtomicU64::new(0),
            config,
        }
    }

    /// 書き込み前の遅延計算
    /// Returns: Duration::ZERO (遅延なし), Duration::MAX (ブロック), その他 (遅延時間)
    pub fn calculate_delay(&self) -> Duration {
        let sections = self.pending_sections.load(Ordering::Relaxed);
        let debt = self.compaction_debt.load(Ordering::Relaxed);

        // ハードリミット超過 → ブロック
        if sections >= self.config.hard_limit_sections {
            return Duration::MAX;
        }

        // ソフトリミット未満 → 遅延なし
        if sections < self.config.soft_limit_sections {
            return Duration::ZERO;
        }

        // ソフトリミット超過 → 線形遅延
        let section_ratio = (sections - self.config.soft_limit_sections) as f64
            / (self.config.hard_limit_sections - self.config.soft_limit_sections) as f64;

        // Compaction 負債による追加遅延
        let debt_ratio = (debt as f64 / self.config.compaction_debt_threshold as f64)
            .min(1.0);

        let combined_ratio = (section_ratio * 0.7 + debt_ratio * 0.3).min(1.0);
        let delay_ms = (self.config.max_delay.as_millis() as f64 * combined_ratio) as u64;

        Duration::from_millis(delay_ms)
    }

    /// 書き込み前のゲート（必要に応じて待機）
    pub async fn wait_for_capacity(&self) {
        loop {
            let delay = self.calculate_delay();
            if delay == Duration::ZERO {
                return;
            }
            if delay == Duration::MAX {
                // Compaction 完了を待機
                tokio::time::sleep(Duration::from_millis(100)).await;
                continue;
            }
            tokio::time::sleep(delay).await;
            return;
        }
    }

    /// Flush 完了時にセクション数を増加
    pub fn on_flush_complete(&self) {
        self.pending_sections.fetch_add(1, Ordering::Relaxed);
    }

    /// Compaction 完了時にセクション数を減少
    pub fn on_compaction_complete(&self, sections_removed: usize, bytes_compacted: u64) {
        self.pending_sections.fetch_sub(sections_removed, Ordering::Relaxed);
        // 負債を減算（アンダーフローを防止）
        let _ = self.compaction_debt.fetch_update(
            Ordering::Relaxed,
            Ordering::Relaxed,
            |current| Some(current.saturating_sub(bytes_compacted))
        );
    }

    /// 書き込みバイト数に応じて負債を加算
    pub fn add_write_debt(&self, bytes: u64) {
        self.compaction_debt.fetch_add(bytes, Ordering::Relaxed);
    }
}

/// WAL + バックプレッシャ統合ライター
pub struct ThrottledWalWriter {
    wal: WriteAheadLog,
    backpressure: Arc<BackpressureController>,
}

impl ThrottledWalWriter {
    pub async fn write_batch(&self, entries: &[TSDBWalEntry]) -> Result<()> {
        // バックプレッシャゲート
        self.backpressure.wait_for_capacity().await;

        // WAL 書き込み
        let bytes_written = self.wal.write_batch(entries)?;

        // 負債加算（Write Amplification 見積もり: 実書き込みの約10倍）
        self.backpressure.add_write_debt(bytes_written as u64 * 10);

        Ok(())
    }
}
```

### 2.2 MemTable連携

```rust
use alopex_core::memtable::{MemTable as BaseMemTable, MemTableConfig};

/// 時系列特化MemTable
pub struct TimeSeriesMemTable {
    /// 基底MemTable (alopex-core)
    base: BaseMemTable,

    /// 時刻パーティション
    partition: TimePartition,

    /// シリーズID → データポイントのマッピング
    /// BTreeMapで時刻順ソートを維持
    series_data: HashMap<SeriesId, BTreeMap<Timestamp, f64>>,

    /// シリーズメタデータ
    series_meta: HashMap<SeriesId, SeriesMeta>,

    /// 統計情報
    stats: MemTableStats,
}

#[derive(Default)]
struct MemTableStats {
    point_count: AtomicU64,
    series_count: AtomicU32,
    memory_bytes: AtomicUsize,
    min_timestamp: AtomicI64,
    max_timestamp: AtomicI64,
}

impl TimeSeriesMemTable {
    pub fn new(partition: TimePartition, config: MemTableConfig) -> Self {
        Self {
            base: BaseMemTable::new(config),
            partition,
            series_data: HashMap::new(),
            series_meta: HashMap::new(),
            stats: MemTableStats::default(),
        }
    }

    /// データポイント挿入
    pub fn insert(&mut self, point: &DataPoint) -> Result<()> {
        let series_id = self.get_or_create_series(
            &point.metric,
            &point.labels
        )?;

        // シリーズデータに追加
        self.series_data
            .entry(series_id)
            .or_insert_with(BTreeMap::new)
            .insert(point.timestamp, point.value);

        // 統計更新
        self.stats.point_count.fetch_add(1, Ordering::Relaxed);
        self.update_timestamp_range(point.timestamp);

        // alopex-core MemTableにも書き込み（WALリカバリ用）
        let key = encode_tsm_key(series_id, point.timestamp);
        let value = point.value.to_le_bytes();
        self.base.put(&key, &value)?;

        Ok(())
    }

    /// Flush準備完了かチェック
    pub fn should_flush(&self) -> bool {
        let size = self.stats.memory_bytes.load(Ordering::Relaxed);
        let age = Timestamp::now() - self.stats.min_timestamp.load(Ordering::Relaxed);

        size >= FLUSH_SIZE_THRESHOLD     // 64MB
        || age >= FLUSH_AGE_THRESHOLD    // 15分
    }

    /// TSMファイルへFlush
    pub async fn flush(&self, path: &Path) -> Result<TSMFile> {
        let mut writer = TSMWriter::new(path)?;

        // シリーズごとにデータブロック書き込み
        for (series_id, points) in &self.series_data {
            let meta = &self.series_meta[series_id];
            writer.write_series(*series_id, meta, points)?;
        }

        writer.finish()
    }
}

/// TSMキーエンコーディング
fn encode_tsm_key(series_id: u64, timestamp: i64) -> Vec<u8> {
    let mut key = Vec::with_capacity(16);
    key.extend_from_slice(&series_id.to_be_bytes());
    // タイムスタンプは降順ソート用に反転
    key.extend_from_slice(&(!timestamp as u64).to_be_bytes());
    key
}
```

### 2.3 Compaction連携

```rust
use alopex_core::compaction::{Compactor as BaseCompactor, CompactionStrategy};

/// 時系列Compaction戦略
pub struct TimeSeriesCompactionStrategy {
    /// 基底戦略
    base: CompactionStrategy,

    /// パーティション内レベル設定
    level_config: Vec<LevelConfig>,

    /// ダウンサンプリング統合
    downsample_on_compact: bool,

    /// 書き込み増幅トラッカー
    write_amp_tracker: WriteAmpTracker,
}

struct LevelConfig {
    level: u8,
    max_files: usize,
    target_file_size: usize,
}

impl TimeSeriesCompactionStrategy {
    /// 時系列用デフォルト設定
    pub fn default() -> Self {
        Self {
            base: CompactionStrategy::Leveled,
            level_config: vec![
                LevelConfig { level: 0, max_files: 4, target_file_size: 4 * MB },
                LevelConfig { level: 1, max_files: 10, target_file_size: 40 * MB },
                LevelConfig { level: 2, max_files: 100, target_file_size: 400 * MB },
            ],
            downsample_on_compact: false,
            write_amp_tracker: WriteAmpTracker::new(),
        }
    }

    /// Compaction対象選択
    pub fn select_files(&self, partition: &TimePartition) -> Vec<CompactionTask> {
        let mut tasks = vec![];

        // Level 0 → Level 1 (重複キー範囲全マージ)
        let l0_files = self.list_files(partition, 0);
        if l0_files.len() > self.level_config[0].max_files {
            tasks.push(CompactionTask {
                level: 0,
                input_files: l0_files,
                output_level: 1,
            });
        }

        // Level N → Level N+1 (サイズベース)
        for config in &self.level_config[1..] {
            let files = self.list_files(partition, config.level);
            let total_size: usize = files.iter().map(|f| f.size).sum();

            if total_size > config.max_files * config.target_file_size {
                // 最古のファイルを選択
                let oldest = files.into_iter().min_by_key(|f| f.created_at);
                if let Some(file) = oldest {
                    tasks.push(CompactionTask {
                        level: config.level,
                        input_files: vec![file],
                        output_level: config.level + 1,
                    });
                }
            }
        }

        tasks
    }
}

/// Compaction実行
pub struct TSMCompactor {
    strategy: TimeSeriesCompactionStrategy,
    backpressure: Arc<BackpressureController>,
}

impl TSMCompactor {
    pub async fn compact(&self, task: CompactionTask) -> Result<Vec<TSMFile>> {
        let input_bytes: u64 = task.input_files.iter().map(|f| f.size as u64).sum();

        // 入力ファイルを時刻順マージイテレータで読み取り
        let readers: Vec<_> = task.input_files.iter()
            .map(|f| TSMReader::open(&f.path))
            .collect::<Result<_>>()?;

        let merged = MergingIterator::new(readers);

        // 出力ファイル書き込み
        let mut output_files = vec![];
        let mut writer = TSMWriter::new_for_level(task.output_level)?;
        let mut output_bytes: u64 = 0;

        for (series_id, timestamp, value) in merged {
            writer.write_point(series_id, timestamp, value)?;

            // ファイルサイズ制限でローテーション
            if writer.size() >= self.strategy.level_config[task.output_level as usize].target_file_size {
                let file = writer.finish()?;
                output_bytes += file.size as u64;
                output_files.push(file);
                writer = TSMWriter::new_for_level(task.output_level)?;
            }
        }

        if writer.point_count() > 0 {
            let file = writer.finish()?;
            output_bytes += file.size as u64;
            output_files.push(file);
        }

        // 入力ファイル削除（アトミック置換後）
        let sections_removed = task.input_files.len();
        for file in task.input_files {
            std::fs::remove_file(&file.path)?;
        }

        // 書き込み増幅記録
        self.strategy.write_amp_tracker.record(input_bytes, output_bytes);

        // バックプレッシャ更新
        self.backpressure.on_compaction_complete(sections_removed, input_bytes);

        Ok(output_files)
    }
}
```

### 2.3.1 書き込み増幅トラッキング

Compaction の書き込み増幅 (Write Amplification) を監視し、性能劣化を検出する。

```rust
use std::sync::atomic::{AtomicU64, Ordering};

/// 書き込み増幅トラッカー
/// WA = 総ディスク書き込み量 / ユーザ書き込み量
pub struct WriteAmpTracker {
    /// ユーザからの書き込みバイト数（WAL含む）
    user_bytes_written: AtomicU64,
    /// Compaction による書き込みバイト数
    compaction_bytes_written: AtomicU64,
    /// Flush による書き込みバイト数
    flush_bytes_written: AtomicU64,
}

impl WriteAmpTracker {
    pub fn new() -> Self {
        Self {
            user_bytes_written: AtomicU64::new(0),
            compaction_bytes_written: AtomicU64::new(0),
            flush_bytes_written: AtomicU64::new(0),
        }
    }

    /// ユーザ書き込み記録
    pub fn record_user_write(&self, bytes: u64) {
        self.user_bytes_written.fetch_add(bytes, Ordering::Relaxed);
    }

    /// Flush 書き込み記録
    pub fn record_flush(&self, bytes: u64) {
        self.flush_bytes_written.fetch_add(bytes, Ordering::Relaxed);
    }

    /// Compaction I/O 記録
    pub fn record(&self, _input_bytes: u64, output_bytes: u64) {
        self.compaction_bytes_written.fetch_add(output_bytes, Ordering::Relaxed);
    }

    /// 書き込み増幅係数を計算
    pub fn write_amplification(&self) -> f64 {
        let user = self.user_bytes_written.load(Ordering::Relaxed) as f64;
        if user == 0.0 {
            return 1.0;
        }

        let flush = self.flush_bytes_written.load(Ordering::Relaxed) as f64;
        let compact = self.compaction_bytes_written.load(Ordering::Relaxed) as f64;
        let total = user + flush + compact;

        total / user
    }

    /// メトリクス出力
    pub fn metrics(&self) -> WriteAmpMetrics {
        WriteAmpMetrics {
            user_bytes: self.user_bytes_written.load(Ordering::Relaxed),
            flush_bytes: self.flush_bytes_written.load(Ordering::Relaxed),
            compaction_bytes: self.compaction_bytes_written.load(Ordering::Relaxed),
            write_amplification: self.write_amplification(),
        }
    }

    /// カウンタリセット（定期リセット用）
    pub fn reset(&self) {
        self.user_bytes_written.store(0, Ordering::Relaxed);
        self.flush_bytes_written.store(0, Ordering::Relaxed);
        self.compaction_bytes_written.store(0, Ordering::Relaxed);
    }
}

#[derive(Debug, Clone)]
pub struct WriteAmpMetrics {
    pub user_bytes: u64,
    pub flush_bytes: u64,
    pub compaction_bytes: u64,
    pub write_amplification: f64,
}
```

### 2.3.2 External Ingest API

TiKV の `ingest_external_file` を参考に、外部で生成した TSM ファイルを直接取り込む API を提供する。
スナップショット復元やバルクロードに有効。

```rust
use std::path::Path;

/// External Ingest 設定
#[derive(Clone, Default)]
pub struct IngestOptions {
    /// 取り込み後に元ファイルを削除
    pub move_files: bool,
    /// チェックサム検証を実行
    pub verify_checksum: bool,
    /// キー範囲がオーバーラップする場合の動作
    pub allow_overlap: bool,
    /// 取り込み先レベル（None = 自動選択）
    pub target_level: Option<u8>,
}

/// External Ingest トレイト
pub trait ExternalIngest {
    /// 外部 TSM ファイルを取り込み
    ///
    /// # Arguments
    /// * `paths` - 取り込む TSM ファイルのパス
    /// * `partition` - 対象パーティション
    /// * `options` - 取り込みオプション
    ///
    /// # Returns
    /// 取り込まれたファイル情報
    fn ingest_external_files(
        &self,
        paths: &[&Path],
        partition: &TimePartition,
        options: IngestOptions,
    ) -> Result<Vec<IngestResult>>;
}

#[derive(Debug)]
pub struct IngestResult {
    pub original_path: PathBuf,
    pub ingested_path: PathBuf,
    pub level: u8,
    pub point_count: u64,
    pub size_bytes: u64,
}

impl ExternalIngest for TSMStorage {
    fn ingest_external_files(
        &self,
        paths: &[&Path],
        partition: &TimePartition,
        options: IngestOptions,
    ) -> Result<Vec<IngestResult>> {
        let mut results = Vec::with_capacity(paths.len());

        for path in paths {
            // 1. ファイル検証
            let reader = TSMReader::open(path)?;
            if options.verify_checksum {
                reader.verify_checksum()?;
            }

            // 2. メタデータ取得
            let meta = reader.metadata();

            // 3. パーティション整合性チェック
            if meta.min_timestamp < partition.start || meta.max_timestamp >= partition.end {
                return Err(Error::PartitionMismatch {
                    file_range: (meta.min_timestamp, meta.max_timestamp),
                    partition_range: (partition.start, partition.end),
                });
            }

            // 4. オーバーラップチェック
            if !options.allow_overlap {
                let existing = self.find_overlapping_files(partition, meta.min_timestamp, meta.max_timestamp)?;
                if !existing.is_empty() {
                    return Err(Error::OverlappingFiles { count: existing.len() });
                }
            }

            // 5. レベル決定
            let level = options.target_level.unwrap_or_else(|| {
                self.calculate_ingest_level(meta.size_bytes)
            });

            // 6. ファイル配置
            let dest_path = self.generate_tsm_path(partition, level);

            if options.move_files {
                std::fs::rename(path, &dest_path)?;
            } else {
                std::fs::copy(path, &dest_path)?;
            }

            // 7. メタデータ登録
            self.register_tsm_file(&dest_path, level, &meta)?;

            results.push(IngestResult {
                original_path: path.to_path_buf(),
                ingested_path: dest_path,
                level,
                point_count: meta.point_count,
                size_bytes: meta.size_bytes,
            });
        }

        Ok(results)
    }
}

impl TSMStorage {
    /// ファイルサイズに基づく取り込みレベル決定
    fn calculate_ingest_level(&self, size_bytes: u64) -> u8 {
        // L0: ~4MB, L1: ~40MB, L2: ~400MB
        if size_bytes < 4 * 1024 * 1024 {
            0
        } else if size_bytes < 40 * 1024 * 1024 {
            1
        } else {
            2
        }
    }
}
```

### 2.3.3 セクション分離設計

YugabyteDB の Intent CF / Regular CF 分離を参考に、TSM ファイル内でセクションを論理分離する。
これにより、異なる書き込みパターンのデータを分離し、Compaction コストを局所化する。

```rust
/// TSM ファイル内セクション種別
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum TSMSectionType {
    /// 通常のデータブロック（確定済みデータ）
    Regular = 0,
    /// Hot データ（直近の高頻度アクセス領域）
    Hot = 1,
    /// Cold データ（古いデータ、アクセス頻度低）
    Cold = 2,
    /// メタデータセクション（シリーズインデックス等）
    Meta = 3,
}

/// セクション分離コンフィグ
#[derive(Clone)]
pub struct SectionConfig {
    /// Hot → Regular 降格閾値（アクセスなし期間）
    pub hot_to_regular_threshold: Duration,
    /// Regular → Cold 降格閾値
    pub regular_to_cold_threshold: Duration,
    /// セクション別 Compaction 優先度
    pub compaction_priority: HashMap<TSMSectionType, u8>,
}

impl Default for SectionConfig {
    fn default() -> Self {
        Self {
            hot_to_regular_threshold: Duration::from_secs(3600),      // 1時間
            regular_to_cold_threshold: Duration::from_secs(86400),    // 24時間
            compaction_priority: [
                (TSMSectionType::Hot, 1),      // 最優先
                (TSMSectionType::Regular, 2),
                (TSMSectionType::Cold, 3),
                (TSMSectionType::Meta, 4),     // 最低優先
            ].into_iter().collect(),
        }
    }
}

/// セクション分離 Compaction スケジューラ
pub struct SectionAwareCompactionScheduler {
    config: SectionConfig,
    section_stats: HashMap<TSMSectionType, SectionStats>,
}

#[derive(Default)]
struct SectionStats {
    total_bytes: u64,
    file_count: usize,
    last_compaction: Option<Instant>,
}

impl SectionAwareCompactionScheduler {
    /// セクション別に Compaction タスクを生成
    pub fn schedule(&self, partition: &TimePartition) -> Vec<CompactionTask> {
        let mut tasks = vec![];

        // 優先度順にソート
        let mut sections: Vec<_> = self.config.compaction_priority.iter().collect();
        sections.sort_by_key(|(_, priority)| *priority);

        for (section_type, _) in sections {
            if let Some(task) = self.select_for_section(partition, *section_type) {
                tasks.push(task);
            }
        }

        tasks
    }

    fn select_for_section(
        &self,
        partition: &TimePartition,
        section_type: TSMSectionType,
    ) -> Option<CompactionTask> {
        // セクション別のファイルを取得し、閾値チェック
        // Hot セクションは小さく保ち頻繁に Compaction
        // Cold セクションは大きく保ち稀に Compaction
        let threshold = match section_type {
            TSMSectionType::Hot => 4,
            TSMSectionType::Regular => 8,
            TSMSectionType::Cold => 16,
            TSMSectionType::Meta => 4,
        };

        // 実装は省略（list_section_files など）
        None
    }
}
```

---

## 3. TSMファイル形式仕様

### 3.1 ファイルレイアウト詳細

```
Offset      Size      Description
────────────────────────────────────────────────────────────
0x0000      4         Magic: "ATSM" (0x4154534D)
0x0004      2         Version: 3 (max_lsn 対応)
0x0006      8         Min Timestamp (i64, little-endian)
0x000E      8         Max Timestamp (i64, little-endian)
0x0016      4         Series Count (u32)
0x001A      1         Compression Type (0=None, 1=Gorilla, 2=LZ4=予約)
0x001B      1         Section Flags (bit0=Hot, bit1=Cold, bit2=Meta)
0x001C      2         Level (u16, Compaction レベル)
0x001E      2         Reserved (zeroed)
────────────────────────────────────────────────────────────
0x0020      var       Data Blocks Section
                      Data Block (per series)
                        8   Series ID
                        4   Point Count
                        8   Min Timestamp
                        8   Max Timestamp
                        8   Max LSN
                        1   Timestamp Encoding (0=Raw, 1=DoD)
                        1   Value Encoding (0=Raw, 1=Gorilla)
                        4   Timestamps Size
                        var Timestamps Data (compressed)
                        4   Values Size
                        var Values Data (compressed)
                        4   Block CRC32
────────────────────────────────────────────────────────────
var         var       Series Index Section
            4         Index Entry Count
            var       Index Entries[]
                        8   Series ID
                        2   Metric Name Length
                        var Metric Name (UTF-8)
                        2   Label Count
                        var Labels[]
                              2   Key Length
                              var Key (UTF-8)
                              2   Value Length
                              var Value (UTF-8)
                        8   Data Block Offset
                        4   Data Block Length
                        4   Point Count
            4         Bloom Filter Size
            var       Bloom Filter Data (xxhash64-based)
────────────────────────────────────────────────────────────
EOF-48      48        Footer
            8         Series Index Offset
            4         Series Index Size
            8         Data Section Offset
            8         Data Section Size
            8         Total Point Count
            4         File CRC32
            4         Magic (reverse): "MSTA" (0x4D535441)
            4         Reserved
```

### 3.2 Gorillaエンコーディング仕様

**タイムスタンプ (Delta-of-Delta)**:

```
First timestamp: 64 bits raw

Subsequent timestamps:
  delta = current - previous
  delta_of_delta = delta - previous_delta

  if delta_of_delta == 0:
    write '0' (1 bit)

  else if -63 <= delta_of_delta <= 64:
    write '10' (2 bits) + value (7 bits, biased by 63)

  else if -255 <= delta_of_delta <= 256:
    write '110' (3 bits) + value (9 bits, biased by 255)

  else if -2047 <= delta_of_delta <= 2048:
    write '1110' (4 bits) + value (12 bits, biased by 2047)

  else:
    write '1111' (4 bits) + value (64 bits raw)
```

**浮動小数点値 (XOR)**:

```
First value: 64 bits raw (IEEE 754 double)

Subsequent values:
  xor = current_bits XOR previous_bits

  if xor == 0:
    write '0' (1 bit)

  else:
    write '1' (1 bit)
    leading_zeros = xor.leading_zeros()
    trailing_zeros = xor.trailing_zeros()
    meaningful_bits = 64 - leading_zeros - trailing_zeros

    if leading_zeros >= prev_leading AND trailing_zeros >= prev_trailing:
      // Reuse previous window
      write '0' (1 bit)
      write meaningful_bits using previous window

    else:
      // New window
      write '1' (1 bit)
      write leading_zeros (5 bits)
      write meaningful_bits - 1 (6 bits)
      write meaningful_bits of xor >> trailing_zeros
```

### 3.3 シリーズインデックス

```rust
/// シリーズインデックス構造
pub struct SeriesIndex {
    /// シリーズID → メタデータ + オフセット
    entries: BTreeMap<SeriesId, SeriesIndexEntry>,

    /// Bloomフィルタ（シリーズ存在チェック高速化）
    bloom: BloomFilter,

    /// ラベル逆引きインデックス
    /// label_name=label_value → [series_id, ...]
    label_index: HashMap<(String, String), Vec<SeriesId>>,
}

pub struct SeriesIndexEntry {
    series_id: SeriesId,
    metric_name: String,
    labels: Vec<(String, String)>,
    data_offset: u64,
    data_length: u32,
    point_count: u32,
    min_timestamp: i64,
    max_timestamp: i64,
}

impl SeriesIndex {
    /// ラベルマッチャーでシリーズ検索
    pub fn find_series(&self, matchers: &[LabelMatcher]) -> Vec<SeriesId> {
        if matchers.is_empty() {
            return self.entries.keys().cloned().collect();
        }

        // 最も選択性の高いマッチャーから開始
        let mut candidates: Option<HashSet<SeriesId>> = None;

        for matcher in matchers {
            let matched = match &matcher.op {
                MatchOp::Equal => {
                    self.label_index
                        .get(&(matcher.name.clone(), matcher.value.clone()))
                        .cloned()
                        .unwrap_or_default()
                }
                MatchOp::NotEqual => {
                    // 全シリーズ - マッチするシリーズ
                    let exclude: HashSet<_> = self.label_index
                        .get(&(matcher.name.clone(), matcher.value.clone()))
                        .cloned()
                        .unwrap_or_default()
                        .into_iter()
                        .collect();

                    self.entries.keys()
                        .filter(|id| !exclude.contains(id))
                        .cloned()
                        .collect()
                }
                MatchOp::Regex(re) => {
                    self.label_index.iter()
                        .filter(|((name, value), _)| {
                            name == &matcher.name && re.is_match(value)
                        })
                        .flat_map(|(_, ids)| ids.iter().cloned())
                        .collect()
                }
                // ...
            };

            let matched_set: HashSet<_> = matched.into_iter().collect();

            candidates = Some(match candidates {
                Some(prev) => prev.intersection(&matched_set).cloned().collect(),
                None => matched_set,
            });
        }

        candidates.unwrap_or_default().into_iter().collect()
    }
}
```

---

## 4. クエリエンジン仕様

### 4.1 PromQLパーサー仕様

```rust
use nom::{
    IResult,
    branch::alt,
    bytes::complete::{tag, take_while1},
    combinator::{map, opt},
    multi::separated_list0,
    sequence::{delimited, preceded, tuple},
};

/// PromQL文法 (サブセット)
///
/// expr         = aggregate_expr | binary_expr | vector_expr | number | string
/// vector_expr  = metric_name label_matchers? range? offset?
/// label_matchers = "{" label_matcher ("," label_matcher)* "}"
/// label_matcher = label_name match_op string
/// match_op     = "=" | "!=" | "=~" | "!~"
/// range        = "[" duration "]"
/// offset       = "offset" duration
/// aggregate_expr = agg_op ("by" | "without") "(" labels ")" "(" expr ")"
/// binary_expr  = expr binop expr
/// binop        = "+" | "-" | "*" | "/" | "%" | "^" | "==" | "!=" | "<" | ">" | ...

pub fn parse_promql(input: &str) -> IResult<&str, PromExpr> {
    alt((
        parse_aggregate_expr,
        parse_function_call,
        parse_binary_expr,
        parse_vector_selector,
        parse_number_literal,
        parse_string_literal,
    ))(input)
}

fn parse_vector_selector(input: &str) -> IResult<&str, PromExpr> {
    let (input, metric) = parse_metric_name(input)?;
    let (input, labels) = opt(parse_label_matchers)(input)?;
    let (input, range) = opt(parse_range)(input)?;
    let (input, offset) = opt(parse_offset)(input)?;

    Ok((input, PromExpr::VectorSelector {
        metric: metric.to_string(),
        labels: labels.unwrap_or_default(),
        range,
        offset,
    }))
}

fn parse_label_matchers(input: &str) -> IResult<&str, Vec<LabelMatcher>> {
    delimited(
        tag("{"),
        separated_list0(tag(","), parse_label_matcher),
        tag("}")
    )(input)
}

fn parse_function_call(input: &str) -> IResult<&str, PromExpr> {
    let (input, func_name) = parse_identifier(input)?;
    let (input, args) = delimited(
        tag("("),
        separated_list0(tag(","), parse_promql),
        tag(")")
    )(input)?;

    let func = match func_name {
        "rate" => PromFunction::Rate,
        "irate" => PromFunction::Irate,
        "increase" => PromFunction::Increase,
        "sum" => PromFunction::Sum,
        "avg" => PromFunction::Avg,
        "max" => PromFunction::Max,
        "min" => PromFunction::Min,
        "count" => PromFunction::Count,
        "histogram_quantile" => PromFunction::HistogramQuantile,
        _ => return Err(nom::Err::Error(/* unknown function */)),
    };

    Ok((input, PromExpr::Call { func, args }))
}
```

### 4.2 SQL-TS拡張仕様

```rust
use sqlparser::ast::{Expr, Function, FunctionArg};

/// SQL-TS専用関数
pub enum TSFunction {
    /// TIME_BUCKET('interval', timestamp_column)
    TimeBucket {
        interval: Duration,
        column: String,
    },

    /// RATE(counter_column)
    Rate { column: String },

    /// DELTA(gauge_column)
    Delta { column: String },

    /// DERIVATIVE(column)
    Derivative { column: String },

    /// FIRST(value_column, time_column)
    First { value_column: String, time_column: String },

    /// LAST(value_column, time_column)
    Last { value_column: String, time_column: String },

    /// HISTOGRAM_QUANTILE(quantile, bucket_column)
    HistogramQuantile { quantile: f64, column: String },
}

/// SQL-TS関数実行
impl TSFunction {
    pub fn execute(&self, data: &[DataPoint]) -> Result<Vec<DataPoint>> {
        match self {
            TSFunction::TimeBucket { interval, .. } => {
                // GROUP BY用のバケットタイムスタンプを計算
                Ok(data.iter()
                    .map(|p| DataPoint {
                        timestamp: time_bucket(*interval, p.timestamp),
                        ..*p
                    })
                    .collect())
            }

            TSFunction::Rate { .. } => {
                // カウンター変化率（リセット考慮）
                if data.len() < 2 {
                    return Ok(vec![]);
                }

                let mut results = Vec::with_capacity(data.len() - 1);
                for window in data.windows(2) {
                    let (p1, p2) = (&window[0], &window[1]);
                    let delta_v = if p2.value >= p1.value {
                        p2.value - p1.value
                    } else {
                        p2.value // counter reset
                    };
                    let delta_t = (p2.timestamp - p1.timestamp).as_secs_f64();
                    results.push(DataPoint {
                        timestamp: p2.timestamp,
                        value: delta_v / delta_t,
                        ..p2.clone()
                    });
                }
                Ok(results)
            }

            TSFunction::Delta { .. } => {
                if data.len() < 2 {
                    return Ok(vec![]);
                }

                Ok(data.windows(2)
                    .map(|w| DataPoint {
                        timestamp: w[1].timestamp,
                        value: w[1].value - w[0].value,
                        ..w[1].clone()
                    })
                    .collect())
            }

            TSFunction::First { .. } => {
                Ok(data.first().cloned().into_iter().collect())
            }

            TSFunction::Last { .. } => {
                Ok(data.last().cloned().into_iter().collect())
            }

            // ...
        }
    }
}

/// TIME_BUCKET実装
fn time_bucket(interval: Duration, timestamp: Timestamp) -> Timestamp {
    let interval_nanos = interval.as_nanos() as i64;
    let ts_nanos = timestamp.as_nanos();
    Timestamp::from_nanos((ts_nanos / interval_nanos) * interval_nanos)
}
```

### 4.3 クエリプランナー

```rust
/// クエリ実行プラン
pub enum QueryPlan {
    /// シーケンシャルスキャン
    SeqScan {
        table: String,
        time_range: TimeRange,
        series_filter: Option<Vec<LabelMatcher>>,
    },

    /// インデックススキャン
    IndexScan {
        table: String,
        index: String,
        time_range: TimeRange,
        series_ids: Vec<SeriesId>,
    },

    /// フィルタ
    Filter {
        input: Box<QueryPlan>,
        predicate: Expr,
    },

    /// 時系列集約
    TimeAggregate {
        input: Box<QueryPlan>,
        bucket: Duration,
        aggregates: Vec<AggregateSpec>,
        group_by: Vec<String>,
    },

    /// 時系列関数適用
    TimeFunction {
        input: Box<QueryPlan>,
        function: TSFunction,
    },

    /// マージ（分散クエリ用）
    Merge {
        inputs: Vec<QueryPlan>,
        order_by: Vec<OrderSpec>,
    },

    /// シャードスキャッター
    ShardScatter {
        plan: Box<QueryPlan>,
        shards: Vec<ShardId>,
    },
}

/// プランナー
pub struct QueryPlanner {
    schema: SchemaCache,
    stats: TableStats,
}

impl QueryPlanner {
    pub fn plan(&self, query: &ParsedQuery) -> Result<QueryPlan> {
        match query {
            ParsedQuery::PromQL(expr) => self.plan_promql(expr),
            ParsedQuery::SqlTS(stmt) => self.plan_sqlts(stmt),
        }
    }

    fn plan_promql(&self, expr: &PromExpr) -> Result<QueryPlan> {
        match expr {
            PromExpr::VectorSelector { metric, labels, range, .. } => {
                // シリーズインデックスで対象シリーズ特定
                let series_ids = self.schema.find_series(metric, labels)?;

                // 時間範囲スキャン
                let time_range = range.map(|r| TimeRange::last(r))
                    .unwrap_or(TimeRange::instant());

                Ok(QueryPlan::IndexScan {
                    table: metric.clone(),
                    index: "series_idx".to_string(),
                    time_range,
                    series_ids,
                })
            }

            PromExpr::Call { func, args } => {
                let input = self.plan_promql(&args[0])?;

                let ts_func = match func {
                    PromFunction::Rate => TSFunction::Rate { column: "value".to_string() },
                    PromFunction::Sum => return Ok(QueryPlan::TimeAggregate {
                        input: Box::new(input),
                        bucket: Duration::from_secs(0), // instant
                        aggregates: vec![AggregateSpec::sum("value")],
                        group_by: vec![],
                    }),
                    // ...
                };

                Ok(QueryPlan::TimeFunction {
                    input: Box::new(input),
                    function: ts_func,
                })
            }

            // ...
        }
    }

    fn plan_sqlts(&self, stmt: &Statement) -> Result<QueryPlan> {
        // sqlparser ASTをQueryPlanに変換
        // TIME_BUCKET, RATE等の関数を検出してTimeFunction/TimeAggregateに変換
        unimplemented!()
    }
}
```

---

## 5. クラスタ仕様

### 5.1 シャーディング

```rust
/// シャードキー計算
pub fn compute_shard(metric: &str, labels: &[(String, String)], shard_count: u32) -> ShardId {
    let mut hasher = XxHash64::default();

    // メトリクス名
    hasher.write(metric.as_bytes());

    // ラベル（ソート済み）
    let mut sorted_labels = labels.to_vec();
    sorted_labels.sort_by(|a, b| a.0.cmp(&b.0));

    for (k, v) in &sorted_labels {
        hasher.write(k.as_bytes());
        hasher.write(v.as_bytes());
    }

    let hash = hasher.finish();
    ShardId((hash % shard_count as u64) as u32)
}

/// シャードルーター
pub struct ShardRouter {
    /// シャード配置マップ
    shard_map: RwLock<ShardMap>,

    /// Chirpsメッシュ
    mesh: Arc<Mesh>,
}

impl ShardRouter {
    /// 書き込みルーティング
    pub async fn route_write(&self, points: Vec<DataPoint>) -> Result<()> {
        // シャードごとにグループ化
        let mut by_shard: HashMap<ShardId, Vec<DataPoint>> = HashMap::new();

        for point in points {
            let shard = compute_shard(&point.metric, &point.labels, self.shard_count());
            by_shard.entry(shard).or_default().push(point);
        }

        // 各シャードリーダーに送信
        let map = self.shard_map.read().await;
        let futures: Vec<_> = by_shard.into_iter()
            .map(|(shard, points)| {
                let leader = map.get_leader(shard);
                self.send_write(leader, points)
            })
            .collect();

        futures::future::try_join_all(futures).await?;
        Ok(())
    }

    /// クエリルーティング（スキャッター・ギャザー）
    pub async fn route_query(&self, query: &QueryPlan) -> Result<QueryResult> {
        // 対象シャードを特定
        let target_shards = self.determine_target_shards(query)?;

        // 各シャードに並列クエリ
        let map = self.shard_map.read().await;
        let futures: Vec<_> = target_shards.iter()
            .map(|shard| {
                let node = map.get_any_replica(*shard); // 読み取りはレプリカでもOK
                self.send_query(node, query.clone())
            })
            .collect();

        let results = futures::future::try_join_all(futures).await?;

        // 結果マージ
        self.merge_results(results)
    }
}
```

### 5.2 Chirps Raft統合

> **参照**: [chirps-raft-integration-proposal.md](chirps-raft-integration-proposal.md)

Skulkは `alopex-chirps` が提供するRaft Consensus APIを利用する。
Raftメッセージの送受信は `chirps-raft` モジュールが自動的に処理するため、
アプリケーション側ではRaftメッセージを直接扱う必要はない。

```rust
use alopex_chirps::{Mesh, MessageProfile, NodeId};
use alopex_chirps::raft::{StateMachine, MultiRaftManager, WalRaftStorage};

/// Skulkアプリケーションメッセージ（Raft以外）
/// Raftメッセージは chirps-raft が自動的に Control Profile で処理
#[derive(Serialize, Deserialize)]
pub enum SkulkMessage {
    /// クエリリクエスト（シャード間分散クエリ）
    QueryRequest {
        query_id: Uuid,
        plan: QueryPlan,
    },

    /// クエリ応答
    QueryResponse {
        query_id: Uuid,
        result: Result<Vec<DataPoint>, String>,
    },

    /// シャードメタデータ同期（SWIM Gossip経由）
    ShardMetaSync {
        shard_id: ShardId,
        version: u64,
        leader: NodeId,
        replicas: Vec<NodeId>,
    },

    /// Changefeed通知
    ChangefeedEvent {
        series_id: SeriesId,
        points: Vec<DataPoint>,
    },
}

/// Skulk クラスタノード
/// Chirps MultiRaftManager を使用してシャード単位のRaftグループを管理
pub struct SkulkClusterNode {
    /// Multi-Raft マネージャ（Chirps提供）
    /// シャードごとにRaftグループを持ち、自動的にリーダー選出・レプリケーションを行う
    multi_raft: MultiRaftManager<ShardStateMachine, WalRaftStorage>,

    /// シャードルーティング
    shard_router: ShardRouter,

    /// Chirps メッシュ（QUIC Transport + SWIM）
    mesh: Arc<Mesh>,

    /// クエリエンジン
    query_engine: Arc<QueryEngine>,
}

impl SkulkClusterNode {
    /// 初期化
    pub async fn new(config: ClusterConfig, mesh: Arc<Mesh>) -> Result<Self> {
        // WalRaftStorage: alopex-core の WAL を利用した Raft ログ永続化
        let storage_factory = WalRaftStorageFactory::new(&config.data_dir);

        let multi_raft = MultiRaftManager::new(
            mesh.clone(),
            storage_factory,
        );

        Ok(Self {
            multi_raft,
            shard_router: ShardRouter::new(&config.shard_config),
            mesh,
            query_engine: Arc::new(QueryEngine::new()),
        })
    }

    /// シャード作成（Raftグループも作成）
    pub async fn create_shard(
        &mut self,
        shard_id: ShardId,
        initial_members: Vec<NodeId>,
    ) -> Result<()> {
        let state_machine = ShardStateMachine::new(shard_id);

        self.multi_raft.create_group(
            shard_id.into(),
            initial_members,
            state_machine,
        ).await
    }

    /// メトリクス書き込み（Raft経由で合意）
    pub async fn write_metrics(&self, points: Vec<DataPoint>) -> Result<()> {
        // 1. メトリクスをシャードごとにグループ化
        let grouped = self.shard_router.group_by_shard(&points);

        // 2. 各シャードに並列で書き込み
        let futures: Vec<_> = grouped.into_iter().map(|(shard_id, shard_points)| {
            async move {
                let raft_node = self.multi_raft.get_group(shard_id)
                    .ok_or(Error::ShardNotFound)?;

                // Raft リーダーにコマンドを提案
                // リーダーでなければ NotLeader エラーが返る
                let command = ShardCommand::WritePoints { points: shard_points };
                raft_node.propose(command).await
            }
        }).collect();

        futures::future::try_join_all(futures).await?;
        Ok(())
    }

    /// アプリケーションメッセージハンドラ（Raft以外）
    pub async fn handle_message(&self, from: NodeId, payload: &[u8]) -> Result<()> {
        let msg: SkulkMessage = bincode::deserialize(payload)?;

        match msg {
            SkulkMessage::QueryRequest { query_id, plan } => {
                // ローカルクエリ実行
                let result = self.query_engine.execute(&plan).await;
                let response = SkulkMessage::QueryResponse {
                    query_id,
                    result: result.map_err(|e| e.to_string()),
                };
                // クエリ応答はEphemeral（損失時はリトライ）
                self.mesh.send_to(
                    from,
                    &bincode::serialize(&response)?,
                    MessageProfile::Ephemeral
                ).await?;
            }

            SkulkMessage::ShardMetaSync { shard_id, version, leader, replicas } => {
                // シャードメタデータ更新
                self.shard_router.update_meta(shard_id, version, leader, replicas).await?;
            }

            SkulkMessage::ChangefeedEvent { series_id, points } => {
                // Changefeed処理（外部サブスクライバーへの転送など）
                self.handle_changefeed(series_id, points).await?;
            }

            _ => {}
        }

        Ok(())
    }
}
```

**Message Profile使い分け**:

| メッセージ種別 | Profile | 理由 |
|--------------|---------|------|
| Raft AppendEntries/Vote | Control | chirps-raft が自動処理、最高優先度 |
| クエリリクエスト/応答 | Ephemeral | 損失時はクライアントがリトライ |
| Changefeed | Durable | 到達保証が必要 |
| ShardMetaSync | Ephemeral | Gossipで冗長に配信 |

### 5.3 タイムスタンプ実装

> **参照**: [design-spec-tsdb.md](design-spec-tsdb.md) Section 3.1.7

TSDBとしてのタイムスタンプ処理実装仕様。

#### 5.3.1 タイムスタンプ型定義

```rust
/// Skulkで使用するタイムスタンプ型
/// ナノ秒精度のUnix epoch
pub type Timestamp = i64;

/// タイムスタンプ精度
#[derive(Clone, Copy, Debug)]
pub enum TimestampPrecision {
    Nanoseconds,   // 10^-9 (デフォルト)
    Microseconds,  // 10^-6
    Milliseconds,  // 10^-3
    Seconds,       // 10^0
}

impl TimestampPrecision {
    /// 指定精度からナノ秒に変換
    pub fn to_nanos(&self, value: i64) -> Timestamp {
        match self {
            Self::Nanoseconds => value,
            Self::Microseconds => value * 1_000,
            Self::Milliseconds => value * 1_000_000,
            Self::Seconds => value * 1_000_000_000,
        }
    }
}
```

#### 5.3.2 タイムスタンプ割り当て

```rust
/// Ingestハンドラのタイムスタンプ処理
pub struct TimestampAssigner {
    /// クロックスキュー許容範囲
    max_clock_skew: Duration,

    /// 未来のタイムスタンプ許容範囲
    max_future_offset: Duration,
}

impl Default for TimestampAssigner {
    fn default() -> Self {
        Self {
            max_clock_skew: Duration::from_secs(60),      // 1分
            max_future_offset: Duration::from_secs(300), // 5分
        }
    }
}

impl TimestampAssigner {
    /// タイムスタンプを検証・割り当て
    pub fn assign(&self, point: &mut DataPoint) -> Result<()> {
        let now = self.current_time();

        match point.timestamp {
            Some(ts) => {
                // クライアント指定の場合は検証
                self.validate_client_timestamp(ts, now)?;
            }
            None => {
                // 省略時はサーバー時刻を割り当て
                point.timestamp = Some(now);
            }
        }
        Ok(())
    }

    /// 現在時刻取得（ナノ秒精度）
    fn current_time(&self) -> Timestamp {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos() as i64
    }

    /// クライアント指定タイムスタンプの検証
    fn validate_client_timestamp(&self, ts: Timestamp, now: Timestamp) -> Result<()> {
        let future_limit = now + self.max_future_offset.as_nanos() as i64;

        if ts > future_limit {
            return Err(Error::TimestampTooFarInFuture {
                timestamp: ts,
                limit: future_limit,
            });
        }

        // 過去のタイムスタンプはO3設定で処理するため、ここでは許可
        Ok(())
    }
}
```

#### 5.3.3 Out-of-Order (O3) 処理

```rust
/// O3データ処理
pub struct O3Handler {
    config: O3Config,
    metrics: O3Metrics,
}

/// O3設定
#[derive(Clone, Debug)]
pub struct O3Config {
    /// O3許容ウィンドウ
    pub allowed_window: Duration,

    /// 古すぎるデータのポリシー
    pub too_old_policy: TooOldPolicy,

    /// 現在パーティションより古いパーティションへの書き込み許可
    pub allow_backfill: bool,
}

impl Default for O3Config {
    fn default() -> Self {
        Self {
            allowed_window: Duration::from_secs(3600),  // 1時間
            too_old_policy: TooOldPolicy::AcceptWithWarning,
            allow_backfill: true,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub enum TooOldPolicy {
    Reject,
    AcceptWithWarning,
    Drop,
}

impl O3Handler {
    /// O3データの処理判定
    pub fn handle(&self, point: &DataPoint, current_partition: &TimePartition) -> O3Decision {
        let point_ts = point.timestamp.unwrap();
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos() as i64;

        let age = now - point_ts;
        let allowed_nanos = self.config.allowed_window.as_nanos() as i64;

        if age <= allowed_nanos {
            // 許容範囲内
            O3Decision::Accept
        } else {
            // 許容範囲外
            self.metrics.too_old_count.fetch_add(1, Ordering::Relaxed);

            match self.config.too_old_policy {
                TooOldPolicy::Reject => O3Decision::Reject(Error::DataTooOld { age }),
                TooOldPolicy::AcceptWithWarning => {
                    tracing::warn!(
                        timestamp = point_ts,
                        age_secs = age / 1_000_000_000,
                        "Accepting out-of-order data outside allowed window"
                    );
                    O3Decision::Accept
                }
                TooOldPolicy::Drop => {
                    self.metrics.dropped_count.fetch_add(1, Ordering::Relaxed);
                    O3Decision::Drop
                }
            }
        }
    }
}

pub enum O3Decision {
    Accept,
    Drop,
    Reject(Error),
}
```

#### 5.3.4 クエリ時のNOW()処理

```rust
/// クエリコンテキスト
#[derive(Clone, Debug)]
pub struct QueryContext {
    /// クエリID
    pub query_id: Uuid,

    /// クエリ開始時刻（NOW()の値）
    pub now_timestamp: Timestamp,

    /// タイムアウト
    pub timeout: Duration,

    /// クエリ精度（ダウンサンプリング済みデータの解像度）
    pub precision: TimestampPrecision,
}

/// クエリコーディネーター
impl QueryCoordinator {
    /// クエリ実行
    pub async fn execute(&self, sql: &str) -> Result<QueryResult> {
        // コーディネーターのローカル時刻を NOW() として確定
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos() as i64;

        let ctx = QueryContext {
            query_id: Uuid::new_v4(),
            now_timestamp: now,
            timeout: self.config.query_timeout,
            precision: TimestampPrecision::Nanoseconds,
        };

        // SQL解析でNOW()を ctx.now_timestamp に置換
        let plan = self.planner.plan(sql, &ctx)?;

        // 分散実行
        self.execute_plan(plan, ctx).await
    }
}

/// NOW()関数の評価
impl SqlEvaluator {
    fn eval_now(&self, ctx: &QueryContext) -> Timestamp {
        ctx.now_timestamp
    }

    fn eval_interval(&self, base: Timestamp, interval: &Interval) -> Timestamp {
        base - interval.as_nanos() as i64
    }
}
```

#### 5.3.5 クロックスキュー監視

```rust
/// クロックスキュー監視
pub struct ClockSkewMonitor {
    /// 最大許容スキュー
    max_skew: Duration,

    /// 他ノードとのスキュー記録
    peer_skews: RwLock<HashMap<NodeId, i64>>,

    /// メトリクス
    metrics: ClockMetrics,
}

impl ClockSkewMonitor {
    /// Gossipメッセージ受信時にスキューを計測
    pub fn observe_peer(&self, peer: NodeId, peer_timestamp: Timestamp) {
        let local = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos() as i64;

        let skew = (peer_timestamp - local).abs();

        // スキュー記録
        self.peer_skews.write().insert(peer, skew);

        // メトリクス更新
        self.metrics.skew_gauge.set(skew as f64 / 1_000_000.0);  // ms

        // 警告閾値チェック
        if skew > self.max_skew.as_nanos() as i64 {
            tracing::warn!(
                peer = %peer,
                skew_ms = skew / 1_000_000,
                "Clock skew exceeds threshold"
            );
        }
    }

    /// 現在の最大スキューを取得
    pub fn max_observed_skew(&self) -> Duration {
        let max_nanos = self.peer_skews
            .read()
            .values()
            .copied()
            .max()
            .unwrap_or(0);

        Duration::from_nanos(max_nanos as u64)
    }
}
```

---

## 6. 設定仕様

### 6.1 設定ファイル形式

```toml
# alopex-skulk.toml

[server]
# HTTP APIリッスンアドレス
listen_addr = "0.0.0.0:8086"
# gRPCリッスンアドレス（オプション）
grpc_addr = "0.0.0.0:8087"

[storage]
# データディレクトリ
data_dir = "/var/lib/alopex-skulk/data"
# WALディレクトリ
wal_dir = "/var/lib/alopex-skulk/wal"

# MemTableサイズ（フラッシュ閾値）
memtable_size = "64MB"
# MemTableフラッシュ間隔
memtable_flush_interval = "15m"

# Skulkファイル設定
[storage.skulk]
compression = "gorilla"  # none, gorilla, lz4
block_size = "4KB"

# Compaction設定
[storage.compaction]
enabled = true
interval = "1h"
level0_file_limit = 4
level1_file_limit = 10

[retention]
# デフォルト保持期間
default_retention = "7d"

# ダウンサンプリング設定
[[retention.downsample]]
source_retention = "72h"
target_retention = "30d"
interval = "1h"
aggregates = ["avg", "max", "min", "count"]

[[retention.downsample]]
source_retention = "30d"
target_retention = "1y"
interval = "1d"
aggregates = ["avg", "max", "min", "count", "p50", "p99"]

[cluster]
# クラスタモード有効化
enabled = false
# ノードID（空の場合は自動生成）
node_id = ""
# シードノード
seeds = ["node1:9100", "node2:9100"]
# シャード数
shard_count = 16
# レプリケーションファクター
replication_factor = 3

[cluster.chirps]
# Chirps設定（QUIC Transport + SWIM + Raft）
listen_addr = "0.0.0.0:9100"
quic_cert = "/etc/alopex-skulk/cert.pem"
quic_key = "/etc/alopex-skulk/key.pem"

[cluster.chirps.raft]
# Raft Consensus API設定（chirps-raft）
# 選挙タイムアウト（ミリ秒）
election_timeout_ms = 1000
# ハートビート間隔（ミリ秒）
heartbeat_interval_ms = 150
# 最大ログエントリバッチサイズ
max_batch_size = 1000
# スナップショット閾値（ログエントリ数）
snapshot_threshold = 10000

[query]
# 最大同時クエリ数
max_concurrent_queries = 100
# クエリタイムアウト
query_timeout = "30s"
# 最大ポイント数（メモリ保護）
max_points_per_query = 10_000_000

[alert]
# アラートエンジン有効化
enabled = true
# 評価間隔
eval_interval = "15s"

[logging]
level = "info"  # trace, debug, info, warn, error
format = "json"  # json, text

[metrics]
# Prometheusメトリクスエンドポイント
enabled = true
listen_addr = "0.0.0.0:9090"
```

### 6.2 Embedded API設定

```rust
/// Embedded TSDB設定
pub struct EmbeddedConfig {
    /// データディレクトリ
    pub data_dir: PathBuf,

    /// インメモリモード（テスト用）
    pub in_memory: bool,

    /// 保持ポリシー
    pub retention: RetentionConfig,

    /// ストレージ設定
    pub storage: StorageConfig,

    /// クエリ設定
    pub query: QueryConfig,
}

impl Default for EmbeddedConfig {
    fn default() -> Self {
        Self {
            data_dir: PathBuf::from("./tsdb_data"),
            in_memory: false,
            retention: RetentionConfig {
                default_retention: Duration::from_secs(7 * 24 * 3600), // 7d
                downsample: vec![],
            },
            storage: StorageConfig {
                memtable_size: 64 * 1024 * 1024, // 64MB
                compression: Compression::Gorilla,
            },
            query: QueryConfig {
                max_points: 1_000_000,
                timeout: Duration::from_secs(30),
            },
        }
    }
}

/// Embedded TSDB使用例
pub fn example_embedded_usage() -> Result<()> {
    let config = EmbeddedConfig {
        data_dir: PathBuf::from("/tmp/my_tsdb"),
        retention: RetentionConfig {
            default_retention: Duration::from_secs(72 * 3600), // 72h
            ..Default::default()
        },
        ..Default::default()
    };

    let db = EmbeddedTSDB::open(config)?;

    // 書き込み
    db.write_points(&[
        DataPoint {
            metric: "cpu".to_string(),
            labels: vec![("host".to_string(), "server1".to_string())],
            timestamp: Timestamp::now(),
            value: 45.2,
        },
    ])?;

    // クエリ
    let results = db.query_promql("rate(cpu{host='server1'}[5m])")?;

    Ok(())
}
```

---

## 7. 変更履歴

| バージョン | 日付 | 変更者 | 変更内容 |
|----------|------|--------|---------|
| 1.0 | 2025-11-29 | Claude | 初版作成 |
| 1.1 | 2025-11-29 | Claude | file-format-comparison.md を参考にリファイン:<br>- §2.1.1 バックプレッシャ制御追加 (Pebble/TiKV参照)<br>- §2.3.1 書き込み増幅トラッキング追加<br>- §2.3.2 External Ingest API追加 (TiKV参照)<br>- §2.3.3 セクション分離設計追加 (YugabyteDB参照)<br>- §3.1 TSMヘッダ拡張 (Version 2, Section Flags, Level) |
| 1.2 | 2025-11-29 | Claude | 製品名を「Alopex Skulk」に変更:<br>- alopex-tsdb → alopex-skulk |
