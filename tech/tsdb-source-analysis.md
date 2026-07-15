# CnosDB / QuestDB ソースコード分析レポート

対象: `reference/` にクローンされた CnosDB および QuestDB のソースコード。Alopex Skulk（時系列DB）設計の参考資料として、両DBのストレージエンジン、ファイルフォーマット、クラスタリング実装を分析する。

---

## 概要比較

| 項目 | CnosDB | QuestDB |
|------|--------|---------|
| 言語 | Rust | Java (Zero-GC) + C++ + Rust (Enterprise) |
| ライセンス | AGPL 3.0 | Apache 2.0 |
| ストレージモデル | TSM (Time-Structured Merge Tree) | Cairo (Column-oriented native storage) |
| 圧縮 | Gorilla (timestamp), Simple8b (integers), Snappy/Zstd | 非圧縮 (mmap直接アクセス優先) + Parquet連携 |
| WAL | Raft統合WAL | Segment WAL |
| クラスタリング | Raft (openraft) ベース | Enterprise版のみ (Read Replica, Multi-Primary) |
| 時間パーティション | Vnode単位 | Hour/Day/Month/Week/Year |

---

## CnosDB (`reference/cnosdb`)

### アーキテクチャ概要

CnosDBは InfluxDB の TSM 形式をベースにした Rust 製の分散時系列データベース。主要コンポーネント:

```
┌─────────────────────────────────────────────────────────────┐
│                      query_server                           │
│                   (SQL/InfluxQL Engine)                     │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                       coordinator                            │
│               (Query Distribution & Scheduling)              │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│     tskv      │    │     tskv      │    │     tskv      │
│ (Storage Node)│    │ (Storage Node)│    │ (Storage Node)│
└───────────────┘    └───────────────┘    └───────────────┘
        │                     │                     │
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  replication  │    │  replication  │    │  replication  │
│   (Raft)      │    │   (Raft)      │    │   (Raft)      │
└───────────────┘    └───────────────┘    └───────────────┘
```

### TSKVストレージエンジン (`tskv/`)

#### TSMファイル形式

**ファイル構造** (`tskv/src/tsm/`):

```
┌──────────────────────────────────────────────────────┐
│                   TSM File                           │
├──────────────────────────────────────────────────────┤
│ Magic Number (4 bytes): 0x12CDA16                    │
├──────────────────────────────────────────────────────┤
│ Page Data Blocks                                     │
│   ├─ Page 1: [column_data, statistics, meta]         │
│   ├─ Page 2: ...                                     │
│   └─ Page N: ...                                     │
├──────────────────────────────────────────────────────┤
│ Chunk Metadata (per series)                          │
│   ├─ SeriesId                                        │
│   ├─ ColumnGroup offsets                             │
│   └─ TimeRange                                       │
├──────────────────────────────────────────────────────┤
│ ChunkGroup Metadata (per table)                      │
│   ├─ TableSchema                                     │
│   ├─ ChunkGroup offset/size                          │
│   └─ TimeRange                                       │
├──────────────────────────────────────────────────────┤
│ Footer (131140 bytes fixed)                          │
│   ├─ Version: V1 | V2                                │
│   ├─ TimeRange (min_ts, max_ts)                      │
│   ├─ TableMeta (chunk_group_offset, chunk_group_size)│
│   ├─ SeriesMeta                                      │
│   │   ├─ BloomFilter (1MB = 1024*1024 bits)          │
│   │   ├─ chunk_offset                                │
│   │   └─ chunk_size                                  │
│   └─ Serialized via bincode                          │
└──────────────────────────────────────────────────────┘
```

**バージョン管理**:
- `TsmVersion::V1`: 非圧縮メタデータ
- `TsmVersion::V2`: 圧縮メタデータ（Encoding指定時）

#### コーデック実装 (`tskv/src/tsm/codec/`)

| データ型 | コーデック | 特徴 |
|----------|-----------|------|
| Timestamp | `timestamp.rs` | Delta-of-delta + Gorilla圧縮 |
| Integer | `integer.rs` | ZigZag + Simple8b |
| Unsigned | `unsigned.rs` | Simple8b |
| Float | `float.rs` | Gorilla XOR圧縮 |
| Boolean | `boolean.rs` | Bit-packing |
| String | `string.rs` | Snappy/Zstd/LZ4 |

**Simple8b** (`simple8b.rs`): 最大64bit×240個を単一64bitワードにパック。整数の差分エンコーディングと組み合わせて使用。

#### WAL実装 (`tskv/src/wal/`)

**WALレコード形式**:

```
Write Record:
┌────────┬──────────┬──────────┬───────────┬─────────────┬────────┬───────┐
│ type   │ sequence │ vnode_id │ precision │ tenant_size │ tenant │ data  │
│ 1 byte │ 8 bytes  │ 4 bytes  │ 1 byte    │ 8 bytes     │ n bytes│n bytes│
└────────┴──────────┴──────────┴───────────┴─────────────┴────────┴───────┘

Footer:
┌──────────┬───────────────┬──────────────┬──────────────┐
│ "walo"   │ padding_zeros │ min_sequence │ max_sequence │
│ 4 bytes  │ 12 bytes      │ 8 bytes      │ 8 bytes      │
└──────────┴───────────────┴──────────────┴──────────────┘
```

**WAL Type**:
- `RaftBlankLog (101)`: 空のRaftログ
- `RaftNormalLog (102)`: 通常のRaftログ
- `RaftMembershipLog (103)`: メンバーシップ変更ログ

#### Compaction (`tskv/src/compaction/`)

**タスクタイプ**:
- `Normal`: Level間のコンパクション
- `Delta`: Level-0ファイルの統合
- `Manual`: 手動トリガー

**Picker戦略**: Level毎のファイル数・サイズに基づいて選択

### Replication (`replication/`)

**Raft実装** (openraftベース):
- `raft_node.rs`: Raftノード管理
- `multi_raft.rs`: 複数Raftグループの管理
- `entry_store.rs`: Raftエントリの永続化
- `apply_store.rs`: ステートマシンへの適用
- `network_grpc.rs` / `network_http.rs`: ノード間通信

**クラスタリングモデル**:
- Vnode単位でRaftグループを形成
- 各VnodeはTSMファイル + WALを持つ
- メタデータ管理は別途 `meta/` コンポーネント

---

## QuestDB (`reference/questdb`)

### アーキテクチャ概要

QuestDBはZero-GC Javaで実装された高性能時系列データベース。金融市場データ向けに最適化。

```
┌─────────────────────────────────────────────────────────────┐
│                    Query Engine (Griffin)                    │
│              SIMD-accelerated, JIT compilation               │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    Cairo Storage Engine                      │
│           Memory-mapped, column-oriented storage             │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   Native      │    │     WAL       │    │   Parquet     │
│  Columnar     │    │   Segments    │    │  (Cold Tier)  │
└───────────────┘    └───────────────┘    └───────────────┘
```

### Cairo Storage Engine (`cairo/`)

#### ファイル構造

**テーブルディレクトリ構成**:

```
<table_name>/
├── _meta                    # テーブルメタデータ
├── _txn                     # トランザクションファイル
├── _txn_scoreboard          # 並行読み取り管理
├── _cv                      # カラムバージョン
├── _name                    # テーブル名
├── <partition>/             # 時間パーティション (例: 2024-01-15)
│   ├── <column>.d           # データファイル
│   ├── <column>.i           # インデックスファイル（可変長列用）
│   ├── <symbol>.o           # シンボルオフセット
│   ├── <symbol>.k           # シンボルキー
│   ├── <symbol>.v           # シンボル値
│   └── data.parquet         # Parquet形式 (コールドストレージ)
└── wal/                     # WALセグメント
    ├── 0/
    │   ├── _event
    │   └── <segment_files>
    └── seq/                 # シーケンサ
```

#### メタファイル形式 (`_meta`)

```
Offset    Size     Field
─────────────────────────────────
0         4        column_count
4         4        partition_by
8         4        timestamp_index
12        4        version
16        4        table_id
20        4        max_uncommitted_rows
24        8        o3_max_lag
32        8        metadata_version
40        1        wal_enabled
41        4        meta_format_minor_version
45        4        ttl_hours_or_months
...
128+      32*N     column_definitions
```

#### トランザクションファイル (`_txn`)

```
TX Header (64 bytes base):
┌─────────────────────────────────────────────────────┐
│ version_64 | offset_a | symbols_size_a | parts_size_a │
│ offset_b   | symbols_size_b | parts_size_b           │
└─────────────────────────────────────────────────────┘

TX Record:
┌────────────────────────────────────────────────────────────┐
│ txn | transient_row_count | fixed_row_count | min_ts       │
│ max_ts | struct_version | data_version | partition_version │
│ column_version | truncate_version | seq_txn | checksum     │
│ lag_txn_count | lag_row_count | lag_min_ts | lag_max_ts    │
└────────────────────────────────────────────────────────────┘
```

#### カラム型システム (`ColumnType.java`)

| Type ID | 型名 | サイズ | 備考 |
|---------|------|--------|------|
| 1 | BOOLEAN | 1 byte | |
| 2 | BYTE | 1 byte | |
| 3 | SHORT | 2 bytes | |
| 5 | INT | 4 bytes | |
| 6 | LONG | 8 bytes | |
| 8 | TIMESTAMP | 8 bytes | マイクロ秒 or ナノ秒 |
| 9 | FLOAT | 4 bytes | |
| 10 | DOUBLE | 8 bytes | |
| 11 | STRING | 可変長 | .d + .i ファイル |
| 12 | SYMBOL | 4 bytes | 辞書エンコード |
| 13 | LONG256 | 32 bytes | |
| 14-17 | GEO* | 1-8 bytes | GeoHash |
| 18 | BINARY | 可変長 | |
| 19 | UUID | 16 bytes | |
| 26 | VARCHAR | 可変長 | 新形式 |
| 27 | ARRAY | 可変長 | N次元配列 |
| 28-33 | DECIMAL* | 8-64 bytes | 固定小数点 |

#### パーティショニング (`PartitionBy.java`)

| 値 | パーティション | ディレクトリ形式 |
|----|---------------|-----------------|
| 0 | DAY | `2024-01-15` |
| 1 | MONTH | `2024-01` |
| 2 | YEAR | `2024` |
| 3 | NONE | `default` |
| 4 | HOUR | `2024-01-15T14` |
| 5 | WEEK | `2024-W03` |

#### Out-of-Order (O3) 処理

QuestDBの特徴的な機能。遅延到着データの効率的な処理:

1. **O3 Buffer**: メモリ内で順序外データを一時保持
2. **O3 Commit**: バッファがしきい値に達したらマージ
3. **O3 Copy Job**: パーティション内でのデータ再配置
4. **O3 Partition Job**: パーティション間のデータ移動

```java
// O3Utils.java - 順序外データのコピー処理
public static void copyFixedSizeCol(
    FilesFacade ff,
    long srcAddr, long srcLo,
    long dstAddr, long dstFixFileOffset,
    long dstFd, boolean mixedIOFlag,
    long len, int shl
)
```

#### WAL実装 (`cairo/wal/`)

**WALモード** (`SqlWalMode`):
- WAL有効: 書き込みはまずWALセグメントに記録
- WAL無効: 直接テーブルに書き込み（高スループット）

**WALコンポーネント**:
- `WalWriter`: WALセグメントへの書き込み
- `WalReader`: WALセグメントの読み取り
- `ApplyWal2TableJob`: WALからテーブルへの適用
- `WalPurgeJob`: 古いWALセグメントの削除
- `CheckWalTransactionsJob`: WALの整合性確認

#### Multi-Tier Storage

QuestDBの3層ストレージ戦略:

1. **WAL Layer**: 書き込みバッファ（高速インジェスト）
2. **Native Columnar**: アクティブデータ（低レイテンシクエリ）
3. **Parquet**: コールドストレージ（コスト効率・互換性）

---

## Alopex Skulk への示唆

### CnosDBからの学び

**採用候補**:
1. **TSM形式の基本構造**: Page → Chunk → ChunkGroup → Footer の階層構造
2. **BloomFilter統合**: Footer内にSeriesId用BloomFilterを埋め込む設計
3. **Raft統合WAL**: WALエントリとRaftログを統合する設計
4. **Codec多様性**: データ型毎に最適なコーデックを選択

**注意点**:
- Footer固定サイズ (131KB) は大規模テーブルでオーバーヘッドになる可能性
- bincode シリアライゼーションはスキーマ進化に弱い

### QuestDBからの学び

**採用候補**:
1. **O3処理**: 遅延到着データの効率的なマージ戦略
2. **Symbol型**: 文字列の辞書エンコーディングで空間効率化
3. **柔軟なパーティショニング**: HOUR/DAY/WEEK/MONTH/YEAR対応
4. **WAL + 直接書き込みの選択**: ワークロードに応じた書き込みモード

**注意点**:
- 圧縮なしの列指向ストレージは、Alopexの単一ファイル志向と相性が悪い可能性
- Multi-tier storageはAlopexの統一ファイル形式と整合させる設計が必要

### Alopex Skulk設計への反映案

```
┌─────────────────────────────────────────────────────────────┐
│                    .alopex TSM Section                       │
├─────────────────────────────────────────────────────────────┤
│ Header (64B): magic, version, section_type=TSM              │
├─────────────────────────────────────────────────────────────┤
│ Page Blocks (CnosDB inspired):                              │
│   ├─ Timestamp: Delta-of-delta + Gorilla                    │
│   ├─ Float: Gorilla XOR                                     │
│   ├─ Integer: ZigZag + Simple8b                             │
│   └─ String: Symbol dict + Snappy                           │
├─────────────────────────────────────────────────────────────┤
│ Chunk Index (per series):                                   │
│   ├─ series_id (u64)                                        │
│   ├─ time_range (i64, i64)                                  │
│   └─ column_offsets[]                                       │
├─────────────────────────────────────────────────────────────┤
│ ChunkGroup Index (per table):                               │
│   ├─ table_id (u32)                                         │
│   ├─ schema_version (u32)                                   │
│   └─ chunk_offsets[]                                        │
├─────────────────────────────────────────────────────────────┤
│ TSM Footer:                                                 │
│   ├─ bloom_filter (series_id, 128KB)                        │
│   ├─ partition_by (HOUR|DAY|MONTH|YEAR)                     │
│   ├─ min_ts, max_ts                                         │
│   ├─ series_count                                           │
│   ├─ index_offset, index_size                               │
│   └─ checksum (CRC32)                                       │
└─────────────────────────────────────────────────────────────┘
```

### ファイル形式比較まとめ

| 項目 | CnosDB TSM | QuestDB Cairo | Alopex Skulk (提案) |
|------|------------|---------------|---------------------|
| ファイル形式 | 単一 `.tsm` | 多数 `.d/.i` | 単一 `.skulk` |
| メタデータ | Footer内 (bincode) | 別ファイル `_meta` | Footer内 (FlatBuffers) |
| 圧縮 | Gorilla/Simple8b/Snappy | なし (Parquetのみ) | Gorilla/Simple8b/Snappy |
| BloomFilter | Footer内 (1MB固定) | なし | Footer内 (可変長) |
| パーティション | Vnode | Directory | Range単位 `.skulk` |
| WAL | Raft統合 | Segment WAL | Raft統合 (Chirps) |
| O3対応 | 限定的 | 高度なO3処理 | 要設計 |
| WASM配布 | 非対応 | 非対応 | 対応 (read-only) |

---

## 結論

CnosDBとQuestDBは異なるアプローチで時系列データを処理している:

- **CnosDB**: InfluxDB TSM形式を継承しつつRust化。圧縮効率と分散処理に重点。
- **QuestDB**: Zero-GC Java + SIMD最適化。金融データ向けの低レイテンシクエリに特化。

Alopex Skulkは両者の良い点を取り入れつつ、Alopex Core の単一ファイル哲学を維持する設計が求められる:

1. **CnosDBから**: TSM形式の圧縮コーデック、Raft統合WAL
2. **QuestDBから**: O3処理戦略、柔軟なパーティショニング、Symbol型
3. **Alopex独自**: 単一 `.alopex` 内TSMセクション、WASM配布対応、Chirps統合
