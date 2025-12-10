# Alopex Skulk 要求仕様書

**バージョン**: 1.0
**最終更新日**: 2025-11-29
**ステータス**: Draft

---

## 1. エグゼクティブサマリー

### 1.1 プロジェクト概要

Alopex Skulkは、**Alopex Coreを基盤とする時系列データベース**である。監視・IoT・ログ分析など、時間経過に伴うデータのライフサイクル管理を主眼とし、Alopex DB本体とは**独立したサブプロジェクト**として開発する。

> **命名由来**: 「Skulk」はキツネの群れを意味する英語の集合名詞。Alopex（北極キツネ）の群れが静かに獲物を追うように、バックグラウンドで時系列データを収集し続ける様を表現。

**コアバリュー**: Ephemeral. Streaming. Observable.

- **Ephemeral（一過性）**: データは消耗品、自動TTL/ダウンサンプリングで鮮度管理
- **Streaming（ストリーミング）**: 高速インジェスト、連続クエリ、リアルタイムアラート
- **Observable（可観測性）**: メトリクス/ログ/トレースの統合基盤

### 1.2 Alopex DBとの関係

| 観点 | Alopex DB | Alopex Skulk |
|------|-----------|-------------|
| **ユースケース** | RAG/AI、知識ベース、OLTP | 監視、IoT、ログ分析 |
| **データ寿命** | 長期保持（資産） | 短期ローテーション（消耗品） |
| **主要操作** | CRUD + 類似検索 | 追記 + 集約 + TTL削除 |
| **クエリパターン** | 点検索、JOIN、ベクトル検索 | 範囲集約、ダウンサンプリング |
| **削除パターン** | 明示的DELETE | 自動TTL満了 |

**共有基盤**:
- `alopex-core`: LSM-Tree、WAL、Compaction（フォーク or trait抽象化）
- `alopex-chirps`: クラスタ通信
  - Raft Consensus API（chirps-raft）: 分散合意、レプリケーション
  - SWIM Membership（chirps-gossip-swim）: ノード検出、障害検知
  - QUIC Transport（chirps-transport-quic）: セキュア通信

### 1.3 市場ニーズ

**現状の課題**:
1. **監視スタックの複雑さ**: Prometheus + InfluxDB + Grafana + Loki の組み合わせ
2. **ライフサイクル管理の手動化**: TTL、ダウンサンプリングの設定が煩雑
3. **スケーラビリティの壁**: 単一ノードPrometheusの限界
4. **エッジとクラウドの断絶**: IoTデバイスとクラウド監視の統合困難

**Alopex Skulkの解決策**:
- Alopex Core基盤による統一ストレージ
- ポリシーベースの自動ライフサイクル管理
- Embedded → Distributed のシームレススケール
- PromQL互換 + SQL-TS拡張

---

## 2. ステークホルダー要求

### 2.1 対象ユーザー

#### プライマリユーザー
1. **SRE/インフラエンジニア**
   - システム監視、アラート設定
   - ダッシュボード構築

2. **IoTプラットフォーム開発者**
   - センサーデータ収集
   - エッジ-クラウド連携

3. **ログ分析エンジニア**
   - アプリケーションログ解析
   - 異常検知

#### セカンダリユーザー
4. **データエンジニア**
   - ETLパイプライン構築
   - データウェアハウス連携

5. **アプリケーション開発者**
   - アプリケーション内メトリクス
   - ユーザー行動分析

### 2.2 主要要求

#### 機能要求（FR）

**FR-TSDB-001: 時系列データモデル**
- タイムスタンプ + ラベル（タグ）+ 値の3要素モデル
- 多次元ラベルによるフィルタリング
- 高カーディナリティラベル対応

**FR-TSDB-002: 高速インジェスト**
- Line Protocol互換（InfluxDB形式）
- Prometheus Remote Write対応
- バッチ/ストリーミング両対応

**FR-TSDB-003: ライフサイクル管理**
- 時刻ベースTTL（例: 72時間、7日、30日）
- 自動ダウンサンプリング（例: 1分 → 1時間 → 1日）
- 保持ポリシーのカスケード

**FR-TSDB-004: クエリ言語**
- PromQL互換サブセット
- SQL-TS拡張（時系列関数追加）
- 連続クエリ（Continuous Query）

**FR-TSDB-005: アラート**
- 閾値ベースアラート
- 異常検知（将来）
- Webhook/Slack通知

**FR-TSDB-006: マルチモード展開**
- Embedded: エッジデバイス、組み込み
- Single-Node: 小〜中規模監視
- Distributed: 大規模クラスタ

#### 非機能要求（NFR）

**NFR-TSDB-001: パフォーマンス**
- インジェストスループット: >500,000 points/sec (単一ノード)
- クエリレイテンシ: <100ms (P99, 24時間範囲集約)
- 圧縮率: >10:1 (Gorilla + LZ4)

**NFR-TSDB-002: 可用性**
- Uptime: 99.9% (3ノードクラスタ)
- データ損失: 最大1分（設定可能なWALバッファ）

**NFR-TSDB-003: ストレージ効率**
- Gorilla圧縮（タイムスタンプ + 値）
- Delta-of-Delta エンコーディング
- 辞書エンコーディング（ラベル）

**NFR-TSDB-004: 運用性**
- Prometheus互換エンドポイント
- Grafanaネイティブ連携
- Kubernetes Operator（将来）

---

## 3. システム要求

### 3.1 機能要求詳細

#### 3.1.1 データモデル

**要求ID**: SR-TSDB-MODEL-001
**概要**: 時系列データの論理モデル

**データ構造**:
```
Metric:
  name: string              # メトリクス名 (例: "cpu_usage")
  labels: Map<string, string>  # タグ/ラベル (例: {"host": "server1", "region": "ap-northeast-1"})
  timestamp: i64            # Unix timestamp (ナノ秒)
  value: f64                # 数値

Series:
  metric_name + label_set → unique time series
```

**DDL例**:
```sql
-- 時系列テーブル定義
CREATE TIMESERIES TABLE cpu_metrics (
  time TIMESTAMP NOT NULL,
  host TAG,
  region TAG,
  cpu TAG,
  usage_user FIELD FLOAT,
  usage_system FIELD FLOAT,
  usage_idle FIELD FLOAT
) WITH (
  retention = '7d',           -- 7日間保持
  downsample = '1h:30d,1d:1y' -- 1時間集約を30日、1日集約を1年
);
```

**検証基準**:
- [ ] 100万ユニークシリーズの登録が可能
- [ ] ラベルカーディナリティ10万でも検索性能劣化<20%
- [ ] タイムスタンプ精度: ナノ秒

---

#### 3.1.2 タイムスタンプ設計

**要求ID**: SR-TSDB-TIMESTAMP-001
**概要**: 時系列データのタイムスタンプ決定戦略

> **設計方針**: Skulkは高スループット・低レイテンシを優先し、データポイントのタイムスタンプには**Raft TSO（厳密順序タイムスタンプ）を使用しない**。これはAlopex DB本体（MVCC/トランザクション向けにRaft TSOを使用）とは異なる設計判断である。

**Chirpsタイムスタンプサービスとの関係**:

| Chirpsサービス | Skulkでの用途 | 理由 |
|---------------|--------------|------|
| **Raft TSO** | 使用しない（データポイント） | スループット優先、レイテンシ削減 |
| **Gossip HLC** | 必要時のみ（ノード間イベント順序付け） | インフラ層での利用に限定 |
| **ローカル時刻** | データポイントのデフォルトタイムスタンプ | 高スループット、低レイテンシ |

**タイムスタンプソース決定マトリクス**:

| ユースケース | タイムスタンプソース | 理由 |
|------------|------------------|------|
| **クライアント指定** | クライアント提供値 | センサーデータ等、発生時刻が重要 |
| **サーバー割当** | Ingestノードのローカル時刻 | 高スループット維持、Raft往復不要 |
| **クエリ NOW()** | Coordinatorのローカル時刻 | クエリ実行時の基準時刻 |
| **TTL/ダウンサンプリング** | 各ノードのローカル時刻 | 厳密同期不要、近似で十分 |
| **Out-of-Order許容** | 設定可能な許容ウィンドウ | 遅延データの受け入れ制御 |

**Out-of-Order (O3) データ処理**:

```rust
/// O3データ処理ポリシー
pub struct O3Config {
    /// 許容するO3ウィンドウ（デフォルト: 5分）
    pub allowed_window: Duration,
    /// ウィンドウ外データの処理ポリシー
    pub too_old_policy: TooOldPolicy,
}

pub enum TooOldPolicy {
    /// 拒否（エラー返却）
    Reject,
    /// 警告ログを出して受け入れ
    AcceptWithWarning,
    /// 静かにドロップ
    Drop,
}
```

**クロックスキュー監視**:

```rust
/// ノード間時刻差の監視
/// Gossip経由で各ノードの時刻を交換し、大きなスキューを検出
pub struct ClockSkewMonitor {
    /// 警告閾値（デフォルト: 1秒）
    pub warning_threshold: Duration,
    /// クリティカル閾値（デフォルト: 5秒）
    pub critical_threshold: Duration,
}
```

**検証基準**:
- [ ] クライアント指定タイムスタンプが正確に保存される
- [ ] サーバー割当時のスループット劣化が<5%
- [ ] O3データが設定ポリシーに従って処理される
- [ ] クロックスキュー>1秒で警告ログが出力される

---

#### 3.1.3 インジェスト

**要求ID**: SR-TSDB-INGEST-001
**概要**: 高速データ取り込み

**サポートプロトコル**:
```
1. Line Protocol (InfluxDB互換)
   cpu,host=server1,region=ap usage_user=23.5,usage_system=12.3 1609459200000000000

2. Prometheus Remote Write (protobuf)
   POST /api/v1/write
   Content-Type: application/x-protobuf
   Body: snappy-compressed protobuf

3. JSON API
   POST /api/v1/ingest
   {
     "metric": "cpu",
     "tags": {"host": "server1"},
     "fields": {"usage_user": 23.5},
     "timestamp": 1609459200000000000
   }
```

**バッファリング戦略**:
```
Write Path:
  1. Receive → Parse → Validate
  2. Write to WAL (fsync per batch)
  3. Insert to MemTable (time-partitioned)
  4. Acknowledge to client
  5. Background: MemTable → TSM File (flush)
```

**検証基準**:
- [ ] Line Protocol: 500K points/sec
- [ ] Remote Write: 100K samples/sec
- [ ] バッチサイズ10K points で <10ms レイテンシ

---

#### 3.1.4 ライフサイクル管理

**要求ID**: SR-TSDB-LIFECYCLE-001
**概要**: 自動データローテーション

**TTLポリシー**:
```sql
-- テーブルレベルTTL
ALTER TIMESERIES TABLE cpu_metrics SET retention = '72h';

-- シャード/パーティション単位削除
-- 内部: 時刻パーティション単位でファイル削除（個別行削除なし）
```

**ダウンサンプリング**:
```sql
-- 連続集約定義
CREATE CONTINUOUS AGGREGATE cpu_hourly
FROM cpu_metrics
GROUP BY time_bucket('1 hour', time), host, region
SELECT
  time_bucket('1 hour', time) AS time,
  host,
  region,
  avg(usage_user) AS usage_user_avg,
  max(usage_user) AS usage_user_max,
  min(usage_user) AS usage_user_min
WITH (
  retention = '30d',
  refresh_interval = '1h'
);
```

**ライフサイクルカスケード**:
```
Raw Data (1s resolution)
    │ TTL: 72h
    ▼
Hourly Aggregate (1h resolution)
    │ TTL: 30d
    ▼
Daily Aggregate (1d resolution)
    │ TTL: 1y
    ▼
Archive/Delete
```

**検証基準**:
- [ ] TTL満了データが自動削除される
- [ ] ダウンサンプリングがバックグラウンドで実行
- [ ] パーティション削除が<1秒で完了

---

#### 3.1.5 クエリ

**要求ID**: SR-TSDB-QUERY-001
**概要**: 時系列クエリ言語

**PromQL互換**:
```promql
# 直近5分のCPU使用率
cpu_usage{host="server1"}[5m]

# 1分間隔の平均
avg_over_time(cpu_usage{host="server1"}[1m])

# ラベルでグループ化
sum by (region) (rate(http_requests_total[5m]))
```

**SQL-TS拡張**:
```sql
-- TIME_BUCKET: 時間バケット集約
SELECT
  TIME_BUCKET('1 hour', time) AS bucket,
  host,
  AVG(usage_user) AS avg_usage
FROM cpu_metrics
WHERE time > NOW() - INTERVAL '24 hours'
GROUP BY bucket, host
ORDER BY bucket DESC;

-- RATE: 変化率計算
SELECT
  TIME_BUCKET('5 minutes', time) AS bucket,
  RATE(requests_total) AS requests_per_sec
FROM http_metrics
WHERE time > NOW() - INTERVAL '1 hour';

-- FIRST/LAST: 期間内の最初/最後の値
SELECT
  TIME_BUCKET('1 day', time) AS day,
  FIRST(price, time) AS open,
  LAST(price, time) AS close,
  MAX(price) AS high,
  MIN(price) AS low
FROM stock_prices
GROUP BY day;

-- DELTA: 差分計算
SELECT
  TIME_BUCKET('1 hour', time) AS hour,
  DELTA(counter_total) AS increase
FROM counters;

-- DERIVATIVE: 微分（変化率/秒）
SELECT
  time,
  DERIVATIVE(temperature) AS temp_change_per_sec
FROM sensor_data;
```

**検証基準**:
- [ ] PromQL基本関数（rate, sum, avg, max, min）動作
- [ ] TIME_BUCKET + GROUP BY が正しく集約
- [ ] 24時間範囲クエリが<100ms

---

#### 3.1.6 アラート

**要求ID**: SR-TSDB-ALERT-001
**概要**: リアルタイムアラート

**アラート定義**:
```sql
CREATE ALERT high_cpu
ON cpu_metrics
WHERE usage_user > 90
FOR '5 minutes'
NOTIFY webhook('https://slack.example.com/webhook');

CREATE ALERT disk_full
ON disk_metrics
WHERE usage_percent > 95
SEVERITY critical
NOTIFY email('ops@example.com'), pagerduty('service-key');
```

**アラート状態遷移**:
```
INACTIVE → PENDING → FIRING → RESOLVED
              │         │
              └─────────┘ (条件継続)
```

**検証基準**:
- [ ] 閾値超過から通知まで<30秒
- [ ] FOR句による継続条件判定
- [ ] 複数通知先への同時送信

---

### 3.2 ストレージ設計

#### 3.2.1 TSMファイル形式

**要求ID**: SR-TSDB-STORAGE-001
**概要**: 時系列最適化ストレージ形式

**ファイル構造** (`.skulk` 拡張子):
```
┌─────────────────────────────────────────────────────────────┐
│                   Skulk File (.skulk)                        │
├─────────────────────────────────────────────────────────────┤
│  File Header (32 bytes)                                      │
│  - Magic: "ATSM" (4 bytes)                                   │
│  - Version: u16 (2 bytes)                                    │
│  - Min Timestamp: i64 (8 bytes)                              │
│  - Max Timestamp: i64 (8 bytes)                              │
│  - Series Count: u32 (4 bytes)                               │
│  - Compression: u8 (1 byte)                                  │
│  - Reserved: 5 bytes                                         │
├─────────────────────────────────────────────────────────────┤
│  Series Index Block                                          │
│  - Series entries (metric + labels → offset)                 │
│  - Bloom filter for series lookup                            │
├─────────────────────────────────────────────────────────────┤
│  Data Blocks (repeated per series)                           │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Block Header                                            ││
│  │  - Series ID: u64                                        ││
│  │  - Point Count: u32                                      ││
│  │  - Min/Max Timestamp: i64 x 2                            ││
│  │  - Compression Type: u8                                  ││
│  ├─────────────────────────────────────────────────────────┤│
│  │  Timestamp Column (Gorilla-encoded)                      ││
│  │  - Delta-of-delta encoding                               ││
│  │  - XOR compression                                       ││
│  ├─────────────────────────────────────────────────────────┤│
│  │  Value Column (Gorilla-encoded)                          ││
│  │  - XOR compression for floats                            ││
│  │  - RLE for repeated values                               ││
│  └─────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│  Footer                                                      │
│  - Index Block Offset: u64                                   │
│  - Checksum: u32                                             │
│  - Magic (reverse): "MSTA"                                   │
└─────────────────────────────────────────────────────────────┘
```

**時刻パーティション**:
```
/data/
  /2025-11-29/           # 日次パーティション
    /00/                 # 時間パーティション（オプション）
      series_0001.skulk
      series_0002.skulk
    /01/
      ...
  /2025-11-28/
    ...
```

**検証基準**:
- [ ] Gorilla圧縮で10:1以上の圧縮率
- [ ] 時刻パーティション単位の高速削除
- [ ] シリーズインデックスによる<1ms検索

---

#### 3.2.2 Alopex Core連携

**要求ID**: SR-TSDB-CORE-001
**概要**: Alopex Core基盤の活用

**共有コンポーネント**:
```rust
// alopex-core から継承/利用
use alopex_core::{
    wal::WriteAheadLog,      // WAL（そのまま利用）
    memtable::MemTable,      // MemTable（trait化して時系列向け拡張）
    compaction::Compactor,   // Compaction（時刻ベース戦略を追加）
};

// 時系列専用拡張
pub struct TimeSeriesMemTable {
    // 時刻パーティションごとのMemTable
    partitions: BTreeMap<TimePartition, MemTable>,
}

pub struct TimeSeriesCompactor {
    // 時刻ベースCompaction + ダウンサンプリング統合
    base: Compactor,
    downsample_config: DownsampleConfig,
}
```

**検証基準**:
- [ ] WAL再生で時系列データが復元
- [ ] MemTable → TSMファイルのflush動作
- [ ] 時刻ベースCompactionが正常動作

---

### 3.3 分散アーキテクチャ

**要求ID**: SR-TSDB-CLUSTER-001
**概要**: 分散時系列クラスタ

**シャーディング戦略**:
```
Shard Key = hash(metric_name + label_set) % shard_count

各シャードは時刻パーティションを持つ:
  Shard 0:
    /2025-11-29/ → Node A (Leader), Node B, Node C
    /2025-11-28/ → Node A (Leader), Node B, Node C
  Shard 1:
    /2025-11-29/ → Node B (Leader), Node C, Node A
    ...
```

**Chirps Raft統合**:

> **参照**: [chirps-raft-integration-proposal.md](chirps-raft-integration-proposal.md)

```rust
// Chirps Raft Consensus API を利用
use alopex_chirps::{Mesh, MessageProfile};
use alopex_chirps::raft::{StateMachine, MultiRaftManager, WalRaftStorage};

// ShardStateMachine: Skulk側で実装
// Raftロジックは chirps-raft が提供
pub struct ShardStateMachine { /* ... */ }

impl StateMachine for ShardStateMachine {
    type Command = ShardCommand;
    // ... apply, snapshot, restore
}

// クラスタノードは MultiRaftManager を使用
// Raftメッセージは chirps-raft が Control Profile で自動送信
let cluster_node = SkulkClusterNode::new(config, mesh).await?;

// メトリクス書き込み（Raft経由で合意）
cluster_node.write_metrics(points).await?;
```

**検証基準**:
- [ ] 3ノードクラスタで1ノード障害時も継続
- [ ] シャード間クエリの透過的統合
- [ ] リバランス時のデータ損失なし

---

## 4. ユースケース

### 4.1 UC-TSDB-001: Kubernetes監視

**アクター**: SREエンジニア

**フロー**:
1. Prometheusがクラスタメトリクスを収集
2. Remote WriteでAlopex Skulkに送信
3. Grafanaダッシュボードでリアルタイム可視化
4. アラートルールで異常通知

**期待結果**:
- Prometheus互換で既存ワークフローを維持
- 長期保存コストを90%削減（ダウンサンプリング）

---

### 4.2 UC-TSDB-002: IoTセンサーデータ

**アクター**: IoTプラットフォーム開発者

**フロー**:
1. エッジデバイスでAlopex Skulk Embeddedを起動
2. センサーデータをローカル保存（72時間TTL）
3. 定期的にクラウドへ集約データを同期
4. エッジでリアルタイムアラート発報

**期待結果**:
- オフライン動作可能
- ネットワーク帯域を95%削減（集約後同期）

---

### 4.3 UC-TSDB-003: アプリケーションログ分析

**アクター**: ログ分析エンジニア

**フロー**:
1. アプリケーションログをLine Protocolで送信
2. ログレベル/サービス別にタグ付け
3. SQL-TSで異常パターン検出
4. 連続クエリでリアルタイム集計

**期待結果**:
- 構造化ログと非構造化ログの統合検索
- 秒単位の異常検知

---

## 5. インターフェース要求

### 5.1 インジェストAPI

```bash
# Line Protocol
curl -X POST http://localhost:8086/write \
  -d 'cpu,host=server1 usage=23.5 1609459200000000000'

# Prometheus Remote Write
curl -X POST http://localhost:8086/api/v1/write \
  -H "Content-Type: application/x-protobuf" \
  -H "Content-Encoding: snappy" \
  --data-binary @metrics.pb
```

### 5.2 クエリAPI

```bash
# PromQL
curl -G http://localhost:8086/api/v1/query \
  --data-urlencode 'query=rate(http_requests_total[5m])'

# SQL-TS
curl -X POST http://localhost:8086/api/v1/sql \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT TIME_BUCKET('"'"'1h'"'"', time), AVG(usage) FROM cpu GROUP BY 1"}'
```

### 5.3 管理API

```bash
# 保持ポリシー設定
curl -X PUT http://localhost:8086/api/v1/retention/cpu_metrics \
  -H "Content-Type: application/json" \
  -d '{"retention": "7d", "downsample": [{"interval": "1h", "retention": "30d"}]}'

# シャード情報取得
curl http://localhost:8086/api/v1/shards
```

---

## 6. 品質要求

### 6.1 信頼性

**REL-TSDB-001: データ耐久性**
- WALによる書き込み保証
- 設定可能な同期間隔（1秒〜1分）

**REL-TSDB-002: 障害復旧**
- RTO: <5分
- RPO: <1分（WALバッファ依存）

### 6.2 保守性

**MAIN-TSDB-001: 監視**
- 内部メトリクスのself-monitoring
- Grafanaダッシュボードテンプレート

**MAIN-TSDB-002: 運用**
- オンラインリテンション変更
- ローリングアップグレード対応

---

## 7. リリースマイルストーン

### v0.1 TSM Core（alopex-core v0.2 依存）

**ファイル配置**:
```
crates/skulk/src/
├── tsm/
│   ├── mod.rs
│   ├── memtable.rs       # TimeSeriesMemTable
│   ├── gorilla.rs        # Gorilla圧縮
│   └── file.rs           # TSMファイル形式
├── lib.rs
└── error.rs
```

**タスク**:
- [ ] TimeSeriesMemTable 実装
- [ ] Gorilla 圧縮（タイムスタンプ、値）
- [ ] TSM ファイル形式（.skulk）

### v0.2 Lifecycle（Skulk v0.1 依存）

**ファイル配置**:
```
crates/skulk/src/
├── lifecycle/
│   ├── mod.rs
│   ├── ttl_manager.rs    # TTL Manager
│   ├── partition.rs      # 時刻パーティショニング
│   └── compaction.rs     # Compaction
```

**タスク**:
- [ ] TTL Manager（自動削除）
- [ ] 時刻パーティショニング（日/時間単位）
- [ ] Compaction（時系列最適化）

### v0.3 Ingest（Skulk v0.2 依存）

**ファイル配置**:
```
crates/skulk/src/
├── ingest/
│   ├── mod.rs
│   ├── line_protocol.rs  # Line Protocol パーサー
│   ├── remote_write.rs   # Prometheus Remote Write
│   └── json.rs           # JSON インジェスト
```

**タスク**:
- [ ] Line Protocol パーサー（InfluxDB互換）
- [ ] Prometheus Remote Write（protobuf）
- [ ] JSON インジェスト API

### v0.4 Query（Skulk v0.3 依存）

**ファイル配置**:
```
crates/skulk/src/
├── query/
│   ├── mod.rs
│   ├── promql/
│   │   ├── mod.rs
│   │   ├── parser.rs     # PromQL パーサー
│   │   └── executor.rs   # PromQL エグゼキュータ
│   ├── sql_ts/
│   │   ├── mod.rs
│   │   └── functions.rs  # TIME_BUCKET, RATE, DELTA
│   └── engine.rs         # クエリエンジン
```

**タスク**:
- [ ] PromQL パーサー（基本サブセット）
- [ ] SQL-TS 拡張（TIME_BUCKET, RATE, DELTA, FIRST, LAST）
- [ ] クエリ実行エンジン

### v0.5 Downsampling（Skulk v0.4 依存）

**ファイル配置**:
```
crates/skulk/src/
├── downsample/
│   ├── mod.rs
│   ├── downsampler.rs    # Downsampler
│   └── continuous.rs     # Continuous Query
```

**タスク**:
- [ ] Downsampler（自動ダウンサンプリング）
- [ ] Continuous Query（連続クエリ）

### v0.6 Server（Skulk v0.5 依存）

**ファイル配置**:
```
crates/skulk-server/src/
├── api/
│   ├── mod.rs
│   ├── write.rs          # /write エンドポイント
│   ├── query.rs          # /query エンドポイント
│   └── admin.rs          # 管理API
├── prometheus/
│   ├── mod.rs
│   └── compat.rs         # Prometheus互換エンドポイント
├── metrics.rs            # Self-monitoring
└── main.rs
```

**タスク**:
- [ ] HTTP API（/write, /query, /api/v1/*）
- [ ] Prometheus 互換エンドポイント
- [ ] Self-monitoring メトリクス

### v0.7 Alert（Skulk v0.6 依存）

**ファイル配置**:
```
crates/skulk/src/
├── alert/
│   ├── mod.rs
│   ├── rule.rs           # AlertRule
│   ├── evaluator.rs      # ルール評価
│   └── notifier.rs       # 通知先連携
```

**タスク**:
- [ ] AlertRule（閾値ベースアラート）
- [ ] 通知先連携（Webhook, Slack, Email）

### v0.8 Distributed（Skulk v0.7 + Chirps v0.3 依存）

**ファイル配置**:
```
crates/skulk-cluster/src/
├── shard/
│   ├── mod.rs
│   ├── manager.rs        # シャード管理
│   └── router.rs         # ShardRouter
├── query/
│   └── distributed.rs    # 分散クエリ
└── lib.rs
```

**タスク**:
- [ ] シャーディング（metric_name + label_set ハッシュ）
- [ ] ShardRouter（クエリルーティング）
- [ ] 分散クエリ（シャード間集約）

### v0.9 Replication（Skulk v0.8 + Chirps v0.6 依存）

**タスク**:
- [ ] シャード Raft グループ（ShardStateMachine + Chirps Raft API）
- [ ] リーダー選出/フェイルオーバー

### v1.0 Stable

**タスク**:
- [ ] ドキュメント整備
- [ ] 性能チューニング

---

## 8. 変更履歴

| バージョン | 日付 | 変更者 | 変更内容 |
|----------|------|--------|---------|
| 1.0 | 2025-11-29 | Claude | 初版作成 |
| 1.1 | 2025-11-29 | Claude | 製品名を「Alopex Skulk」に変更:<br>- 「Skulk」= キツネの群れを意味する英語の集合名詞 |
| 1.2 | 2025-11-29 | Claude | タイムスタンプ設計要件を追加（3.1.2節）:<br>- Raft TSOを使用しない設計判断<br>- O3データ処理ポリシー<br>- クロックスキュー監視 |
| 1.3 | 2025-11-30 | Claude | リリースマイルストーン詳細化（7節）:<br>- ファイル配置<br>- 各バージョンの実装タスク |

---

## 付録A: 用語集

- **TSM**: Time-Structured Merge Tree（時系列最適化ストレージ形式）
- **Gorilla**: Facebook製時系列圧縮アルゴリズム
- **PromQL**: Prometheus Query Language
- **Downsampling**: データの時間解像度を下げる集約処理
- **TTL**: Time To Live（データ保持期間）
- **Continuous Query**: 定期実行される集約クエリ

## 付録B: 参考文献

1. InfluxDB Documentation: https://docs.influxdata.com/
2. Prometheus Documentation: https://prometheus.io/docs/
3. TimescaleDB Documentation: https://docs.timescale.com/
4. Facebook Gorilla Paper: "Gorilla: A Fast, Scalable, In-Memory Time Series Database"
5. Alopex DB Requirements: ./requirements.md
