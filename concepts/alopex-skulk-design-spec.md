# Alopex Skulk 方式設計書

**バージョン**: 1.0
**最終更新日**: 2025-11-29
**ステータス**: Draft

---

## 1. システムアーキテクチャ

### 1.1 全体アーキテクチャ

```
┌────────────────────────────────────────────────────────────────┐
│                         Client Layer                           │
│  (Prometheus, Telegraf, Grafana, Custom Apps)                  │
└────────────────────┬───────────────────────────────────────────┘
                     │
┌────────────────────┴───────────────────────────────────────────┐
│                    Ingest Gateway Layer                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │ Line Protocol│  │ Remote Write │  │ JSON API     │        │
│  │ Parser       │  │ (Protobuf)   │  │              │        │
│  └──────────────┘  └──────────────┘  └──────────────┘        │
└────────────────────┬───────────────────────────────────────────┘
                     │
┌────────────────────┴───────────────────────────────────────────┐
│                   Query Processing Layer                       │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  PromQL Parser → SQL-TS Parser → Planner → Executor      │ │
│  └──────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Continuous Query Engine + Alert Evaluator               │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────┬───────────────────────────────────────────┘
                     │
┌────────────────────┴───────────────────────────────────────────┐
│                  Lifecycle Management Layer                    │
│  ┌──────────────────┐  ┌───────────────┐  ┌─────────────────┐│
│  │ TTL Manager      │  │ Downsampler   │  │ Retention       ││
│  │                  │  │               │  │ Policy Engine   ││
│  └──────────────────┘  └───────────────┘  └─────────────────┘│
└────────────────────┬───────────────────────────────────────────┘
                     │
┌────────────────────┴───────────────────────────────────────────┐
│                      Storage Layer                             │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Time Series Engine (TSM)                                 │ │
│  │  ┌──────────┐  ┌────────────┐  ┌───────────────────┐   │ │
│  │  │ MemTable │  │ Immutable  │  │ TSM Files         │   │ │
│  │  │ (time-   │  │ MemTables  │  │ (time-partitioned)│   │ │
│  │  │ partitioned)│ │            │  │                   │   │ │
│  │  └──────────┘  └────────────┘  └───────────────────┘   │ │
│  └──────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Alopex Core (WAL, Compaction Base)                       │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────┬───────────────────────────────────────────┘
                     │
┌────────────────────┴───────────────────────────────────────────┐
│            Distribution Layer (Cluster Mode Only)              │
│  ┌──────────────┐  ┌─────────────────────────────────────────┐ │
│  │ Shard        │  │ alopex-chirps (Raft Consensus API)      │ │
│  │ Manager      │  │  - ShardStateMachine (Skulk側で実装)    │ │
│  │              │  │  - MultiRaftManager (シャード毎Raft)    │ │
│  │              │  │  - SWIM Membership + QUIC Transport     │ │
│  └──────────────┘  └─────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

### 1.2 Alopex DBとの差異

```
┌─────────────────────────────────────────────────────────────────┐
│                    Shared Foundation                             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    alopex-core                           │   │
│  │  - WAL (Write-Ahead Log)                                │   │
│  │  - MemTable (base implementation)                       │   │
│  │  - Compaction Framework                                  │   │
│  │  - Basic KV Operations                                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   alopex-chirps                          │   │
│  │  - QUIC Transport (chirps-transport-quic)               │   │
│  │  - SWIM Membership (chirps-gossip-swim)                 │   │
│  │  - Raft Consensus API (chirps-raft)                     │   │
│  │    * StateMachine / RaftStorage traits                  │   │
│  │    * RaftNode, MultiRaftManager                         │   │
│  │    * HybridTimestamp (TSO)                              │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
          │                                      │
          ▼                                      ▼
┌─────────────────────────┐        ┌─────────────────────────┐
│      Alopex DB          │        │     Alopex Skulk        │
│  ┌───────────────────┐  │        │  ┌───────────────────┐  │
│  │ SQL Parser        │  │        │  │ PromQL Parser     │  │
│  │ (sqlparser-rs)    │  │        │  │ + SQL-TS Parser   │  │
│  └───────────────────┘  │        │  └───────────────────┘  │
│  ┌───────────────────┐  │        │  ┌───────────────────┐  │
│  │ Vector Index      │  │        │  │ TSM Storage       │  │
│  │ (Flat/HNSW)       │  │        │  │ (Gorilla Compress)│  │
│  └───────────────────┘  │        │  └───────────────────┘  │
│  ┌───────────────────┐  │        │  ┌───────────────────┐  │
│  │ Transaction       │  │        │  │ Lifecycle Manager │  │
│  │ Manager (MVCC)    │  │        │  │ (TTL/Downsample)  │  │
│  └───────────────────┘  │        │  └───────────────────┘  │
│  ┌───────────────────┐  │        │  ┌───────────────────┐  │
│  │ Range Sharding    │  │        │  │ Time+Hash Shard   │  │
│  └───────────────────┘  │        │  └───────────────────┘  │
│                         │        │  ┌───────────────────┐  │
│  Use Case:              │        │  │ Alert Engine      │  │
│  - RAG/AI              │        │  └───────────────────┘  │
│  - OLTP                │        │                         │
│  - Knowledge Base      │        │  Use Case:              │
│                         │        │  - Monitoring          │
│                         │        │  - IoT                 │
│                         │        │  - Log Analysis        │
└─────────────────────────┘        └─────────────────────────┘
```

### 1.3 モード別アーキテクチャ

#### 1.3.1 Embedded Mode

```
┌─────────────────────────────────────┐
│     Application Process             │
│                                     │
│  ┌───────────────────────────────┐ │
│  │   Alopex Skulk Embedded API   │ │
│  └───────────┬───────────────────┘ │
│              │                     │
│  ┌───────────┴───────────────────┐ │
│  │   Ingest + Query Engine       │ │
│  │   Lifecycle Manager           │ │
│  │   TSM Storage                 │ │
│  └───────────┬───────────────────┘ │
│              │                     │
│  ┌───────────┴───────────────────┐ │
│  │   Local Disk                  │ │
│  │   /data/                      │ │
│  │     /2025-11-29/*.skulk       │ │
│  │     /2025-11-28/*.skulk       │ │
│  └───────────────────────────────┘ │
└─────────────────────────────────────┘

Use Case: Edge IoT, Mobile Monitoring Agent
```

#### 1.3.2 Single-Node Server

```
┌─────────────────────────────────────┐
│   HTTP Server Process               │
│                                     │
│  ┌───────────────────────────────┐ │
│  │   API Server                  │ │
│  │   - /write (Line Protocol)    │ │
│  │   - /api/v1/write (Remote)    │ │
│  │   - /api/v1/query (PromQL)    │ │
│  │   - /api/v1/sql (SQL-TS)      │ │
│  └───────────┬───────────────────┘ │
│              │                     │
│  ┌───────────┴───────────────────┐ │
│  │   Query + Ingest Engine       │ │
│  │   Alert Evaluator             │ │
│  │   Continuous Query Runner     │ │
│  │   Lifecycle Manager           │ │
│  └───────────┬───────────────────┘ │
│              │                     │
│  ┌───────────┴───────────────────┐ │
│  │   TSM Storage                 │ │
│  │   (Time-Partitioned)          │ │
│  └───────────────────────────────┘ │
└─────────────────────────────────────┘

Use Case: Small-Medium Monitoring, Dev Environment
```

#### 1.3.3 Distributed Cluster

```
┌─────────────────────────────────────────────────────────────┐
│                    Cluster (3+ Nodes)                       │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Node 1     │  │   Node 2     │  │   Node 3     │     │
│  │              │  │              │  │              │     │
│  │  ┌────────┐  │  │  ┌────────┐  │  │  ┌────────┐  │     │
│  │  │ Shard  │  │  │  │ Shard  │  │  │  │ Shard  │  │     │
│  │  │ 0 (L)  │  │  │  │ 0 (F)  │  │  │  │ 0 (F)  │  │     │
│  │  └────────┘  │  │  └────────┘  │  │  └────────┘  │     │
│  │  ┌────────┐  │  │  ┌────────┐  │  │  ┌────────┐  │     │
│  │  │ Shard  │  │  │  │ Shard  │  │  │  │ Shard  │  │     │
│  │  │ 1 (F)  │  │  │  │ 1 (L)  │  │  │  │ 1 (F)  │  │     │
│  │  └────────┘  │  │  └────────┘  │  │  └────────┘  │     │
│  │              │  │              │  │              │     │
│  │  Time Parts: │  │  Time Parts: │  │  Time Parts: │     │
│  │  /11-29/     │  │  /11-29/     │  │  /11-29/     │     │
│  │  /11-28/     │  │  /11-28/     │  │  /11-28/     │     │
│  │              │  │              │  │              │     │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘     │
│         │                 │                 │              │
│         └─────────────────┼─────────────────┘              │
│                           │                                │
│              ┌────────────┴────────────┐                   │
│              │   alopex-chirps         │                   │
│              │  - Raft Consensus API   │                   │
│              │  - SWIM Membership      │                   │
│              │  - QUIC Transport       │                   │
│              └─────────────────────────┘                   │
└─────────────────────────────────────────────────────────────┘

Sharding: hash(metric_name + labels) % shard_count
L: Leader, F: Follower
```

---

## 2. データフロー設計

### 2.1 書き込みフロー

```
Client (Prometheus/Telegraf)
     │
     ▼
┌─────────────────┐
│  1. Parse       │
│     Protocol    │
│     (Line/PB)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  2. Validate    │
│     & Enrich    │
│     (labels)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  3. Route to    │
│     Shard       │
│     (hash)      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  4. Write WAL   │
│     (batch)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  5. Insert to   │
│     MemTable    │
│     (time-part) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  6. Acknowledge │
└─────────────────┘

Background Tasks:
- MemTable → TSM Flush (when size > threshold OR time elapsed)
- TSM Compaction (periodic, level-based within time partition)
- TTL Deletion (drop entire time partition)
- Downsampling (aggregate older partitions)
```

### 2.1.1 ディスク書き込み戦略

**設計方針**: Alopex DB同様、時刻パーティション単位で単一`.skulk`ファイルに収束させる。
稼働中はWAL + 現行Skulkファイルの2本立て、安定後は`.skulk`単体で完全状態。

```
┌─────────────────────────────────────────────────────────────────────┐
│                    TSDB 書き込みシーケンス                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  write(points)                                                      │
│       │                                                             │
│       ▼                                                             │
│  ┌─────────────────┐                                               │
│  │ WAL append      │ ← fsync (batch: max 10K points or 100ms)      │
│  │ (.wal)          │                                               │
│  └────────┬────────┘                                               │
│           │                                                         │
│           ▼                                                         │
│  ┌─────────────────┐                                               │
│  │ MemTable insert │ ← 時刻パーティション別に振り分け              │
│  │ (in-memory)     │                                               │
│  └────────┬────────┘                                               │
│           │                                                         │
│     flush trigger?                                                  │
│     (size >= 64MB OR age >= 15min)                                 │
│           │                                                         │
│           ▼                                                         │
│  ┌─────────────────┐                                               │
│  │ Build .skulk.tmp│ ← Gorilla圧縮でセクション書き出し             │
│  │ (temp file)     │                                               │
│  └────────┬────────┘                                               │
│           │                                                         │
│       fsync(tmp)                                                    │
│           │                                                         │
│           ▼                                                         │
│  ┌─────────────────┐                                               │
│  │ atomic rename   │ ← rename(.skulk.tmp → partition.skulk)        │
│  │                 │                                               │
│  └────────┬────────┘                                               │
│           │                                                         │
│           ▼                                                         │
│  ┌─────────────────┐                                               │
│  │ truncate WAL    │ ← flush済み範囲を削除                         │
│  └─────────────────┘                                               │
│                                                                     │
│  最終状態: partition_YYYYMMDD_HH.skulk (単一ファイル)              │
└─────────────────────────────────────────────────────────────────────┘
```

**ファイル構成（稼働中）**:
```
/data/tsdb/
├── shard_0/
│   ├── 2025-11-29/
│   │   ├── partition_00.skulk      # 確定済み (00:00-01:00)
│   │   ├── partition_01.skulk      # 確定済み (01:00-02:00)
│   │   ├── partition_14.skulk.tmp  # flush中 (一時ファイル)
│   │   └── current.wal           # 現在のWAL
│   └── 2025-11-28/
│       └── *.skulk               # 全パーティション確定済み
└── shard_1/
    └── ...
```

**バックプレッシャ制御** (Pebble/TiKV参考):
```rust
pub struct BackpressureController {
    /// 未flush TSMセクション数
    pending_sections: AtomicUsize,

    /// Compaction負債（バイト）
    compaction_debt: AtomicU64,

    /// 閾値
    config: BackpressureConfig,
}

pub struct BackpressureConfig {
    /// 書き込み遅延開始閾値
    soft_limit_sections: usize,      // default: 8

    /// 書き込み停止閾値
    hard_limit_sections: usize,      // default: 16

    /// Compaction負債閾値
    compaction_debt_threshold: u64,  // default: 256MB

    /// 遅延計算係数
    delay_multiplier_ms: u64,        // default: 10
}

impl BackpressureController {
    /// 書き込み前の遅延計算
    pub fn calculate_delay(&self) -> Duration {
        let sections = self.pending_sections.load(Ordering::Relaxed);
        let debt = self.compaction_debt.load(Ordering::Relaxed);

        if sections >= self.config.hard_limit_sections {
            return Duration::MAX; // ブロック
        }

        if sections >= self.config.soft_limit_sections {
            let over = sections - self.config.soft_limit_sections;
            let delay_ms = over as u64 * self.config.delay_multiplier_ms;
            return Duration::from_millis(delay_ms);
        }

        if debt > self.config.compaction_debt_threshold {
            let over_ratio = debt as f64 / self.config.compaction_debt_threshold as f64;
            let delay_ms = (over_ratio * 10.0) as u64;
            return Duration::from_millis(delay_ms);
        }

        Duration::ZERO
    }
}
```

**セクション分離設計** (YugabyteDB Intent CF参考):

TSDBでは時系列の特性上、Intent/Lock CFは不要だが、
データ特性に応じたセクション分離を検討:

```
┌─────────────────────────────────────────────────────────────┐
│                    TSM File Sections                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Section Type 0x01: Hot Series Data                         │
│  ├─ 高頻度アクセスシリーズ                                  │
│  ├─ Compaction優先度: 高                                    │
│  └─ キャッシュ優先度: 高                                    │
│                                                             │
│  Section Type 0x02: Cold Series Data                        │
│  ├─ 低頻度アクセスシリーズ                                  │
│  ├─ Compaction優先度: 低                                    │
│  └─ 圧縮率重視                                              │
│                                                             │
│  Section Type 0x03: Series Index                            │
│  ├─ シリーズメタデータ + Bloom Filter                       │
│  └─ 常にメモリにキャッシュ                                  │
│                                                             │
│  Section Type 0x04: Tombstones (TTL markers)                │
│  ├─ 削除マーカー（パーティション単位削除が基本なので軽量）  │
│  └─ Compaction時にGC                                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 クエリフロー

```
Client Request (PromQL / SQL-TS)
     │
     ▼
┌─────────────────┐
│  1. Parse Query │
│     (PromQL →   │
│     AST/SQL)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  2. Plan        │
│     - Time Range│
│     - Shard Map │
│     - Aggregates│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  3. Scatter to  │
│     Shards      │
│     (parallel)  │
└────────┬────────┘
         │
    ┌────┴────┬────────┐
    │         │        │
    ▼         ▼        ▼
┌───────┐ ┌───────┐ ┌───────┐
│Shard 0│ │Shard 1│ │Shard N│
│ Scan  │ │ Scan  │ │ Scan  │
└───┬───┘ └───┬───┘ └───┬───┘
    │         │        │
    └────┬────┴────────┘
         │
         ▼
┌─────────────────┐
│  4. Gather &    │
│     Merge       │
│     (time-sort) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  5. Apply       │
│     Functions   │
│     (rate,sum)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  6. Return      │
│     Results     │
└─────────────────┘
```

### 2.3 ライフサイクルフロー

```
Data Lifecycle Pipeline
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

     Ingest                                              Delete
        │                                                   │
        ▼                                                   ▼
┌───────────────────────────────────────────────────────────────┐
│   Raw Data (1s resolution)                                    │
│   TTL: 72h                                                    │
│   Partition: /data/raw/2025-11-29/                           │
│                                                               │
│   [point] [point] [point] [point] [point] ...                │
└───────────────────────────────┬───────────────────────────────┘
                                │
                     Downsample (hourly aggregate)
                                │
                                ▼
┌───────────────────────────────────────────────────────────────┐
│   Hourly Aggregate (1h resolution)                            │
│   TTL: 30d                                                    │
│   Partition: /data/hourly/2025-11-29/                        │
│                                                               │
│   [avg,max,min,count] [avg,max,min,count] ...                │
└───────────────────────────────┬───────────────────────────────┘
                                │
                     Downsample (daily aggregate)
                                │
                                ▼
┌───────────────────────────────────────────────────────────────┐
│   Daily Aggregate (1d resolution)                             │
│   TTL: 1y                                                     │
│   Partition: /data/daily/2025-11/                            │
│                                                               │
│   [avg,max,min,count,p50,p99] ...                            │
└───────────────────────────────┬───────────────────────────────┘
                                │
                          TTL Expiry
                                │
                                ▼
                           [DELETE]
```

---

## 3. 主要コンポーネント設計

### 3.1 TSM Storage Engine

#### 3.1.1 時系列最適化MemTable

```rust
/// 時刻パーティション付きMemTable
pub struct TimeSeriesMemTable {
    /// 現在のパーティション (例: 2025-11-29T14:00)
    current_partition: TimePartition,

    /// パーティションごとのデータ
    /// Key: (series_id, timestamp)
    /// Value: field_values
    partitions: BTreeMap<TimePartition, SeriesMemTable>,

    /// シリーズインデックス
    /// metric_name + labels → series_id
    series_index: HashMap<SeriesKey, SeriesId>,

    /// 現在のメモリ使用量
    memory_usage: AtomicUsize,

    /// Flush閾値
    flush_threshold: usize,  // default: 64MB
}

struct SeriesMemTable {
    /// 時刻順にソートされたポイント
    data: BTreeMap<(SeriesId, Timestamp), FieldValues>,

    /// 統計情報
    stats: PartitionStats,
}

struct PartitionStats {
    min_timestamp: Timestamp,
    max_timestamp: Timestamp,
    point_count: u64,
    series_count: u32,
}
```

#### 3.1.2 TSMファイル構造

```
Skulk File Layout (.skulk)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Offset    Section
──────    ───────────────────────────────────────────
0x0000    File Header (32 bytes)
          ├─ Magic: "ATSM" (4 bytes)
          ├─ Version: 1 (2 bytes)
          ├─ Min Timestamp (8 bytes)
          ├─ Max Timestamp (8 bytes)
          ├─ Series Count (4 bytes)
          ├─ Compression: 0=None, 1=Gorilla, 2=LZ4 (1 byte)
          └─ Reserved (5 bytes)

0x0020    Series Index Section
          ├─ Index Entry Count (4 bytes)
          └─ Index Entries (variable)
              ├─ Series ID (8 bytes)
              ├─ Metric Name Length (2 bytes)
              ├─ Metric Name (variable)
              ├─ Label Count (2 bytes)
              ├─ Labels (key-value pairs)
              ├─ Data Block Offset (8 bytes)
              └─ Data Block Length (4 bytes)

          Bloom Filter (for series lookup)
          ├─ Filter Size (4 bytes)
          └─ Filter Data (variable)

Variable  Data Blocks Section
          ┌─────────────────────────────────────────┐
          │  Data Block (per series)                │
          │  ├─ Block Header (16 bytes)             │
          │  │   ├─ Series ID (8 bytes)             │
          │  │   ├─ Point Count (4 bytes)           │
          │  │   └─ Checksum (4 bytes)              │
          │  │                                      │
          │  ├─ Timestamps Column (Gorilla)         │
          │  │   ├─ First Timestamp (8 bytes)       │
          │  │   └─ Delta-of-Delta encoded          │
          │  │                                      │
          │  └─ Values Column (Gorilla)             │
          │      ├─ First Value (8 bytes)           │
          │      └─ XOR encoded                     │
          └─────────────────────────────────────────┘

EOF-48    Footer (48 bytes)
          ├─ Series Index Offset (8 bytes)
          ├─ Series Index Size (4 bytes)
          ├─ Data Section Offset (8 bytes)
          ├─ Data Section Size (8 bytes)
          ├─ Total Points (8 bytes)
          ├─ Footer Checksum (4 bytes)
          └─ Magic (reverse): "MSTA" (4 bytes)
          └─ Reserved (4 bytes)
```

#### 3.1.3 Gorilla圧縮実装

```rust
/// Gorilla圧縮エンコーダ（タイムスタンプ用）
pub struct TimestampEncoder {
    prev_timestamp: i64,
    prev_delta: i64,
    bit_writer: BitWriter,
}

impl TimestampEncoder {
    pub fn encode(&mut self, timestamp: i64) {
        if self.is_first() {
            // 最初のタイムスタンプは64ビットそのまま
            self.bit_writer.write_bits(timestamp as u64, 64);
            self.prev_timestamp = timestamp;
            return;
        }

        let delta = timestamp - self.prev_timestamp;
        let delta_of_delta = delta - self.prev_delta;

        // Delta-of-Deltaエンコーディング
        match delta_of_delta {
            0 => {
                // 同じ間隔: 1ビット (0)
                self.bit_writer.write_bit(false);
            }
            -63..=64 => {
                // 7ビット範囲: 2ビット(10) + 7ビット値
                self.bit_writer.write_bits(0b10, 2);
                self.bit_writer.write_bits((delta_of_delta + 63) as u64, 7);
            }
            -255..=256 => {
                // 9ビット範囲: 3ビット(110) + 9ビット値
                self.bit_writer.write_bits(0b110, 3);
                self.bit_writer.write_bits((delta_of_delta + 255) as u64, 9);
            }
            -2047..=2048 => {
                // 12ビット範囲: 4ビット(1110) + 12ビット値
                self.bit_writer.write_bits(0b1110, 4);
                self.bit_writer.write_bits((delta_of_delta + 2047) as u64, 12);
            }
            _ => {
                // フルサイズ: 4ビット(1111) + 64ビット値
                self.bit_writer.write_bits(0b1111, 4);
                self.bit_writer.write_bits(delta_of_delta as u64, 64);
            }
        }

        self.prev_timestamp = timestamp;
        self.prev_delta = delta;
    }
}

/// Gorilla圧縮エンコーダ（浮動小数点値用）
pub struct ValueEncoder {
    prev_value: u64,  // f64のビット表現
    prev_leading_zeros: u8,
    prev_trailing_zeros: u8,
    bit_writer: BitWriter,
}

impl ValueEncoder {
    pub fn encode(&mut self, value: f64) {
        let bits = value.to_bits();

        if self.is_first() {
            // 最初の値は64ビットそのまま
            self.bit_writer.write_bits(bits, 64);
            self.prev_value = bits;
            return;
        }

        let xor = bits ^ self.prev_value;

        if xor == 0 {
            // 同じ値: 1ビット (0)
            self.bit_writer.write_bit(false);
        } else {
            self.bit_writer.write_bit(true);

            let leading = xor.leading_zeros() as u8;
            let trailing = xor.trailing_zeros() as u8;

            if leading >= self.prev_leading_zeros
               && trailing >= self.prev_trailing_zeros {
                // 前回と同じウィンドウを使用: 1ビット(0) + 有効ビット
                self.bit_writer.write_bit(false);
                let meaningful_bits = 64 - self.prev_leading_zeros - self.prev_trailing_zeros;
                let value_bits = (xor >> self.prev_trailing_zeros) as u64;
                self.bit_writer.write_bits(value_bits, meaningful_bits as usize);
            } else {
                // 新しいウィンドウ: 1ビット(1) + leading(5) + length(6) + 有効ビット
                self.bit_writer.write_bit(true);
                self.bit_writer.write_bits(leading as u64, 5);
                let meaningful_bits = 64 - leading - trailing;
                self.bit_writer.write_bits((meaningful_bits - 1) as u64, 6);
                let value_bits = (xor >> trailing) as u64;
                self.bit_writer.write_bits(value_bits, meaningful_bits as usize);

                self.prev_leading_zeros = leading;
                self.prev_trailing_zeros = trailing;
            }
        }

        self.prev_value = bits;
    }
}
```

#### 3.1.4 Compaction戦略

**設計方針**: 時刻パーティション内で完結するCompactionを行い、
書き込み増幅を抑制しつつ単一ファイル指向を維持する。

**Compaction種別**:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    TSDB Compaction 種別                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. Minor Compaction (L0 → L1)                                      │
│     ├─ トリガー: L0 TSMファイル数 >= 4                              │
│     ├─ 動作: 全L0ファイルをマージして1つのL1ファイルに              │
│     ├─ 頻度: 数分〜数十分ごと                                       │
│     └─ 書き込み増幅: 低 (1-2x)                                      │
│                                                                     │
│  2. Major Compaction (L1+ レベル間)                                 │
│     ├─ トリガー: レベルサイズ閾値超過                               │
│     ├─ 動作: 1ファイル選択 → 下位レベルの重複範囲とマージ          │
│     ├─ 頻度: 数時間ごと                                             │
│     └─ 書き込み増幅: 中 (5-10x)                                     │
│                                                                     │
│  3. TTL Compaction (パーティション削除)                             │
│     ├─ トリガー: パーティションがTTL期限超過                        │
│     ├─ 動作: パーティションディレクトリごと削除                     │
│     ├─ 頻度: 時間単位（TTL設定依存）                                │
│     └─ 書き込み増幅: 0 (削除のみ)                                   │
│                                                                     │
│  4. Downsample Compaction (集約 + 移行)                             │
│     ├─ トリガー: ダウンサンプリングウィンドウ閉じ                   │
│     ├─ 動作: 元データを集約 → 下位解像度パーティションに書き込み   │
│     ├─ 頻度: ダウンサンプリング設定依存                             │
│     └─ 書き込み増幅: 集約により大幅削減                             │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**レベル構成** (時刻パーティション内):

```
Level 0 (L0): Fresh Flushes
├─ ファイルサイズ: 4-16MB
├─ 最大ファイル数: 4
├─ 重複キー範囲: 許容
└─ Compaction優先度: 最高

Level 1 (L1): Merged
├─ ファイルサイズ: 64-256MB
├─ 最大ファイル数: 10
├─ 重複キー範囲: なし
└─ Compaction優先度: 高

Level 2 (L2): Archived (オプション)
├─ ファイルサイズ: 256MB-1GB
├─ 最大ファイル数: 制限なし
├─ 圧縮: 最大圧縮率
└─ 読み取り専用パーティション向け
```

**Compaction実装**:

```rust
/// 時系列Compaction戦略
pub struct TSMCompactionStrategy {
    /// パーティション内レベル設定
    levels: Vec<LevelConfig>,

    /// 書き込み増幅計測
    write_amp_tracker: WriteAmpTracker,

    /// Compaction負債
    debt: AtomicU64,
}

struct LevelConfig {
    level: u8,
    max_file_count: usize,
    target_file_size: usize,
    max_total_size: usize,
}

impl TSMCompactionStrategy {
    pub fn default_tsdb() -> Self {
        Self {
            levels: vec![
                LevelConfig {
                    level: 0,
                    max_file_count: 4,
                    target_file_size: 8 * MB,
                    max_total_size: 64 * MB,
                },
                LevelConfig {
                    level: 1,
                    max_file_count: 10,
                    target_file_size: 128 * MB,
                    max_total_size: 1 * GB,
                },
                LevelConfig {
                    level: 2,
                    max_file_count: usize::MAX,
                    target_file_size: 512 * MB,
                    max_total_size: usize::MAX,
                },
            ],
            write_amp_tracker: WriteAmpTracker::new(),
            debt: AtomicU64::new(0),
        }
    }

    /// Compactionタスク選択
    pub fn pick_compaction(&self, partition: &TimePartition) -> Option<CompactionTask> {
        // L0優先: ファイル数が閾値を超えたら即座にCompaction
        let l0_files = self.list_level_files(partition, 0);
        if l0_files.len() >= self.levels[0].max_file_count {
            return Some(CompactionTask {
                task_type: CompactionType::Minor,
                input_level: 0,
                output_level: 1,
                input_files: l0_files,
                priority: CompactionPriority::High,
            });
        }

        // L1以降: サイズベースでCompaction
        for (i, config) in self.levels.iter().enumerate().skip(1) {
            let files = self.list_level_files(partition, config.level);
            let total_size: usize = files.iter().map(|f| f.size).sum();

            if total_size > config.max_total_size {
                // 最も古いファイルを選択（時系列特性: 古いデータは変更少）
                let oldest = files.into_iter()
                    .min_by_key(|f| f.min_timestamp)?;

                return Some(CompactionTask {
                    task_type: CompactionType::Major,
                    input_level: config.level,
                    output_level: config.level + 1,
                    input_files: vec![oldest],
                    priority: CompactionPriority::Normal,
                });
            }
        }

        None
    }

    /// 増分セクション置換 (書き込み増幅抑制)
    ///
    /// 全体リライトではなく、変更セクションのみを置換
    pub fn incremental_compaction(
        &self,
        base_file: &TSMFile,
        new_sections: Vec<Section>,
    ) -> Result<TSMFile> {
        let mut builder = TSMFileBuilder::from_existing(base_file)?;

        for section in new_sections {
            match section.section_type {
                SectionType::HotData | SectionType::ColdData => {
                    // データセクションのみ置換
                    builder.replace_section(section)?;
                }
                SectionType::Index => {
                    // インデックスは再構築
                    builder.rebuild_index()?;
                }
                _ => {}
            }
        }

        builder.build()
    }
}

/// 書き込み増幅トラッカー
pub struct WriteAmpTracker {
    /// 書き込みバイト数（ユーザーデータ）
    user_written: AtomicU64,

    /// 実際のディスク書き込みバイト数
    disk_written: AtomicU64,
}

impl WriteAmpTracker {
    /// 書き込み増幅率を計算
    pub fn write_amplification(&self) -> f64 {
        let user = self.user_written.load(Ordering::Relaxed) as f64;
        let disk = self.disk_written.load(Ordering::Relaxed) as f64;

        if user == 0.0 {
            return 1.0;
        }
        disk / user
    }
}
```

**Bulk Load / External Ingest** (TiKV参考):

```rust
/// 外部TSMファイルの直接取り込み
///
/// Raftスナップショット復元やバックアップリストア時に使用
pub trait ExternalIngest {
    /// 外部TSMファイルをパーティションに取り込み
    ///
    /// - ファイル検証（checksum, version互換性）
    /// - セクションをそのまま配置（Compaction不要）
    /// - インデックス再構築
    fn ingest_external(&self, path: &Path, partition: &TimePartition) -> Result<()>;

    /// Raftスナップショットからの復元
    fn restore_from_snapshot(&self, snapshot: &RaftSnapshot) -> Result<()>;
}

impl ExternalIngest for TSMStorage {
    fn ingest_external(&self, path: &Path, partition: &TimePartition) -> Result<()> {
        // 1. ファイル検証
        let file = TSMFile::open(path)?;
        file.validate_checksum()?;
        file.check_version_compatibility()?;

        // 2. パーティションディレクトリにコピー/ハードリンク
        let dest = partition.path().join(file.filename());
        std::fs::hard_link(path, &dest)
            .or_else(|_| std::fs::copy(path, &dest).map(|_| ()))?;

        // 3. メタデータ更新
        self.metadata.add_file(partition, &file)?;

        // 4. インデックスキャッシュ更新
        self.index_cache.invalidate(partition)?;

        Ok(())
    }

    fn restore_from_snapshot(&self, snapshot: &RaftSnapshot) -> Result<()> {
        // スナップショットに含まれる全Skulkファイルを取り込み
        for skulk_data in &snapshot.skulk_files {
            let temp_path = self.temp_dir.join(&skulk_data.filename);
            std::fs::write(&temp_path, &skulk_data.data)?;

            self.ingest_external(&temp_path, &skulk_data.partition)?;

            std::fs::remove_file(&temp_path)?;
        }

        Ok(())
    }
}
```

#### 3.1.6 Chirps Raft統合 (ShardStateMachine)

> **参照**: [chirps-raft-integration-proposal.md](chirps-raft-integration-proposal.md)

Skulkは `alopex-chirps` が提供するRaft Consensus APIを利用し、シャード単位でレプリケーションを行う。
Raftロジック自体はChirps側に実装され、Skulkは `StateMachine` traitを実装することで合意後の操作を処理する。

```rust
use alopex_chirps::raft::{StateMachine, RaftStorage, RaftNode, MultiRaftManager};

/// Skulk シャードのコマンド
#[derive(Clone, Serialize, Deserialize)]
pub enum ShardCommand {
    /// データポイント書き込み
    WritePoints { points: Vec<DataPoint> },
    /// シリーズ削除
    DeleteSeries { series_id: SeriesId },
    /// ダウンサンプリング実行
    Downsample { resolution: Duration },
    /// パーティションコンパクション
    CompactPartition { partition: TimePartition },
}

/// Skulk シャードのステートマシン
/// Chirps RaftNode から呼び出される
pub struct ShardStateMachine {
    shard_id: ShardId,
    skulk_storage: SkulkStorage,  // .skulk ファイル管理
}

#[async_trait]
impl StateMachine for ShardStateMachine {
    type Command = ShardCommand;
    type Response = ShardResponse;
    type Snapshot = ShardSnapshot;

    async fn apply(&mut self, index: LogIndex, command: Self::Command) -> Result<Self::Response> {
        match command {
            ShardCommand::WritePoints { points } => {
                // Raft commit済みなのでローカルに書き込み
                let written = self.skulk_storage.write_batch(&points).await?;
                Ok(ShardResponse::Written { count: written })
            }
            ShardCommand::DeleteSeries { series_id } => {
                self.skulk_storage.delete_series(series_id).await?;
                Ok(ShardResponse::Ok)
            }
            ShardCommand::Downsample { resolution } => {
                self.skulk_storage.downsample(resolution).await?;
                Ok(ShardResponse::Ok)
            }
            ShardCommand::CompactPartition { partition } => {
                self.skulk_storage.compact_partition(&partition).await?;
                Ok(ShardResponse::Ok)
            }
        }
    }

    async fn snapshot(&self) -> Result<Self::Snapshot> {
        // .skulk ファイル一覧 + メタデータをスナップショット化
        self.skulk_storage.create_snapshot().await
    }

    async fn restore(&mut self, snapshot: Self::Snapshot) -> Result<()> {
        // スナップショットから .skulk ファイルを復元
        self.skulk_storage.restore_from_snapshot(snapshot).await
    }
}
```

**Skulkクラスタノード構成**:

```rust
/// Skulk クラスタノード
pub struct SkulkClusterNode {
    /// Multi-Raft マネージャ（Chirps提供）
    multi_raft: MultiRaftManager<ShardStateMachine, WalRaftStorage>,

    /// シャードルーティング
    shard_router: ShardRouter,

    /// Chirps トランスポート
    transport: Arc<ChirpsTransport>,
}

impl SkulkClusterNode {
    /// メトリクス書き込み（クラスタモード）
    pub async fn write_metrics(&self, points: Vec<DataPoint>) -> Result<()> {
        // 1. メトリクスをシャードごとにグループ化
        let grouped = self.shard_router.group_by_shard(&points);

        // 2. 各シャードに並列で書き込み（Raft経由）
        let futures: Vec<_> = grouped.into_iter().map(|(shard_id, shard_points)| {
            self.write_to_shard(shard_id, shard_points)
        }).collect();

        futures::future::try_join_all(futures).await?;
        Ok(())
    }

    async fn write_to_shard(&self, shard_id: ShardId, points: Vec<DataPoint>) -> Result<()> {
        let raft_node = self.multi_raft.get_group(shard_id)
            .ok_or(Error::ShardNotFound)?;

        // リーダーでなければリダイレクト
        if !raft_node.is_leader() {
            return Err(Error::NotLeader(raft_node.leader_id()));
        }

        let command = ShardCommand::WritePoints { points };
        raft_node.propose(command).await?;
        Ok(())
    }
}
```

**Chirps Message Profile統合**:

Raft メッセージは Control Profile（高優先度）を使用し、通常のデータ通信より優先される。

```rust
// Chirps経由のRaftメッセージ送信
async fn send_raft_message(mesh: &Mesh, target: NodeId, msg: RaftMessage) {
    let payload = bincode::serialize(&msg)?;

    // Control Profile: 高優先度、低レイテンシ
    mesh.send(target, payload, MessageProfile::Control).await?;
}
```

#### 3.1.7 タイムスタンプ設計

> **参照**: [chirps-raft-integration-proposal.md](chirps-raft-integration-proposal.md) Section 3.4

TSDBとして、Skulkには「現在時刻」の決定に関する固有の要件がある。
Chirpsが提供する2つのタイムスタンプサービス（Raft TSO / Gossip HLC）との使い分けを明確にする。

**Chirpsタイムスタンプサービス**:

| レイヤー | 方式 | 用途 | 特徴 |
|---------|------|------|------|
| アプリ層 | Raft TSO | MVCC、トランザクション | 厳密な単調増加、Raftリーダー集中発行 |
| インフラ層 | Gossip HLC | ノード間イベント順序 | 分散発行、低レイテンシ、因果順序 |

**Skulk固有のタイムスタンプ要件**:

```
┌─────────────────────────────────────────────────────────────────┐
│  TSDB Timestamp Use Cases                                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. データポイントのタイムスタンプ                               │
│     ┌─────────────────────────────────────────────────────────┐ │
│     │ Line Protocol: cpu,host=A value=0.5 1732900000000000000  │ │
│     │                                     ^^^^^^^^^^^^^^^^     │ │
│     │                                     クライアント指定     │ │
│     │                                                          │ │
│     │ タイムスタンプ省略時 → Ingestノードのローカル時刻        │ │
│     └─────────────────────────────────────────────────────────┘ │
│                                                                  │
│  2. クエリの NOW() 関数                                          │
│     ┌─────────────────────────────────────────────────────────┐ │
│     │ SELECT * FROM cpu WHERE time > NOW() - INTERVAL '1h'     │ │
│     │                         ^^^^                             │ │
│     │                         コーディネーターが決定           │ │
│     └─────────────────────────────────────────────────────────┘ │
│                                                                  │
│  3. TTL / ダウンサンプリング判定                                 │
│     ┌─────────────────────────────────────────────────────────┐ │
│     │ 各ノードのローカル時刻で判定（厳密な同期不要）           │ │
│     └─────────────────────────────────────────────────────────┘ │
│                                                                  │
│  4. Out-of-Order (O3) データ                                     │
│     ┌─────────────────────────────────────────────────────────┐ │
│     │ 許容ウィンドウ内の過去データは受け入れ                   │ │
│     └─────────────────────────────────────────────────────────┘ │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**タイムスタンプソース決定**:

```rust
/// データポイントのタイムスタンプ決定
pub enum TimestampSource {
    /// クライアントが明示的に指定（最優先）
    ClientProvided(i64),

    /// タイムスタンプ省略時 → Ingestノードのローカル時刻
    /// NTP同期前提でクロックスキューは許容範囲内
    ServerAssigned,
}

/// タイムスタンプ割り当てロジック
impl IngestHandler {
    fn assign_timestamp(&self, point: &mut DataPoint) {
        if point.timestamp.is_none() {
            // ローカル時刻を使用（Raft TSO不要 = 低レイテンシ）
            point.timestamp = Some(
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap()
                    .as_nanos() as i64
            );
        }
    }
}
```

**クエリ時の NOW() 決定**:

```rust
/// クエリコンテキスト
pub struct QueryContext {
    /// クエリ開始時の現在時刻（コーディネーターが決定）
    /// 全シャードで統一された NOW() 値として使用
    pub query_timestamp: i64,

    /// クエリID
    pub query_id: Uuid,

    /// タイムアウト
    pub timeout: Duration,
}

impl QueryCoordinator {
    pub async fn execute(&self, sql: &str) -> Result<QueryResult> {
        // コーディネーターのローカル時刻を NOW() として確定
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos() as i64;

        let ctx = QueryContext {
            query_timestamp: now,
            query_id: Uuid::new_v4(),
            timeout: self.config.query_timeout,
        };

        // 各シャードにコンテキストを配布
        // シャードは ctx.query_timestamp を NOW() として評価
        self.scatter_gather(sql, ctx).await
    }
}
```

**Out-of-Order (O3) データ処理**:

```rust
/// O3設定
pub struct O3Config {
    /// O3許容ウィンドウ（この範囲内の遅延データは受け入れ）
    /// デフォルト: 1時間
    pub allowed_window: Duration,

    /// 古すぎるデータの扱い
    pub too_old_policy: TooOldPolicy,
}

pub enum TooOldPolicy {
    /// 拒否してエラー返却
    Reject,
    /// 警告ログのみで受け入れ
    AcceptWithWarning,
    /// 静かに破棄
    Drop,
}

impl Default for O3Config {
    fn default() -> Self {
        Self {
            allowed_window: Duration::from_secs(3600),  // 1時間
            too_old_policy: TooOldPolicy::AcceptWithWarning,
        }
    }
}
```

**Skulkにおけるタイムスタンプ使い分け**:

| ユースケース | 方式 | 理由 |
|-------------|------|------|
| データポイントTS（クライアント指定） | クライアント値をそのまま使用 | IoT/センサーの時刻を尊重 |
| データポイントTS（サーバー割当） | Ingestノードローカル時刻 | 高スループット優先、NTP同期前提 |
| クエリ `NOW()` | コーディネーターローカル時刻 | シャード間で統一、低レイテンシ |
| TTL削除判定 | 各ノードローカル時刻 | 厳密な同期不要、パーティション単位操作 |
| ダウンサンプリング判定 | 各ノードローカル時刻 | 同上 |
| Raft合意順序 | Raft TSO（Chirps提供） | ログエントリの厳密な順序が必要 |
| SWIMメンバーシップ | Gossip HLC（Chirps提供） | 因果順序で十分 |

**設計判断**: Alopex DBとは異なり、SkulkではデータポイントのタイムスタンプにRaft TSOを**使用しない**。
理由:
1. 時系列DBでは「厳密な順序」より「高スループット・低レイテンシ」が重要
2. Prometheus、InfluxDB等の既存TSDBも同様のアプローチ
3. クロックスキューは通常NTP同期で数十ms以内に収まる
4. O3許容ウィンドウで遅延データにも対応可能

---

### 3.2 Lifecycle Manager

#### 3.2.1 TTL Manager

```rust
pub struct TTLManager {
    /// 保持ポリシー
    policies: HashMap<String, RetentionPolicy>,

    /// 削除スケジューラ
    scheduler: TTLScheduler,
}

pub struct RetentionPolicy {
    /// テーブル/メトリクス名
    target: String,

    /// 保持期間
    retention: Duration,

    /// チェック間隔
    check_interval: Duration,
}

impl TTLManager {
    /// 期限切れパーティションの削除
    pub async fn cleanup_expired(&self) -> Result<CleanupStats> {
        let now = Timestamp::now();
        let mut stats = CleanupStats::default();

        for (target, policy) in &self.policies {
            let cutoff = now - policy.retention;

            // 時刻パーティション単位で削除（行単位削除なし）
            let expired_partitions = self.storage
                .list_partitions_before(target, cutoff)?;

            for partition in expired_partitions {
                // ディレクトリごと削除（高速）
                self.storage.drop_partition(&partition).await?;
                stats.partitions_deleted += 1;
                stats.bytes_reclaimed += partition.size_bytes;
            }
        }

        Ok(stats)
    }
}
```

#### 3.2.2 Downsampler

```rust
pub struct Downsampler {
    /// ダウンサンプリング設定
    configs: Vec<DownsampleConfig>,

    /// 連続クエリエンジン
    cq_engine: ContinuousQueryEngine,
}

pub struct DownsampleConfig {
    /// ソーステーブル
    source: String,

    /// 出力テーブル
    destination: String,

    /// 集約間隔
    interval: Duration,

    /// 集約関数
    aggregates: Vec<AggregateSpec>,

    /// 出力の保持期間
    retention: Duration,
}

pub struct AggregateSpec {
    /// 入力フィールド
    input_field: String,

    /// 集約関数
    function: AggregateFunction,

    /// 出力フィールド名
    output_field: String,
}

pub enum AggregateFunction {
    Avg,
    Sum,
    Min,
    Max,
    Count,
    First,
    Last,
    Percentile(f64),
}

impl Downsampler {
    pub async fn run_downsample(&self, config: &DownsampleConfig) -> Result<()> {
        // 処理済みウォーターマークを取得
        let watermark = self.get_watermark(&config.destination)?;

        // 未処理の時間範囲を特定
        let source_max = self.storage.get_max_timestamp(&config.source)?;
        let process_until = source_max - config.interval; // ウィンドウが閉じるまで待つ

        if watermark >= process_until {
            return Ok(()); // 処理済み
        }

        // 集約クエリを生成・実行
        let query = self.build_aggregate_query(config, watermark, process_until);
        let results = self.cq_engine.execute(&query).await?;

        // 結果を出力テーブルに書き込み
        self.storage.write_batch(&config.destination, results).await?;

        // ウォーターマーク更新
        self.update_watermark(&config.destination, process_until)?;

        Ok(())
    }

    fn build_aggregate_query(
        &self,
        config: &DownsampleConfig,
        start: Timestamp,
        end: Timestamp,
    ) -> String {
        let aggs = config.aggregates.iter()
            .map(|a| format!("{}({}) AS {}", a.function, a.input_field, a.output_field))
            .collect::<Vec<_>>()
            .join(", ");

        format!(
            "SELECT TIME_BUCKET('{}', time) AS time, {} \
             FROM {} \
             WHERE time >= {} AND time < {} \
             GROUP BY TIME_BUCKET('{}', time)",
            config.interval.as_secs(),
            aggs,
            config.source,
            start,
            end,
            config.interval.as_secs()
        )
    }
}
```

---

### 3.3 Query Engine

#### 3.3.1 PromQL Parser

```rust
/// PromQL AST
pub enum PromExpr {
    /// 即値: 42
    NumberLiteral(f64),

    /// 文字列: "hello"
    StringLiteral(String),

    /// ベクトルセレクタ: http_requests_total{method="GET"}[5m]
    VectorSelector {
        metric: String,
        labels: Vec<LabelMatcher>,
        range: Option<Duration>,
        offset: Option<Duration>,
    },

    /// 二項演算: a + b
    BinaryExpr {
        op: BinaryOp,
        lhs: Box<PromExpr>,
        rhs: Box<PromExpr>,
        matching: Option<VectorMatching>,
    },

    /// 集約: sum by (label) (expr)
    AggregateExpr {
        op: AggregateOp,
        expr: Box<PromExpr>,
        grouping: Grouping,
    },

    /// 関数呼び出し: rate(http_requests_total[5m])
    Call {
        func: PromFunction,
        args: Vec<PromExpr>,
    },
}

pub enum PromFunction {
    Rate,
    Irate,
    Increase,
    Sum,
    Avg,
    Max,
    Min,
    Count,
    Histogram_quantile,
    // ...
}

/// PromQL → SQL-TS 変換
pub fn promql_to_sql(expr: &PromExpr, time_range: TimeRange) -> String {
    match expr {
        PromExpr::VectorSelector { metric, labels, range, .. } => {
            let label_filters = labels.iter()
                .map(|l| format!("{} {} '{}'", l.name, l.op, l.value))
                .collect::<Vec<_>>()
                .join(" AND ");

            format!(
                "SELECT time, value FROM {} WHERE {} AND time BETWEEN {} AND {}",
                metric,
                label_filters,
                time_range.start,
                time_range.end
            )
        }

        PromExpr::Call { func: PromFunction::Rate, args } => {
            let inner = promql_to_sql(&args[0], time_range);
            format!(
                "SELECT time, RATE(value) OVER (ORDER BY time) FROM ({})",
                inner
            )
        }

        PromExpr::AggregateExpr { op: AggregateOp::Sum, expr, grouping } => {
            let inner = promql_to_sql(expr, time_range);
            let group_cols = match grouping {
                Grouping::By(labels) => labels.join(", "),
                Grouping::Without(labels) => "all_labels - ".to_string() + &labels.join(", "),
            };
            format!(
                "SELECT {}, SUM(value) FROM ({}) GROUP BY {}",
                group_cols, inner, group_cols
            )
        }

        // ... 他のケース
        _ => unimplemented!()
    }
}
```

#### 3.3.2 SQL-TS Functions

```rust
/// TIME_BUCKET関数実装
pub fn time_bucket(interval: Duration, timestamp: Timestamp) -> Timestamp {
    let interval_nanos = interval.as_nanos() as i64;
    let ts_nanos = timestamp.as_nanos();

    Timestamp::from_nanos((ts_nanos / interval_nanos) * interval_nanos)
}

/// RATE関数実装（カウンターの変化率/秒）
pub fn rate(points: &[(Timestamp, f64)]) -> Vec<(Timestamp, f64)> {
    if points.len() < 2 {
        return vec![];
    }

    points.windows(2)
        .map(|w| {
            let (t1, v1) = w[0];
            let (t2, v2) = w[1];

            let delta_v = if v2 >= v1 {
                v2 - v1  // 通常の増加
            } else {
                v2  // カウンターリセット検出
            };

            let delta_t = (t2 - t1).as_secs_f64();
            (t2, delta_v / delta_t)
        })
        .collect()
}

/// DELTA関数実装（差分）
pub fn delta(points: &[(Timestamp, f64)]) -> Vec<(Timestamp, f64)> {
    if points.len() < 2 {
        return vec![];
    }

    points.windows(2)
        .map(|w| {
            let (_, v1) = w[0];
            let (t2, v2) = w[1];
            (t2, v2 - v1)
        })
        .collect()
}

/// DERIVATIVE関数実装（微分 = 変化率/秒）
pub fn derivative(points: &[(Timestamp, f64)]) -> Vec<(Timestamp, f64)> {
    rate(points)  // カウンターリセット考慮なし版
}

/// FIRST関数実装（期間内最初の値）
pub fn first<T: Clone>(points: &[(Timestamp, T)]) -> Option<T> {
    points.first().map(|(_, v)| v.clone())
}

/// LAST関数実装（期間内最後の値）
pub fn last<T: Clone>(points: &[(Timestamp, T)]) -> Option<T> {
    points.last().map(|(_, v)| v.clone())
}
```

---

### 3.4 Alert Engine

```rust
pub struct AlertEngine {
    /// アラートルール
    rules: Vec<AlertRule>,

    /// アラート状態
    states: HashMap<AlertId, AlertState>,

    /// 通知先
    notifiers: Vec<Box<dyn Notifier>>,

    /// 評価間隔
    eval_interval: Duration,
}

pub struct AlertRule {
    id: AlertId,
    name: String,
    query: String,           // PromQL or SQL-TS
    condition: Condition,    // > 90, < 10, etc.
    for_duration: Duration,  // PENDING期間
    severity: Severity,
    annotations: HashMap<String, String>,
    notify: Vec<NotifyTarget>,
}

pub enum AlertState {
    Inactive,
    Pending { since: Timestamp },
    Firing { since: Timestamp, notified_at: Option<Timestamp> },
}

impl AlertEngine {
    pub async fn evaluate(&mut self) -> Result<()> {
        let now = Timestamp::now();

        for rule in &self.rules {
            // クエリ実行
            let result = self.query_engine.execute(&rule.query).await?;

            // 条件評価
            let is_triggered = rule.condition.evaluate(&result);

            // 状態遷移
            let state = self.states.entry(rule.id).or_insert(AlertState::Inactive);

            *state = match (&state, is_triggered) {
                (AlertState::Inactive, true) => {
                    AlertState::Pending { since: now }
                }
                (AlertState::Pending { since }, true) => {
                    if now - *since >= rule.for_duration {
                        // FIRING遷移＆通知
                        self.notify(rule, &result).await?;
                        AlertState::Firing { since: now, notified_at: Some(now) }
                    } else {
                        AlertState::Pending { since: *since }
                    }
                }
                (AlertState::Firing { since, .. }, true) => {
                    AlertState::Firing { since: *since, notified_at: None }
                }
                (AlertState::Firing { .. }, false) => {
                    // RESOLVED通知
                    self.notify_resolved(rule).await?;
                    AlertState::Inactive
                }
                (_, false) => AlertState::Inactive,
            };
        }

        Ok(())
    }

    async fn notify(&self, rule: &AlertRule, result: &QueryResult) -> Result<()> {
        let alert = Alert {
            rule_name: rule.name.clone(),
            severity: rule.severity,
            value: result.value(),
            annotations: rule.annotations.clone(),
            fired_at: Timestamp::now(),
        };

        for target in &rule.notify {
            match target {
                NotifyTarget::Webhook(url) => {
                    self.notifiers.iter()
                        .find_map(|n| n.as_webhook())
                        .ok_or(Error::NotifierNotFound)?
                        .send(&alert, url).await?;
                }
                NotifyTarget::Email(addr) => {
                    // ...
                }
                NotifyTarget::PagerDuty(key) => {
                    // ...
                }
            }
        }

        Ok(())
    }
}
```

---

## 4. 通信プロトコル設計

### 4.1 インジェストAPI

**Line Protocol エンドポイント**:
```
POST /write
Content-Type: text/plain

cpu,host=server1,region=ap usage_user=23.5,usage_system=12.3 1609459200000000000
cpu,host=server2,region=ap usage_user=45.2,usage_system=8.1 1609459200000000000
```

**Prometheus Remote Write エンドポイント**:
```
POST /api/v1/write
Content-Type: application/x-protobuf
Content-Encoding: snappy

<snappy-compressed protobuf>
```

**JSON エンドポイント**:
```
POST /api/v1/ingest
Content-Type: application/json

{
  "metrics": [
    {
      "name": "cpu",
      "tags": {"host": "server1", "region": "ap"},
      "fields": {"usage_user": 23.5, "usage_system": 12.3},
      "timestamp": 1609459200000000000
    }
  ]
}
```

### 4.2 クエリAPI

**PromQL エンドポイント**:
```
GET /api/v1/query?query=rate(http_requests_total[5m])&time=2025-11-29T12:00:00Z

Response:
{
  "status": "success",
  "data": {
    "resultType": "vector",
    "result": [
      {
        "metric": {"__name__": "http_requests_total", "method": "GET"},
        "value": [1732881600, "1234.5"]
      }
    ]
  }
}
```

**SQL-TS エンドポイント**:
```
POST /api/v1/sql
Content-Type: application/json

{
  "query": "SELECT TIME_BUCKET('1h', time), AVG(usage) FROM cpu WHERE time > NOW() - INTERVAL '24h' GROUP BY 1"
}

Response:
{
  "success": true,
  "columns": ["time_bucket", "avg_usage"],
  "rows": [
    ["2025-11-29T00:00:00Z", 45.2],
    ["2025-11-29T01:00:00Z", 52.1]
  ],
  "execution_time_ms": 12
}
```

### 4.3 内部通信（Chirps経由）

> **参照**: [chirps-raft-integration-proposal.md](chirps-raft-integration-proposal.md) Section 3

Chirpsが提供するMessage Profileを活用し、メッセージの重要度に応じた通信制御を行う。
Raftメッセージは `chirps-raft` モジュールが自動的に Control Profile で送信するため、
アプリケーション側ではRaftメッセージを直接扱う必要はない。

```rust
/// Skulk内部メッセージ（Raft以外）
pub enum SkulkMessage {
    /// シャード間クエリ（Ephemeral: 損失許容）
    ShardQuery {
        query_id: Uuid,
        query: String,
        time_range: TimeRange,
    },

    /// シャード間クエリ応答
    ShardQueryResponse {
        query_id: Uuid,
        results: Vec<DataPoint>,
    },

    /// ダウンサンプリング調整（Ephemeral）
    DownsampleCoordinate {
        partition: TimePartition,
        watermark: Timestamp,
    },

    /// Changefeed通知（Durable: 到達保証）
    ChangefeedEvent {
        series_id: SeriesId,
        points: Vec<DataPoint>,
    },
}

// Chirps経由の送信（Message Profile使い分け）
async fn send_shard_query(mesh: &Mesh, target: NodeId, query: ShardQuery) {
    let payload = bincode::serialize(&SkulkMessage::ShardQuery(query))?;
    // Ephemeral: 低優先度、損失許容
    mesh.send_to(target, &payload, MessageProfile::Ephemeral).await?;
}

async fn send_changefeed(mesh: &Mesh, target: NodeId, event: ChangefeedEvent) {
    let payload = bincode::serialize(&SkulkMessage::ChangefeedEvent(event))?;
    // Durable: 到達保証、再送あり
    mesh.send_to(target, &payload, MessageProfile::Durable).await?;
}

// Note: Raft メッセージは MultiRaftManager が自動的に
// Control Profile（高優先度）で送信するため、
// アプリケーション側での明示的な送信は不要
```

**Message Profile一覧**:

| Profile | 用途 | 優先度 | 到達保証 |
|---------|------|-------|---------|
| Control | Raft AppendEntries, Vote | 最高 | あり |
| Ephemeral | シャードクエリ, Gossip | 通常 | なし |
| Durable | Changefeed, Snapshot転送 | 低 | あり |

---

## 5. 運用設計

### 5.1 監視項目

| カテゴリ | メトリクス | 閾値 |
|---------|-----------|------|
| Ingest | points_per_second | - (capacity metric) |
| | write_latency_p99 | <10ms |
| | wal_sync_duration | <100ms |
| Query | query_latency_p99 | <100ms |
| | active_queries | <1000 |
| Storage | tsm_file_count | <1000 per partition |
| | compression_ratio | >10:1 |
| | disk_usage_percent | <80% |
| Lifecycle | ttl_deletes_per_minute | - |
| | downsample_lag_seconds | <300 |
| Cluster | shard_leader_elections | <1/hour |
| | replication_lag_seconds | <10 |

### 5.2 Self-Monitoring

```sql
-- TSDB自身のメトリクスを自分自身に保存
CREATE TIMESERIES TABLE _internal.tsdb_metrics (
  time TIMESTAMP NOT NULL,
  host TAG,
  metric TAG,
  value FIELD FLOAT
) WITH (
  retention = '7d'
);

-- 自動収集される内部メトリクス
-- alopex_tsdb_ingest_points_total
-- alopex_tsdb_query_duration_seconds
-- alopex_tsdb_tsm_compaction_duration_seconds
-- alopex_tsdb_wal_size_bytes
-- alopex_tsdb_memtable_size_bytes
```

---

## 6. 変更履歴

| バージョン | 日付 | 変更者 | 変更内容 |
|----------|------|--------|---------|
| 1.0 | 2025-11-29 | Claude | 初版作成 |
| 1.1 | 2025-11-29 | Claude | 製品名を「Alopex Skulk」に変更 |
