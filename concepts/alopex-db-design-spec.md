# Alopex DB 方式設計書

**バージョン**: 1.0
**最終更新日**: 2025-11-21
**ステータス**: Draft

---

## 1. システムアーキテクチャ

### 1.1 全体アーキテクチャ

```
┌────────────────────────────────────────────────────────────────┐
│                         Client Layer                           │
│  (SQL Clients, HTTP/gRPC Clients, JavaScript/WASM Apps)       │
└────────────────────┬───────────────────────────────────────────┘
                     │
┌────────────────────┴───────────────────────────────────────────┐
│                    API Gateway Layer                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │ SQL Endpoint │  │ HTTP/gRPC    │  │ WASM Binding │        │
│  │              │  │ REST API     │  │ (JS/TS)      │        │
│  └──────────────┘  └──────────────┘  └──────────────┘        │
└────────────────────┬───────────────────────────────────────────┘
                     │
┌────────────────────┴───────────────────────────────────────────┐
│                   Query Processing Layer                       │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  SQL Parser → Planner → Optimizer → Executor             │ │
│  └──────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Vector Search Engine (Flat / HNSW)                      │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────┬───────────────────────────────────────────┘
                     │
┌────────────────────┴───────────────────────────────────────────┐
│                  Transaction Management Layer                  │
│  ┌──────────────────┐  ┌───────────────┐  ┌─────────────────┐│
│  │ Transaction      │  │ MVCC Manager  │  │ Lock Manager    ││
│  │ Coordinator      │  │               │  │                 ││
│  └──────────────────┘  └───────────────┘  └─────────────────┘│
└────────────────────┬───────────────────────────────────────────┘
                     │
┌────────────────────┴───────────────────────────────────────────┐
│                      Storage Layer                             │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ LSM-Tree Engine                                          │ │
│  │  ┌──────────┐  ┌────────────┐  ┌───────────────────┐   │ │
│  │  │ MemTable │  │ Immutable  │  │ SSTable + Indexes │   │ │
│  │  │          │  │ MemTables  │  │                   │   │ │
│  │  └──────────┘  └────────────┘  └───────────────────┘   │ │
│  └──────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Write-Ahead Log (WAL)                                    │ │
│  └──────────────────────────────────────────────────────────┘ │
└────────────────────┬───────────────────────────────────────────┘
                     │
┌────────────────────┴───────────────────────────────────────────┐
│            Distribution Layer (Cluster Mode Only)              │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │ Range        │  │ Raft         │  │ Cluster Membership  │ │
│  │ Manager      │  │ Replication  │  │ (alopex-chirps)     │ │
│  └──────────────┘  └──────────────┘  └─────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

### 1.2 モード別アーキテクチャ

**重要: 統一データファイル形式**

全モードは共通の `.alopex` ファイル形式を使用し、モード間でのデータ互換性を保証する。

| モード | 読み取り | 書き込み | データ形式 |
|--------|---------|---------|-----------|
| Embedded | ✅ | ✅ | `.alopex` |
| Single-Node | ✅ | ✅ | `.alopex` |
| Distributed | ✅ | ✅ | `.alopex` (Range単位) |
| WASM | ✅ | ❌ | `.alopex` (読み取り専用) |

詳細は `technical-spec.md` セクション 1.3「Unified Data File Format」を参照。

#### 1.2.1 Embedded Mode

```
┌─────────────────────────────────┐
│     Application Process         │
│                                 │
│  ┌───────────────────────────┐ │
│  │   Alopex Embedded API     │ │
│  └───────────┬───────────────┘ │
│              │                 │
│  ┌───────────┴───────────────┐ │
│  │   Query Processing        │ │
│  │   Transaction Manager     │ │
│  │   Storage Engine          │ │
│  └───────────┬───────────────┘ │
│              │                 │
│  ┌───────────┴───────────────┐ │
│  │   Local Disk              │ │
│  │   (single DB file)        │ │
│  └───────────────────────────┘ │
└─────────────────────────────────┘
```

#### 1.2.2 Single-Node Server

```
┌─────────────────────────────────┐
│   HTTP/gRPC Server Process      │
│                                 │
│  ┌───────────────────────────┐ │
│  │   API Server              │ │
│  │   (HTTP/gRPC Endpoints)   │ │
│  └───────────┬───────────────┘ │
│              │                 │
│  ┌───────────┴───────────────┐ │
│  │   Query Processing        │ │
│  │   Transaction Manager     │ │
│  │   Storage Engine          │ │
│  └───────────┬───────────────┘ │
│              │                 │
│  ┌───────────┴───────────────┐ │
│  │   Persistent Storage      │ │
│  └───────────────────────────┘ │
└─────────────────────────────────┘
```

#### 1.2.3 Distributed Cluster

```
┌─────────────────────────────────────────────────────────────┐
│                    Cluster (3+ Nodes)                       │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Node 1     │  │   Node 2     │  │   Node 3     │     │
│  │              │  │              │  │              │     │
│  │  ┌────────┐  │  │  ┌────────┐  │  │  ┌────────┐  │     │
│  │  │ Range  │  │  │  │ Range  │  │  │  │ Range  │  │     │
│  │  │ A (L)  │  │  │  │ A (F)  │  │  │  │ A (F)  │  │     │
│  │  └────────┘  │  │  └────────┘  │  │  └────────┘  │     │
│  │  ┌────────┐  │  │  ┌────────┐  │  │  ┌────────┐  │     │
│  │  │ Range  │  │  │  │ Range  │  │  │  │ Range  │  │     │
│  │  │ B (F)  │  │  │  │ B (L)  │  │  │  │ B (F)  │  │     │
│  │  └────────┘  │  │  └────────┘  │  │  └────────┘  │     │
│  │              │  │              │  │              │     │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘     │
│         │                 │                 │              │
│         └─────────────────┼─────────────────┘              │
│                           │                                │
│              ┌────────────┴────────────┐                   │
│              │   alopex-chirps         │                   │
│              │   (Gossip + Messaging)  │                   │
│              └─────────────────────────┘                   │
└─────────────────────────────────────────────────────────────┘

L: Leader, F: Follower
```

#### 1.2.4 WASM Mode

```
┌─────────────────────────────────────────┐
│         Browser Environment             │
│                                         │
│  ┌───────────────────────────────────┐ │
│  │   JavaScript Application          │ │
│  └──────────────┬────────────────────┘ │
│                 │                      │
│  ┌──────────────┴────────────────────┐ │
│  │   Alopex WASM Module              │ │
│  │   (wasm-bindgen bindings)         │ │
│  └──────────────┬────────────────────┘ │
│                 │                      │
│  ┌──────────────┴────────────────────┐ │
│  │   Query Processing                │ │
│  │   Storage Engine                  │ │
│  └──────────────┬────────────────────┘ │
│                 │                      │
│  ┌──────────────┴────────────────────┐ │
│  │   IndexedDB / OPFS                │ │
│  │   (Browser Storage APIs)          │ │
│  └───────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

---

## 2. データフロー設計

### 2.1 書き込みフロー（Embedded/Single-Node）

```
Client Request
     │
     ▼
┌─────────────────┐
│  1. Parse SQL   │
│     & Validate  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  2. Begin Txn   │
│     (get ts)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  3. Execute     │
│     Plan        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  4. Write WAL   │
│     (durability)│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  5. Update      │
│     MemTable    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  6. Commit Txn  │
│     (validate)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  7. Return OK   │
└─────────────────┘

Background Tasks:
- MemTable → SSTable Flush (when size > threshold)
- SSTable Compaction (periodic)
```

### 2.2 書き込みフロー（Distributed）

```
Client Request
     │
     ▼
┌──────────────────┐
│  1. Parse & Plan │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  2. Route to     │
│     Range Leader │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  3. Raft Propose │
│     (Leader)     │
└────────┬─────────┘
         │
         ├────────────────────┐
         │                    │
         ▼                    ▼
┌──────────────┐    ┌──────────────┐
│  Replicate   │    │  Replicate   │
│  to Follower │    │  to Follower │
│  Node 2      │    │  Node 3      │
└──────┬───────┘    └──────┬───────┘
       │                   │
       └─────────┬─────────┘
                 │
                 ▼
┌──────────────────┐
│  4. Quorum       │
│     Achieved     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  5. Apply to     │
│     Storage      │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  6. Return OK    │
└──────────────────┘
```

### 2.3 読み取りフロー

```
Client Request
     │
     ▼
┌─────────────────┐
│  1. Parse SQL   │
│     & Plan      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  2. Start Txn   │
│     (snapshot)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  3. Execute     │
│     Operators   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  4. Scan        │
│     Storage     │
│  ┌──────────┐  │
│  │ MemTable │──┼──┐
│  └──────────┘  │  │
│  ┌──────────┐  │  │
│  │ SSTable  │──┼──┤ Merge
│  └──────────┘  │  │
│  ┌──────────┐  │  │
│  │ SSTable  │──┼──┘
│  └──────────┘  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  5. Filter &    │
│     Project     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  6. Return      │
│     Results     │
└─────────────────┘
```

### 2.4 ベクトル検索フロー

```
Client Request (Vector Search)
     │
     ▼
┌─────────────────┐
│  1. Parse Query │
│     + Vector    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  2. Load Vector │
│     Index       │
└────────┬────────┘
         │
         ▼ (Phase 1: Flat)
┌─────────────────┐
│  3. Brute-Force │
│     Similarity  │
│     Calculation │
└────────┬────────┘
         │
         ▼ (Phase 2: HNSW)
┌─────────────────┐
│  3. HNSW        │
│     Greedy      │
│     Search      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  4. Top-K       │
│     Selection   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  5. Apply SQL   │
│     Filters     │
│     (if any)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  6. Return      │
│     Results     │
└─────────────────┘
```

---

## 3. 主要コンポーネント設計

### 3.1 LSM-Tree Storage Engine

#### 3.1.1 構造設計

```
Memory:
┌────────────────────────────────────┐
│         MemTable (Mutable)         │
│  ┌──────────────────────────────┐  │
│  │  BTreeMap<Key, Value>        │  │
│  │  Size: ~64MB                 │  │
│  └──────────────────────────────┘  │
└────────────────────────────────────┘
┌────────────────────────────────────┐
│    Immutable MemTables (Queue)     │
│  ┌──────────────────────────────┐  │
│  │  MemTable 1 (flushing...)    │  │
│  │  MemTable 2 (waiting...)     │  │
│  └──────────────────────────────┘  │
└────────────────────────────────────┘

Disk:
┌────────────────────────────────────┐
│         Write-Ahead Log            │
│  wal_00001.log (active)            │
│  wal_00000.log (archived)          │
└────────────────────────────────────┘
┌────────────────────────────────────┐
│            Level 0                 │
│  sst_00001.sst (4MB)               │
│  sst_00002.sst (4MB)               │
│  sst_00003.sst (4MB)               │
└────────────────────────────────────┘
┌────────────────────────────────────┐
│            Level 1                 │
│  sst_00004.sst (40MB)              │
│  sst_00005.sst (40MB)              │
└────────────────────────────────────┘
┌────────────────────────────────────┐
│            Level 2                 │
│  sst_00006.sst (400MB)             │
└────────────────────────────────────┘
```

#### 3.1.2 Compaction戦略

**Level 0 → Level 1**:
- トリガー: Level 0 のファイル数が閾値（例: 4）を超える
- 戦略: 全てのLevel 0ファイルとLevel 1の重複キー範囲をマージ

**Level N → Level N+1**:
- トリガー: Level Nの合計サイズが閾値を超える
- 戦略: Level Nから1ファイル選択、Level N+1の重複範囲とマージ
- ファイル選択: 最も古いファイル、またはLevel N+1との重複が大きいファイル

**Tombstone（削除マーカー）の削除**:
- 下位レベルに削除マーカーが伝播したら上位レベルから削除
- 最下位レベルでは削除マーカーを即座に削除

---

### 3.2 Transaction Manager

#### 3.2.1 MVCC実装

**タイムスタンプ管理**:
```rust
pub struct TimestampOracle {
    current_ts: AtomicU64,
}

impl TimestampOracle {
    pub fn get_timestamp(&self) -> Timestamp {
        Timestamp(self.current_ts.fetch_add(1, Ordering::SeqCst))
    }
}
```

**バージョン付きキー**:
```
Physical Key Format:
┌──────────────┬───────────────┐
│ User Key     │ Timestamp     │
│ (variable)   │ (8 bytes, u64)│
└──────────────┴───────────────┘

Example:
  "user:123" @ ts=100  →  "user:123\x00\x00\x00\x00\x00\x00\x00\x64"
  "user:123" @ ts=200  →  "user:123\x00\x00\x00\x00\x00\x00\x00\xC8"
```

**可視性判定**:
```rust
fn is_visible(&self, key_ts: Timestamp, txn: &Transaction) -> bool {
    key_ts <= txn.start_ts
}
```

#### 3.2.2 楽観的並行性制御（OCC）

**Read Phase**:
```rust
impl Transaction {
    pub fn get(&mut self, key: &[u8]) -> Result<Option<Vec<u8>>> {
        // 1. write_setをチェック（自分の書き込み）
        if let Some(value) = self.write_set.get(key) {
            return Ok(Some(value.clone()));
        }

        // 2. KVStoreから読み取り（自分のstart_ts以前）
        let value = self.kv_store.get_versioned(key, self.start_ts)?;

        // 3. read_setに記録
        self.read_set.insert(key.to_vec());

        Ok(value)
    }

    pub fn put(&mut self, key: Vec<u8>, value: Vec<u8>) {
        // write_setに記録（まだKVStoreには書き込まない）
        self.write_set.insert(key, value);
    }
}
```

**Validation Phase**:
```rust
impl Transaction {
    pub fn commit(&mut self) -> Result<()> {
        // 1. commit_tsを取得
        self.commit_ts = Some(self.ts_oracle.get_timestamp());

        // 2. read_setの検証
        for key in &self.read_set {
            // 自分のstart_ts以降に他のトランザクションが書き込んでいないか
            if self.kv_store.has_newer_version(key, self.start_ts)? {
                return Err(Error::TransactionConflict);
            }
        }

        // 3. write_setをKVStoreに書き込み
        for (key, value) in &self.write_set {
            let versioned_key = make_versioned_key(key, self.commit_ts.unwrap());
            self.kv_store.put(versioned_key, value.clone())?;
        }

        Ok(())
    }
}
```

---

### 3.3 Query Executor

#### 3.3.1 Volcano-Style Iterator Model

```rust
pub trait Executor: Send {
    fn schema(&self) -> SchemaRef;
    fn execute(&mut self) -> Result<SendableRecordBatchStream>;
}

// RecordBatch: Arrow互換のカラムナー形式
pub struct RecordBatch {
    schema: SchemaRef,
    columns: Vec<ArrayRef>,
    num_rows: usize,
}
```

#### 3.3.2 主要Executor実装

**SeqScan**:
```rust
pub struct SeqScanExec {
    table: TableRef,
    predicate: Option<Expr>,
    projection: Vec<usize>,  // column indices
}

impl Executor for SeqScanExec {
    fn execute(&mut self) -> Result<SendableRecordBatchStream> {
        let iter = self.table.scan()?;

        let filtered = iter.filter(|batch| {
            apply_predicate(batch, &self.predicate)
        });

        let projected = filtered.map(|batch| {
            project_columns(batch, &self.projection)
        });

        Ok(Box::pin(stream::iter(projected)))
    }
}
```

**HashJoin**:
```rust
pub struct HashJoinExec {
    left: Box<dyn Executor>,
    right: Box<dyn Executor>,
    on: Vec<(Column, Column)>,  // join keys
    join_type: JoinType,
}

impl Executor for HashJoinExec {
    fn execute(&mut self) -> Result<SendableRecordBatchStream> {
        // 1. Build Phase: 右側のハッシュテーブル構築
        let mut hash_table = HashMap::new();
        let right_stream = self.right.execute()?;

        while let Some(batch) = right_stream.next().await {
            for row_idx in 0..batch.num_rows() {
                let key = extract_join_key(&batch, row_idx, &self.on);
                hash_table.entry(key).or_insert(vec![]).push(row_idx);
            }
        }

        // 2. Probe Phase: 左側をスキャンしてマッチング
        let left_stream = self.left.execute()?;
        let results = left_stream.map(|left_batch| {
            probe_and_join(&left_batch, &hash_table, &self.on, self.join_type)
        });

        Ok(Box::pin(results))
    }
}
```

---

### 3.4 Distributed Components

#### 3.4.1 Range Descriptor Management

**メタデータストレージ**:
```rust
pub struct MetadataStore {
    // Range情報
    ranges: BTreeMap<Key, RangeDescriptor>,

    // ノード情報
    nodes: HashMap<NodeID, NodeDescriptor>,

    // 変更ログ（Raftで複製）
    change_log: Vec<MetadataChange>,
}

pub struct RangeDescriptor {
    range_id: RangeID,
    start_key: Key,
    end_key: Key,
    replicas: Vec<NodeID>,  // [Leader, Follower1, Follower2]
    generation: u64,        // split/merge時にインクリメント
}

pub struct NodeDescriptor {
    node_id: NodeID,
    address: SocketAddr,
    status: NodeStatus,     // Online, Offline, Draining
    capacity: u64,          // available disk space
}
```

**Range Split手順**:
```
1. Leader検出: Rangeサイズが閾値超過

2. Split Point決定:
   - 中央キーを計算
   - アプリケーション定義の境界を尊重（テーブル境界など）

3. 新RangeDescriptor作成:
   - 元Range: [start_key, split_key)
   - 新Range: [split_key, end_key)

4. メタデータ更新（Raft経由）:
   - MetadataStoreに新RangeDescriptorを追加
   - クラスタ全体に伝播

5. データコピー:
   - 新Range用のRaftグループを初期化
   - 元Rangeからデータをコピー

6. 切り替え:
   - 新Rangeの初期化完了後、ルーティング切り替え
```

#### 3.4.2 Raft Integration

**Raftグループの構成**:
```
Range A:
  Leader: Node1
  Followers: Node2, Node3
  Raft Log: [Entry1, Entry2, ...]

Range B:
  Leader: Node2
  Followers: Node1, Node3
  Raft Log: [Entry1, Entry2, ...]

各Rangeは独立したRaftグループ
ノード間通信はalopex-chirps経由
```

**Write Path**:
```rust
async fn handle_write_request(
    &mut self,
    range_id: RangeID,
    command: Command
) -> Result<()> {
    // 1. Raftログに追加
    let entry = LogEntry {
        term: self.raft.current_term(),
        index: self.raft.next_index(),
        command,
    };

    // 2. Followerにレプリケーション
    self.raft.propose(entry).await?;

    // 3. 過半数の応答待機
    self.raft.wait_for_quorum().await?;

    // 4. KVStoreに適用
    self.apply_to_storage(entry).await?;

    Ok(())
}
```

**Leader Election**:
```
Follower (Heartbeat timeout):
  1. Become Candidate
  2. Increment term
  3. Vote for self
  4. Request votes from other nodes

Candidate (receive majority votes):
  1. Become Leader
  2. Send heartbeats to all Followers

Follower (receive higher term):
  1. Update term
  2. Become Follower
```

---

### 3.5 Vector Search Implementation

#### 3.5.1 Flat Search (Phase 1)

**インデックス構造**:
```rust
pub struct FlatVectorIndex {
    // ベクトルデータ
    vectors: Vec<(RowID, Vec<f32>)>,

    // 次元数
    dimension: usize,

    // 統計情報
    stats: IndexStats,
}

struct IndexStats {
    total_vectors: usize,
    avg_norm: f32,
}
```

**検索アルゴリズム**:
```rust
impl FlatVectorIndex {
    pub fn search(
        &self,
        query: &[f32],
        similarity: SimilarityMetric,
        k: usize,
        filter: Option<Predicate>
    ) -> Vec<(RowID, f32)> {
        // 1. 全ベクトルとの類似度計算
        let mut scores: Vec<_> = self.vectors
            .par_iter()  // 並列化
            .filter_map(|(row_id, vec)| {
                // フィルタ適用
                if let Some(ref pred) = filter {
                    if !pred.evaluate(*row_id) {
                        return None;
                    }
                }

                // 類似度計算
                let score = calculate_similarity(query, vec, similarity);
                Some((*row_id, score))
            })
            .collect();

        // 2. Top-K選択（Partial Sort）
        scores.select_nth_unstable_by(k, |a, b| {
            b.1.partial_cmp(&a.1).unwrap()
        });
        scores.truncate(k);

        scores
    }
}
```

**最適化**:
- SIMD命令による類似度計算高速化
- Rayon並列化
- 早期終了（Top-Kが確定したら以降の計算をスキップ）

#### 3.5.2 HNSW (Phase 2)

**データ構造**:
```rust
pub struct HNSWIndex {
    // 階層グラフ
    layers: Vec<Layer>,

    // エントリーポイント
    entry_point: NodeID,

    // ハイパーパラメータ
    max_connections: usize,       // M
    ef_construction: usize,       // efConstruction
    level_multiplier: f64,        // mL
}

struct Layer {
    level: usize,
    nodes: HashMap<NodeID, Node>,
}

struct Node {
    id: NodeID,
    vector: Vec<f32>,
    connections: Vec<NodeID>,  // size <= M
}
```

**検索アルゴリズム**:
```rust
impl HNSWIndex {
    pub fn search(
        &self,
        query: &[f32],
        k: usize,
        ef: usize
    ) -> Vec<(NodeID, f32)> {
        let mut current = self.entry_point;

        // 1. 上位レイヤーから下位へ貪欲探索
        for layer in self.layers.iter().rev() {
            current = self.greedy_search_layer(
                query,
                current,
                layer,
                1  // ef=1 for upper layers
            )[0].0;
        }

        // 2. 最下位レイヤーでef個の候補を探索
        let candidates = self.greedy_search_layer(
            query,
            current,
            &self.layers[0],
            ef
        );

        // 3. Top-Kを返す
        candidates.into_iter().take(k).collect()
    }

    fn greedy_search_layer(
        &self,
        query: &[f32],
        entry: NodeID,
        layer: &Layer,
        ef: usize
    ) -> Vec<(NodeID, f32)> {
        let mut visited = HashSet::new();
        let mut candidates = BinaryHeap::new();  // max-heap
        let mut results = BinaryHeap::new();     // min-heap

        // 初期ノード
        let dist = self.distance(query, entry);
        candidates.push((Reverse(dist), entry));
        results.push((dist, entry));
        visited.insert(entry);

        while let Some((Reverse(dist), current)) = candidates.pop() {
            if dist > results.peek().unwrap().0 {
                break;  // 候補がresultsの最悪値より悪い
            }

            // 隣接ノードを探索
            for &neighbor in &layer.nodes[&current].connections {
                if visited.contains(&neighbor) {
                    continue;
                }
                visited.insert(neighbor);

                let neighbor_dist = self.distance(query, neighbor);

                if neighbor_dist < results.peek().unwrap().0 || results.len() < ef {
                    candidates.push((Reverse(neighbor_dist), neighbor));
                    results.push((neighbor_dist, neighbor));

                    if results.len() > ef {
                        results.pop();  // 最悪値を削除
                    }
                }
            }
        }

        results.into_sorted_vec()
    }
}
```

**構築アルゴリズム**（概要）:
```
for each vector v:
  1. レベルを決定（指数分布）
  2. entry_pointから貪欲探索で最近傍を見つける
  3. 各レイヤーで近傍M個に接続
  4. 逆方向の接続も追加（双方向グラフ）
  5. 必要に応じてプルーニング（接続数 <= M）
```

---

### 3.6 WASM Integration

#### 3.6.1 ストレージアダプター選択

```rust
pub trait WasmStorage: Send + Sync {
    async fn get(&self, key: &[u8]) -> Result<Option<Vec<u8>>>;
    async fn put(&self, key: &[u8], value: &[u8]) -> Result<()>;
    async fn delete(&self, key: &[u8]) -> Result<()>;
    async fn scan(&self, start: &[u8], end: &[u8]) -> Result<Vec<(Vec<u8>, Vec<u8>)>>;
}

// 環境に応じて選択
pub async fn create_wasm_storage() -> Box<dyn WasmStorage> {
    if opfs_available() {
        Box::new(OPFSStorage::new().await)
    } else {
        Box::new(IndexedDBStorage::new().await)
    }
}
```

#### 3.6.2 非同期処理

**wasm-bindgen-futures**:
```rust
#[wasm_bindgen]
impl AlopexDB {
    #[wasm_bindgen]
    pub async fn query(&self, sql: String) -> Result<JsValue, JsValue> {
        // Rustの非同期処理をJavaScript Promiseに変換
        let result = self.inner.query(&sql).await
            .map_err(|e| JsValue::from_str(&e.to_string()))?;

        serde_wasm_bindgen::to_value(&result)
            .map_err(|e| JsValue::from_str(&e.to_string()))
    }
}
```

**Web Workers対応**:
```rust
// Worker側
#[wasm_bindgen]
pub struct AlopexWorker {
    db: Arc<Database>,
}

#[wasm_bindgen]
impl AlopexWorker {
    #[wasm_bindgen(constructor)]
    pub async fn new() -> Result<AlopexWorker, JsValue> {
        let db = Database::open_wasm("worker_db").await?;
        Ok(AlopexWorker { db: Arc::new(db) })
    }

    #[wasm_bindgen]
    pub async fn execute_in_worker(&self, sql: String) -> Result<JsValue, JsValue> {
        // Worker内で重い処理を実行
        self.db.execute(&sql).await
    }
}
```

---

### 3.5 Columnar Engine と Vector Store（Columnar API基盤）

本節では `design/technical-spec-columnar.md` で定義したカラムナ/ベクトル拡張を、Alopex 全体設計に落とし込む。

#### 3.5.1 スコープとゴール
- Alopex KVS の LSM を永続層として使い、`.alopex` ファイルのセクション `0x03 ColumnarSegment` に複数カラムの圧縮セグメントを格納する。
- SQL（PostgreSQL 方言）と DataFrame（Polars ライク）を同一カラムナ実行基盤で提供し、ベクトル検索 API を同じ物理ストレージ上で動かす。
- 目標: 40x 圧縮、1GB/s スキャン、分析クエリ 50ms 程度、列/セグメント/RowGroup レベルのプルーニングを必須とする。

#### 3.5.2 フォーマット V2（`.cseg`想定・セクション0x03）
- ヘッダ: `ALXC` + version + column_count + row_count + row_group_size + checksum_scope + compression。
- Column Descriptor: logical_type, encoding, compression, nullable, fixed_len, dictionary/page オフセット、data_offset/length。
- Row Group Table: row_start, row_count, column_chunk_offsets/lengths, chunk_checksum（checksum_scope が chunk の場合）。
- ボディ: Column Chunk = {PageHeader, PageBody} を column_count × row_group_count で配置。PageHeader に value_count/null_count/encoding/compression/uncompressed_len/compressed_len/checksum。
- フッタ: Row Group Table + Column Descriptor の再掲 + footer checksum。16MiB ガードを継続。
- エンコード: plain/dictionary/rle/bitpack + Delta/ByteStreamSplit/FOR/PFOR/IncrementalString などを拡張（型/分布に応じたヒューリスティックで自動選択）。nullable ビットマップを保持。
- 圧縮: None/LZ4/Zstd/（将来 Snappy/Brotli）。Zstd は辞書学習オプションあり。

#### 3.5.3 KVS レイアウトと I/O パス
- KVS キー（プレフィックス例）: `0x11` column_segment, `0x12` segment_index, `0x13` statistics, `0x14` row_group, `0x10` table_meta。
- 書き込み: RecordBatch → エンコーディング選択 → ページ化 → 圧縮 → column_chunk を KVS に分割書き込み → SegmentIndex/Statistics を bincode で併置 → `.alopex` の Section 0x03 にもシリアライズ（ウォームストレージ/バックアップ用）。
- 読み込み: SegmentIndex → 統計プルーニング → 列プルーニング → chunk 単位ストリーミング decode（O(row_group_size) メモリ）。SegmentCache で列+row_group キャッシュ。
- 統計: min/max/null_count/distinct（推定）。ベクトル列は dimension/metric をメタに保持し、距離計算の整合性を保証。

#### 3.5.4 API サーフェス（SQL / DataFrame / ベクトル）
- SQL 拡張: `WITH (storage='columnar', compression='lz4|zstd', row_group_size=...)`、`VECTOR(n)` 型、`vector_distance`/`vector_similarity` 関数、`COPY ... (FORMAT PARQUET|CSV)` でバルクロード。`INSERT ... VALUES` は RecordBatch 経由でセグメント化。
- DataFrame API: `Connection::query(sql) -> LazyFrame`、`insert_batch/insert_stream` で RecordBatch を直接書き込み。LazyFrame 上で projection/filter/sort/group/join を最適化し、ColumnarScan 物理演算子に projection pushdown と統計プルーニングを適用。
- Vector Store: ベクトル列は ColumnarSegment に格納し、Flat 検索（Phase1）では距離計算を columnar バッチに対して SIMD で実施。HNSW（Phase2以降）は別 Index Section として管理するが、ベースデータの真値は ColumnarSegment に置く。フィルタ付き KNN は「統計/RowGroup プルーニング → 距離計算 → SQL フィルタ適用」の順で実行。

#### 3.5.5 実装フェーズ案（抜粋）
- P1: Segment V2 Reader/Writer（マルチカラム、RowGroupTable、footer checksum、nullable 対応） + LZ4/Zstd、統計収集。
- P2: ColumnarStorageManager（KVS 書き込み/読み出し、SegmentIndex/Statistics、列/RowGroup プルーニング）。
- P3: ColumnarScan 物理演算子 + Optimizer ルール（projection/filter pushdown、stats pruning） + COPY/INSERT バルクロード。
- P4: Vector Flat Search on Columnar（SIMD 距離計算、metric 正規化、フィルタ前置/後置戦略）。
- P5: Section 0x03 統合（.alopex writer/reader）とバックアップ/リカバリ動線。

---

## 4. 通信プロトコル設計

### 4.1 HTTP API

**エンドポイント設計**:

```
POST /api/v1/sql
  Request:
    {
      "query": "SELECT * FROM users WHERE id = ?",
      "params": [1]
    }
  Response:
    {
      "success": true,
      "data": {
        "columns": ["id", "name", "age"],
        "rows": [[1, "Alice", 30]]
      },
      "execution_time_ms": 12
    }

POST /api/v1/vector/search
  Request:
    {
      "table": "documents",
      "column": "embedding",
      "query_vector": [0.1, 0.2, ...],
      "similarity": "cosine",
      "limit": 10,
      "filter": "category = 'tech'"
    }
  Response:
    {
      "success": true,
      "data": {
        "results": [
          {"id": 123, "similarity": 0.95, "content": "..."},
          {"id": 456, "similarity": 0.92, "content": "..."}
        ]
      },
      "execution_time_ms": 45
    }

POST /api/v1/transaction/begin
POST /api/v1/transaction/commit
POST /api/v1/transaction/rollback

GET /metrics
  Prometheus形式のメトリクス

GET /health
  Response: {"status": "healthy", "version": "0.3.0"}
```

### 4.2 内部通信プロトコル（alopex-chirps使用）

Alopex DBのノード間通信は、クラスタ制御の中核を担う **alopex-chirps** に完全に依存する。Chirpsは、Gossipベースのメンバーシップ管理と、柔軟なメッセージング機能を提供する独立したコンポーネントである。

#### 4.2.1 Chirpsのアーキテクチャ概要

Chirpsは、ユースケースに応じてメッセージングプロトコルを透過的に切り替えることができる**三層アーキテクチャ**を採用している。

1.  **APIレイヤ**: Alopex DBが利用する層。`send_to` や `broadcast` といったAPIを呼び出す際に、メッセージの性質（`Profile`）を指定する。
2.  **ルーティングレイヤ**: `MessageProfile`（例: `Control`, `Durable`）に基づき、最適なバックエンドプロトコルを選択する。
3.  **バックエンドレイヤ**: 実際の通信を担うプロトコル実装。
    *   `QuicBackend`: 低レイテンシが求められるRaftメッセージやGossipに利用。
    *   `IggyBackend`: 永続性が求められるChangefeedや監査ログに利用。
    *   将来的にKafka等も追加可能。

この設計により、Alopex DBは「Raftメッセージは高速なQUICで」「イベントストリームは永続的なIggyで」といった使い分けを、単一の通信基盤上で実現できる。

#### 4.2.2 Alopex DBからの利用方法（バージョン別制約付き）

Alopex DBは、Chirpsが提供するAPIを通じて、クラスタ内の他ノードと通信する。ただし、**Chirpsのバージョンによって利用可能な機能が制限される**。

##### v0.7-v0.8 (Alopex): Control/Ephemeralプロファイルのみ

**Chirps依存**: v0.3-v0.4 (QuicBackend のみ、IggyBackend未実装)

```rust
use alopex_chirps::{Mesh, MessageProfile};

// ✅ Raftメッセージ（Control profile）
let raft_msg_payload = bincode::serialize(&raft_msg)?;
mesh.send_to(target_node, &raft_msg_payload, MessageProfile::Control).await?;

// ✅ Gossip/Anti-Entropy（Ephemeral profile）
let gossip_payload = bincode::serialize(&gossip_msg)?;
mesh.broadcast(&gossip_payload, MessageProfile::Ephemeral).await?;

// ❌ Durableプロファイルは使用不可（IggyBackend未実装）
// mesh.broadcast(&event, MessageProfile::Durable).await?; // Error
```

##### v0.9+ (Alopex): Durableプロファイル利用可能

**Chirps依存**: v0.7+ (IggyBackend実装完了)

```rust
// ✅ Changefeed（Durable profile → Iggy）
let event_payload = bincode::serialize(&change_event)?;
mesh.broadcast(&event_payload, MessageProfile::Durable).await?;

// ✅ 監査ログ（Durable profile）
let audit_log = bincode::serialize(&log_entry)?;
mesh.send_to(audit_node, &audit_log, MessageProfile::Durable).await?;
```

**メッセージ受信**（全バージョン共通）:
```rust
// 全てのバックエンドからのメッセージを単一のハンドラで受信
mesh.subscribe(|from_node, payload| async move {
    let msg: InternalMessage = bincode::deserialize(&payload)?;
    match msg {
        // Raftメッセージの処理
        InternalMessage::Raft { .. } => handle_raft(msg),
        // メタデータ更新の処理
        InternalMessage::Metadata { .. } => handle_metadata(msg),
        // Changefeedイベント（v0.9+）
        InternalMessage::Changefeed { .. } => handle_changefeed(msg),
        // ...
    }
}).await;
```

#### 4.2.3 主要な設計要件とタイムライン制約

**全バージョン共通**:
- **メンバーシップ管理**: SWIM互換のGossipプロトコルにより、ノードの参加、離脱、障害を自動的に検出・伝播する。
- **Transport**: 通信はすべてQUIC/TLSで暗号化され、安全性が保証される。
- **API**: Alopex DBからは `send_to(..., profile)`, `broadcast(..., profile)`, `subscribe(...)` といった抽象化されたAPIのみを利用し、プロトコルの詳細から隔離される。

**バージョン依存機能**:

| Alopex | Chirps | 利用可能Profile | 制約 |
|--------|--------|----------------|------|
| v0.7 | v0.3 | Control, Ephemeral | ❌ Durable不可 |
| v0.8 | v0.4 | Control, Ephemeral | ❌ Durable不可、✅ Raft優先ストリーム |
| v0.9+ | v0.7+ | Control, Ephemeral, **Durable** | ✅ 全Profile利用可能 |

**重要**: v0.7-v0.8では、**Changefeed等の永続化機能は実装を延期**し、Chirps v0.7+完成後のv0.9で実装する。

### 4.3 クラスタ間フェデレーション設計

複数の独立したAlopexクラスタを連携させ、グローバル規模でのデータ同期と高可用性を実現する。

#### 4.3.1 フェデレーションアーキテクチャ

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Federation Control Plane                            │
│                                                                          │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐   │
│  │ Federation      │     │ Conflict        │     │ Global          │   │
│  │ Coordinator     │     │ Resolver        │     │ Router          │   │
│  └────────┬────────┘     └────────┬────────┘     └────────┬────────┘   │
│           │                       │                       │             │
│           └───────────────────────┼───────────────────────┘             │
│                                   │                                      │
└───────────────────────────────────┼──────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────┐
        │                           │                       │
        ▼                           ▼                       ▼
┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
│   Cluster: Tokyo  │   │  Cluster: US-East │   │  Cluster: EU-West │
│                   │   │                   │   │                   │
│  ┌─────────────┐  │   │  ┌─────────────┐  │   │  ┌─────────────┐  │
│  │ Federation  │◄─┼───┼──┤ Federation  │◄─┼───┼──┤ Federation  │  │
│  │ Gateway     │  │   │  │ Gateway     │  │   │  │ Gateway     │  │
│  └──────┬──────┘  │   │  └──────┬──────┘  │   │  └──────┬──────┘  │
│         │         │   │         │         │   │         │         │
│  ┌──────┴──────┐  │   │  ┌──────┴──────┐  │   │  ┌──────┴──────┐  │
│  │ Chirps Mesh │  │   │  │ Chirps Mesh │  │   │  │ Chirps Mesh │  │
│  │ (Intra)     │  │   │  │ (Intra)     │  │   │  │ (Intra)     │  │
│  └─────────────┘  │   │  └─────────────┘  │   │  └─────────────┘  │
│                   │   │                   │   │                   │
│  [Node1][Node2]..│   │  [Node1][Node2].. │   │  [Node1][Node2].. │
└───────────────────┘   └───────────────────┘   └───────────────────┘
```

#### 4.3.2 コンポーネント設計

##### A. Federation Gateway

各クラスタに配置され、フェデレーション通信を担当する。

```rust
/// フェデレーションゲートウェイ
pub struct FederationGateway {
    /// 自クラスタのChirps Mesh
    local_mesh: Arc<Mesh>,

    /// 他クラスタへのコネクション
    remote_clusters: HashMap<ClusterId, RemoteClusterConnection>,

    /// レプリケーションストリーム
    replication_streams: ReplicationStreamManager,

    /// コンフリクト解決器
    conflict_resolver: Arc<dyn ConflictResolver>,
}

/// リモートクラスタ接続
pub struct RemoteClusterConnection {
    cluster_id: ClusterId,
    endpoints: Vec<SocketAddr>,  // 複数エンドポイントで冗長化
    quic_connection: QuicConnection,
    status: ConnectionStatus,
    latency_tracker: LatencyTracker,
}

/// 接続状態
pub enum ConnectionStatus {
    Connected { since: Instant },
    Connecting { attempt: u32 },
    Disconnected { last_error: Option<FederationError> },
    Degraded { reason: String },  // 部分的接続
}
```

##### B. Replication Stream Manager

非同期レプリケーションを管理する。

```rust
/// レプリケーションストリーム
pub struct ReplicationStream {
    source_cluster: ClusterId,
    target_cluster: ClusterId,

    /// レプリケーション対象の定義
    scope: ReplicationScope,

    /// 現在位置（WAL LSN相当）
    position: ReplicationPosition,

    /// ラグ監視
    lag_monitor: LagMonitor,
}

/// レプリケーション対象
pub enum ReplicationScope {
    /// 全データ
    Full,
    /// 特定のテーブルのみ
    Tables(Vec<TableName>),
    /// 特定のキーレンジのみ
    Ranges(Vec<KeyRange>),
    /// カスタムフィルター（WHERE句相当）
    Filtered { predicate: String },
}

/// レプリケーションイベント
pub struct ReplicationEvent {
    /// ソースクラスタでのタイムスタンプ（HLC: Hybrid Logical Clock）
    hlc_timestamp: HybridTimestamp,
    /// 操作種別
    operation: Operation,
    /// 対象データ
    key: Bytes,
    value: Option<Bytes>,
    /// メタデータ
    table: TableName,
    range_id: RangeId,
}

pub enum Operation {
    Put,
    Delete,
    /// CRDT専用
    CrdtMerge { crdt_type: CrdtType, delta: Bytes },
}
```

##### C. Conflict Resolver

クラスタ間のコンフリクトを解決する。

```rust
/// コンフリクト解決戦略
#[async_trait]
pub trait ConflictResolver: Send + Sync {
    async fn resolve(
        &self,
        local: &ReplicationEvent,
        remote: &ReplicationEvent,
    ) -> ConflictResolution;
}

pub enum ConflictResolution {
    /// ローカル値を採用
    KeepLocal,
    /// リモート値を採用
    AcceptRemote,
    /// マージ結果を使用
    Merge(Bytes),
    /// 手動解決が必要
    RequireManualResolution { reason: String },
}

/// Last-Write-Wins戦略
pub struct LastWriteWinsResolver;

impl ConflictResolver for LastWriteWinsResolver {
    async fn resolve(
        &self,
        local: &ReplicationEvent,
        remote: &ReplicationEvent,
    ) -> ConflictResolution {
        if remote.hlc_timestamp > local.hlc_timestamp {
            ConflictResolution::AcceptRemote
        } else {
            ConflictResolution::KeepLocal
        }
    }
}

/// CRDT-based解決（結果整合性保証）
pub struct CrdtResolver;

impl ConflictResolver for CrdtResolver {
    async fn resolve(
        &self,
        local: &ReplicationEvent,
        remote: &ReplicationEvent,
    ) -> ConflictResolution {
        // CRDTはマージ可能
        match (&local.operation, &remote.operation) {
            (Operation::CrdtMerge { crdt_type: t1, delta: d1 },
             Operation::CrdtMerge { crdt_type: t2, delta: d2 }) if t1 == t2 => {
                let merged = crdt_merge(t1, d1, d2);
                ConflictResolution::Merge(merged)
            }
            _ => ConflictResolution::RequireManualResolution {
                reason: "Non-CRDT operations cannot be auto-merged".into(),
            },
        }
    }
}
```

#### 4.3.3 フェデレーショントポロジ

```rust
/// トポロジ設定
pub enum FederationTopology {
    /// Hub-Spoke: 中央ハブと複数スポーク
    HubSpoke {
        hub: ClusterId,
        spokes: Vec<ClusterId>,
    },

    /// Mesh: 全クラスタが対等接続
    Mesh {
        clusters: Vec<ClusterId>,
    },

    /// Hierarchical: 階層構造
    Hierarchical {
        root: ClusterId,
        children: HashMap<ClusterId, Vec<ClusterId>>,
    },
}

/// フェデレーション設定例
pub struct FederationConfig {
    /// 自クラスタID
    cluster_id: ClusterId,

    /// トポロジ
    topology: FederationTopology,

    /// リモートクラスタ設定
    remote_clusters: Vec<RemoteClusterConfig>,

    /// レプリケーション設定
    replication: ReplicationConfig,

    /// コンフリクト解決戦略
    conflict_strategy: ConflictStrategy,
}

pub struct ReplicationConfig {
    /// レプリケーションモード
    mode: ReplicationMode,
    /// ラグ閾値（アラート用）
    max_lag_seconds: u64,
    /// バッチサイズ
    batch_size: usize,
}

pub enum ReplicationMode {
    /// 非同期（デフォルト）
    Async,
    /// 準同期（ローカルコミット + リモート確認待ち）
    SemiSync { ack_timeout: Duration },
}
```

#### 4.3.4 グローバルルーティング

```rust
/// グローバルルーター
pub struct GlobalRouter {
    /// クラスタトポロジ情報
    topology: Arc<RwLock<TopologyInfo>>,

    /// Locality情報
    locality_detector: LocalityDetector,
}

impl GlobalRouter {
    /// クエリをルーティング
    pub async fn route_query(
        &self,
        query: &Query,
        client_region: Option<Region>,
    ) -> RoutingDecision {
        // 1. データのホームクラスタを特定
        let home_clusters = self.find_home_clusters(query).await;

        // 2. Locality-aware選択
        if let Some(region) = client_region {
            if let Some(local) = home_clusters.iter()
                .find(|c| c.region == region) {
                return RoutingDecision::Local(local.clone());
            }
        }

        // 3. 最寄りクラスタを選択
        let nearest = self.select_nearest(&home_clusters).await;
        RoutingDecision::Remote(nearest)
    }

    /// 書き込みルーティング
    pub async fn route_write(
        &self,
        table: &TableName,
        key: &[u8],
    ) -> RoutingDecision {
        // 書き込みはプライマリクラスタへ
        let primary = self.get_primary_cluster(table).await;
        RoutingDecision::Primary(primary)
    }
}

pub enum RoutingDecision {
    /// ローカルクラスタで処理
    Local(ClusterInfo),
    /// リモートクラスタへ転送
    Remote(ClusterInfo),
    /// プライマリクラスタへ（書き込み用）
    Primary(ClusterInfo),
    /// 複数クラスタへ（scatter-gather）
    Scatter(Vec<ClusterInfo>),
}
```

#### 4.3.5 Chirps拡張（Federation Profile）

```rust
/// フェデレーション用メッセージプロファイル
pub enum MessageProfile {
    // 既存
    Control,      // Raft等
    Ephemeral,    // Gossip等
    Durable,      // Changefeed等（Iggy経由）

    // フェデレーション追加
    Federation,   // クラスタ間通信専用
}

/// フェデレーション用バックエンド
pub struct FederationBackend {
    /// 各リモートクラスタへのQUICコネクション
    connections: HashMap<ClusterId, QuicConnection>,

    /// mTLS証明書（クラスタ間認証）
    cluster_certs: ClusterCertificates,

    /// 優先度制御
    priority_controller: PriorityController,
}

impl MessageBackend for FederationBackend {
    async fn send_to(
        &self,
        target: NodeId,
        bytes: &[u8],
    ) -> Result<(), Self::Error> {
        // NodeIdからクラスタとノードを特定
        let (cluster_id, local_node_id) = parse_federated_node_id(target)?;

        // クラスタ間接続経由で送信
        let conn = self.connections.get(&cluster_id)
            .ok_or(FederationError::ClusterNotConnected)?;

        conn.send(local_node_id, bytes).await
    }
}
```

#### 4.3.6 障害時動作とフェイルオーバー

```rust
/// フェイルオーバーマネージャー
pub struct FailoverManager {
    /// 現在のプライマリクラスタ（テーブル/Range別）
    primary_assignments: Arc<RwLock<HashMap<TableName, ClusterId>>>,

    /// スタンバイクラスタ
    standby_clusters: Vec<ClusterId>,

    /// フェイルオーバーポリシー
    policy: FailoverPolicy,
}

pub struct FailoverPolicy {
    /// フェイルオーバー発動条件
    trigger: FailoverTrigger,
    /// 自動 or 手動
    mode: FailoverMode,
    /// 切り戻し設定
    failback: FailbackConfig,
}

pub enum FailoverTrigger {
    /// N秒間応答なし
    NoResponse { timeout_secs: u64 },
    /// レプリケーションラグ超過
    LagExceeded { max_lag_secs: u64 },
    /// 手動トリガー
    Manual,
}

impl FailoverManager {
    /// プライマリ障害検出時
    pub async fn initiate_failover(
        &self,
        failed_cluster: ClusterId,
        tables: Vec<TableName>,
    ) -> Result<FailoverResult> {
        // 1. スタンバイ選択
        let new_primary = self.select_standby(&tables).await?;

        // 2. レプリケーション同期確認
        let lag = self.check_replication_lag(failed_cluster, new_primary).await?;
        if lag > self.policy.max_acceptable_lag {
            warn!("Failover with data loss: lag={} seconds", lag);
        }

        // 3. プライマリ切り替え
        self.switch_primary(tables, new_primary).await?;

        // 4. ルーティング更新を全クラスタへ伝播
        self.broadcast_routing_update().await?;

        Ok(FailoverResult {
            new_primary,
            data_loss_seconds: lag,
        })
    }
}
```

#### 4.3.7 設定例

```toml
# federation.toml

[federation]
cluster_id = "tokyo-01"
enabled = true

[federation.topology]
type = "mesh"  # hub-spoke, mesh, hierarchical

[[federation.remote_clusters]]
cluster_id = "us-east-01"
endpoints = ["us-east-1.alopex.example.com:7100", "us-east-2.alopex.example.com:7100"]
region = "us-east"

[[federation.remote_clusters]]
cluster_id = "eu-west-01"
endpoints = ["eu-west-1.alopex.example.com:7100"]
region = "eu-west"

[federation.replication]
mode = "async"
max_lag_seconds = 10
batch_size = 1000

# テーブル別レプリケーション設定
[[federation.replication.rules]]
tables = ["users", "orders"]
target_clusters = ["us-east-01", "eu-west-01"]
conflict_strategy = "last_write_wins"

[[federation.replication.rules]]
tables = ["metrics"]
target_clusters = ["us-east-01"]
conflict_strategy = "crdt"
crdt_type = "counter"

[federation.failover]
mode = "automatic"
trigger = { type = "no_response", timeout_secs = 30 }
max_acceptable_lag_secs = 5

[federation.tls]
cert_file = "/etc/alopex/federation.crt"
key_file = "/etc/alopex/federation.key"
ca_file = "/etc/alopex/federation-ca.crt"
```

#### 4.3.8 マイルストーン

| バージョン | フェデレーション機能 | Chirps依存 |
|----------|-------------------|-----------|
| v0.9 | 基盤設計・プロトタイプ | v0.7（Durable profile） |
| v1.0 | 2クラスタ間フェデレーション | v0.8（Federation profile） |
| v1.1 | マルチクラスタMesh | v0.9 |
| v1.2 | 高度なコンフリクト解決・自動フェイルオーバー | v1.0 |

---

## 5. エラーハンドリング設計

### 5.1 エラー階層

```rust
#[derive(Debug, thiserror::Error)]
pub enum AlopexError {
    // Storage Layer
    #[error("Storage error: {0}")]
    Storage(#[from] StorageError),

    // SQL Layer
    #[error("SQL error: {0}")]
    SQL(#[from] SQLError),

    // Transaction Layer
    #[error("Transaction error: {0}")]
    Transaction(#[from] TransactionError),

    // Distributed Layer
    #[error("Cluster error: {0}")]
    Cluster(#[from] ClusterError),

    // General
    #[error("IO error: {0}")]
    IO(#[from] std::io::Error),

    #[error("Internal error: {0}")]
    Internal(String),
}

#[derive(Debug, thiserror::Error)]
pub enum TransactionError {
    #[error("Transaction conflict detected")]
    Conflict,

    #[error("Deadlock detected")]
    Deadlock,

    #[error("Transaction timeout")]
    Timeout,
}
```

### 5.2 リトライ戦略

```rust
pub async fn execute_with_retry<F, T>(
    f: F,
    max_retries: usize
) -> Result<T>
where
    F: Fn() -> Result<T>,
{
    let mut retries = 0;
    loop {
        match f() {
            Ok(result) => return Ok(result),
            Err(e) if is_retryable(&e) && retries < max_retries => {
                retries += 1;
                let backoff = Duration::from_millis(100 * 2u64.pow(retries as u32));
                tokio::time::sleep(backoff).await;
            }
            Err(e) => return Err(e),
        }
    }
}

fn is_retryable(error: &AlopexError) -> bool {
    matches!(error,
        AlopexError::Transaction(TransactionError::Conflict) |
        AlopexError::Transaction(TransactionError::Deadlock) |
        AlopexError::Cluster(ClusterError::LeaderNotFound)
    )
}
```

---

## 6. 運用設計

### 6.1 監視設計

**監視項目**:

| カテゴリ | メトリクス | 閾値 |
|---------|-----------|------|
| Performance | query_duration_p99 | <100ms |
| | write_throughput | >10k ops/sec |
| Storage | memtable_size | <128MB |
| | sstable_count_l0 | <8 |
| | disk_usage_percent | <80% |
| Transaction | conflict_rate | <1% |
| | deadlock_rate | <0.1% |
| Cluster | raft_leader_elections | <1/hour |
| | node_availability | >99.9% |

**アラート定義**:
```yaml
alerts:
  - name: HighQueryLatency
    expr: alopex_query_duration_seconds{quantile="0.99"} > 0.1
    for: 5m
    severity: warning

  - name: NodeDown
    expr: up{job="alopex"} == 0
    for: 1m
    severity: critical

  - name: HighConflictRate
    expr: rate(alopex_transaction_conflicts_total[5m]) > 0.01
    for: 10m
    severity: warning
```

### 6.2 バックアップ・リストア設計

**バックアップ戦略**:
```
Daily Full Backup:
  - スナップショットベース
  - S3/GCS等のオブジェクトストレージに保存
  - 並列バックアップ（Rangeごと）

Continuous WAL Archiving:
  - WALセグメントを継続的にアーカイブ
  - PITR (Point-In-Time Recovery) を可能に
  - 5分間隔でアップロード
```

**リストア手順**:
```
1. フルバックアップからベースをリストア
2. アーカイブされたWALを適用（指定時刻まで）
3. クラスタ再構成（Raftグループ再初期化）
4. サービス開始
```

### 6.3 スケーリング設計

**水平スケーリング（ノード追加）**:
```
1. 新ノードをクラスタに参加（alopex-chirps経由）
2. メタデータ同期
3. Rangeの再配置計画作成
   - 各ノードのRange数を均等化
4. Range転送
   - スナップショット転送
   - Raftグループ再構成
5. 完了後、古いノードからRange削除
```

**垂直スケーリング（リソース追加）**:
- MemTableサイズ拡大
- SSTableキャッシュサイズ拡大
- Compactionスレッド数増加

---

## 7. セキュリティ設計

### 7.1 認証・認可

**認証フロー**:
```
Client
  │
  ▼
┌─────────────────┐
│ 1. Username/    │
│    Password     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 2. Authenticate │
│    (bcrypt)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 3. Generate     │
│    JWT Token    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 4. Return Token │
└─────────────────┘

Subsequent Requests:
  Header: Authorization: Bearer <token>
```

**RBAC実装**:
```sql
-- ロール定義
CREATE ROLE admin WITH
  SELECT, INSERT, UPDATE, DELETE ON ALL TABLES,
  GRANT ROLE TO USER;

CREATE ROLE analyst WITH
  SELECT ON ALL TABLES;

-- ユーザー作成
CREATE USER alice WITH PASSWORD 'secret' ROLE admin;
CREATE USER bob WITH PASSWORD 'secret' ROLE analyst;

-- 権限チェック
-- 各SQL実行前にACLManagerで権限確認
```

### 7.2 データ暗号化

**At Rest**:
- ディスク暗号化（LUKS, dm-crypt等）
- アプリケーション層暗号化（将来）
  - SSTableレベルでAES-256暗号化

**In Transit**:
- TLS 1.3 (HTTP API)
- QUIC (ノード間通信)
- 相互認証（証明書ベース）

---

## 8. テスト設計

### 8.1 テストピラミッド

```
        /\
       /  \
      / E2E\     10% (Playwright風テスト)
     /______\
    /        \
   /Integra- \   30% (統合テスト)
  /   tion    \
 /____________\
/              \
/  Unit Tests   \  60% (単体テスト)
/________________\
```

### 8.2 主要テストケース

**単体テスト**:
- KVStore: get/put/delete/scan
- MemTable: insertion, flush
- SSTable: read, compaction
- Transaction: ACID properties
- SQL Parser: syntax validation
- Vector Search: similarity calculation

**統合テスト**:
- SQL実行（E2E）
- トランザクションのコミット/ロールバック
- 並行トランザクション（コンフリクト検出）
- ベクトル検索（Flat, HNSW）
- 分散トランザクション（2PC）

**Chaos Engineering**:
- ネットワーク分断
- ノードクラッシュ
- ディスク遅延
- クロックスキュー
- パーティション回復後の整合性確認

---

## 9. 変更履歴

| バージョン | 日付 | 変更者 | 変更内容 |
|----------|------|--------|---------|
| 1.0 | 2025-11-21 | Claude | 初版作成 |
