# Chirps Raft統合 モジュール構成変更提案

**バージョン**: 1.0
**作成日**: 2025-11-29
**ステータス**: Proposal

---

## 1. 概要

### 1.0 現行クレート構造の確認結果（2025-11-29調査）

> **重要**: 本提案書作成時に現行のクレート構造を調査した結果、設計ドキュメントとの差異を確認。

#### 実際のワークスペース構成

```
alopex-db/
├── alopex/                    # 独立ワークスペース
│   ├── Cargo.toml (workspace)
│   └── crates/
│       ├── alopex-core/       # ✅ 存在 - 単独公開可能
│       ├── alopex-embedded/   # alopex-core に依存
│       ├── alopex-sql/
│       ├── alopex-server/
│       ├── alopex-cluster/    # ⚠️ 空（依存関係なし）
│       ├── alopex-cli/
│       └── alopex-tools/
│
└── chirps/                    # 独立ワークスペース
    ├── Cargo.toml (workspace)
    └── crates/
        ├── alopex-chirps/     # メインクレート
        ├── chirps-core/       # MessageBackend trait（alopex-core非依存）
        ├── chirps-transport-quic/
        ├── chirps-gossip-swim/
        ├── chirps-wire/
        └── chirps-mock/
```

#### Q1: `alopex-core`は単独で公開できるか？

**回答: はい、可能**

`alopex-core` は外部依存関係のみを使用:
- `bincode`, `crc32fast`, `serde`, `thiserror`, `snap`, `tracing`
- Optional: `zstd`, `lz4`, `xxhash-rust`
- WASM: `js-sys`, `web-sys`

**公開に必要な作業**:
1. `crates.io` に公開、または
2. `chirps` ワークスペースから `path` 依存で参照

#### Q2: `alopex-core` の実装範囲は想定とマッチしているか？

| 想定（本提案） | 実装状況 | 備考 |
|---------------|---------|------|
| WAL | ✅ 実装済 | `log/wal.rs` - WalWriter/WalReader |
| MemTable | ✅ 実装済 | `kv/memory.rs` - MemoryKV |
| SSTable | ⚠️ 構造のみ | `storage/sstable/` モジュール存在 |
| Compaction | ⚠️ 構造のみ | `storage/flush.rs` |

**想定外の追加機能**:
- `columnar/` - カラム型ストレージ（Encoding, Segment）
- `vector/` - ベクトル検索（Flat search, Metric）
- `txn/` - トランザクション管理
- `storage/large_value/` - 大きな値のチャンク管理

#### 現行依存関係の実態

```
現行（2つの独立ワークスペース、相互依存なし）:
┌──────────────────┐     ┌──────────────────┐
│    alopex/       │     │    chirps/       │
│                  │←─X─→│                  │
│  alopex-core     │     │  chirps-core     │
│  alopex-embedded │     │  chirps-quic     │
│  alopex-cluster  │     │  chirps-swim     │
│    (空)          │     │                  │
└──────────────────┘     └──────────────────┘

想定していた構成（修正が必要）:
  chirps → alopex-core (依存)  ← 現在は存在しない!
```

#### 本提案を実現するための選択肢

**Option A: `alopex-core` を `crates.io` に公開**
- メリット: クリーンな依存関係、バージョン管理
- デメリット: 公開プロセス、API安定化が必要

**Option B: `chirps` から `path` 依存で参照**
- メリット: 即座に利用可能
- デメリット: ワークスペースが分離したままで管理が複雑

**Option C: ワークスペース統合**
- メリット: 単一ワークスペースで管理簡素化
- デメリット: 大規模なリファクタリング

**Option D: `chirps-raft` が独自のログ永続化を持つ**
- メリット: `alopex-core` への依存なし
- デメリット: WAL実装の重複

**採用方針**:
1. **Phase 1**: **Option B**（path依存）で即座に開発開始
2. **Phase 2**: **Option A**（crates.io公開）に早期移行

```
Phase 1 (即座に実施):
  chirps/Cargo.toml に追加:
  [dependencies]
  alopex-core = { path = "../alopex/crates/alopex-core" }

Phase 2 (v0.5リリース前に実施):
  1. alopex-core の API を安定化
  2. crates.io に alopex-core を公開
  3. chirps の依存を crates.io 版に切り替え
```

---

### 1.1 目的

現在、Raft コンセンサスアルゴリズムは Alopex DB と Alopex Skulk で個別に実装されている。本提案では、Raft 実装を `alopex-chirps` に統合し、共通APIとして提供することで以下を実現する：

1. **コード重複の排除**: 両製品で同一のRaft実装を使用
2. **保守性向上**: Raft関連のバグ修正・改善が全製品に反映
3. **機能拡張の容易化**: フェデレーション等の高度機能を一箇所で実装
4. **テスト効率化**: Raftの単体テストを一元化

### 1.2 現状の課題

```
現行アーキテクチャの問題点:

┌─────────────────────────┐        ┌─────────────────────────┐
│      Alopex DB          │        │     Alopex Skulk        │
│  ┌───────────────────┐  │        │  ┌───────────────────┐  │
│  │ Distribution Layer│  │        │  │ Distribution Layer│  │
│  │  ┌─────────────┐  │  │        │  │  ┌─────────────┐  │  │
│  │  │ Raft        │←─┼──┼────────┼──┼──│ Raft        │  │  │
│  │  │ Replication │  │  │ 重複!  │  │  │ Replication │  │  │
│  │  └─────────────┘  │  │        │  │  └─────────────┘  │  │
│  └───────────────────┘  │        │  └───────────────────┘  │
└─────────────────────────┘        └─────────────────────────┘
          │                                    │
          ▼                                    ▼
┌─────────────────────────────────────────────────────────────┐
│                       alopex-chirps                          │
│  - QUIC Transport                                           │
│  - SWIM Membership                                          │
│  - Raft Messaging (メッセージ転送のみ、合意ロジックなし)      │
└─────────────────────────────────────────────────────────────┘
```

**問題点:**
- Raftロジックの二重実装によるメンテナンスコスト増大
- 両製品で異なるRaft設定・挙動が発生するリスク
- フェデレーション実装時に両方に変更が必要

---

## 2. 提案アーキテクチャ

### 2.1 変更後のモジュール構成

> **注**: 現行の2つの独立ワークスペース構成を前提とした提案。
> `alopex-core` への依存は **Option B → A**（path依存 → crates.io公開）を採用。

```
┌─────────────────────────────────────────────────────────────┐
│                    alopex/ workspace                         │
│  ┌─────────────────────────┐   ┌─────────────────────────┐  │
│  │      Alopex DB          │   │     Alopex Skulk        │  │
│  │  ┌───────────────────┐  │   │  ┌───────────────────┐  │  │
│  │  │ alopex-cluster    │  │   │  │ skulk-cluster     │  │  │
│  │  │  ┌─────────────┐  │  │   │  │  ┌─────────────┐  │  │  │
│  │  │  │ RaftClient  │  │  │   │  │  │ RaftClient  │  │  │  │
│  │  │  │ (API利用)   │  │  │   │  │  │ (API利用)   │  │  │  │
│  │  │  └──────┬──────┘  │  │   │  │  └──────┬──────┘  │  │  │
│  │  └─────────┼─────────┘  │   │  └─────────┼─────────┘  │  │
│  │            │            │   │            │            │  │
│  │  ┌─────────▼─────────┐  │   │  ┌─────────▼─────────┐  │  │
│  │  │  alopex-core      │  │   │  │  skulk-core       │  │  │
│  │  │  (WAL, KV, etc.)  │  │   │  │  (TSM, etc.)      │  │  │
│  │  └───────────────────┘  │   │  └───────────────────┘  │  │
│  └─────────────────────────┘   └─────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                │ crates.io or path 依存
                ▼
┌─────────────────────────────────────────────────────────────┐
│                    chirps/ workspace                         │
│  ┌─────────────────────────────────────────────────────────┐│
│  │                    alopex-chirps                        ││
│  │  ┌─────────────────────────────────────────────────────┐││
│  │  │              Raft Consensus API (chirps-raft)       │││
│  │  │  - RaftNode (Multi-Raft Group管理)                 │││
│  │  │  - StateMachine trait (アプリ側で実装)             │││
│  │  │  - RaftStorage trait (ログ・スナップショット)       │││
│  │  │  - WalRaftStorage (alopex-core WAL利用)            │││
│  │  └─────────────────────────────────────────────────────┘││
│  │  ┌─────────────────────────────────────────────────────┐││
│  │  │              Core Infrastructure                    │││
│  │  │  - chirps-transport-quic (QUIC Transport)          │││
│  │  │  - chirps-gossip-swim (SWIM Membership)            │││
│  │  │  - chirps-wire (Message Profiles)                  │││
│  │  └─────────────────────────────────────────────────────┘││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

**Option B → A 採用の理由**:
1. WAL実装の重複を回避（DRY原則）
2. `alopex-core` の成熟度向上に貢献
3. 早期にcrates.io公開することで外部利用も可能に

**Phase 1 依存設定** (`chirps/Cargo.toml`):
```toml
[workspace.dependencies]
alopex-core = { path = "../alopex/crates/alopex-core" }
```

### 2.2 レイヤー構成

```
┌───────────────────────────────────────────────────────────────┐
│  Application Layer (Alopex DB / Skulk)                       │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ StateMachine Implementation                              │ │
│  │  - Alopex DB: RangeStateMachine (KV操作)                │ │
│  │  - Skulk: ShardStateMachine (TSM操作)                   │ │
│  └─────────────────────────────────────────────────────────┘ │
├───────────────────────────────────────────────────────────────┤
│  Consensus Layer (alopex-chirps)                             │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Raft Consensus Engine (openraft ベース)                  │ │
│  │  - Leader Election                                       │ │
│  │  - Log Replication                                       │ │
│  │  - Membership Change                                     │ │
│  │  - Snapshot Transfer                                     │ │
│  └─────────────────────────────────────────────────────────┘ │
├───────────────────────────────────────────────────────────────┤
│  Transport Layer (alopex-chirps)                             │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ QUIC Transport + Message Profiles                        │ │
│  │  - Control Profile (Raft Messages, Priority: HIGH)       │ │
│  │  - Ephemeral Profile (Gossip, Priority: NORMAL)         │ │
│  │  - Durable Profile (Changefeed, Priority: LOW)          │ │
│  └─────────────────────────────────────────────────────────┘ │
├───────────────────────────────────────────────────────────────┤
│  Membership Layer (alopex-chirps)                            │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ SWIM Protocol                                            │ │
│  │  - Node Discovery                                        │ │
│  │  - Failure Detection                                     │ │
│  │  - Membership Dissemination                              │ │
│  └─────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

---

## 3. Chirps Raft API 設計

### 3.1 Core Traits

```rust
//! alopex-chirps Raft API

use async_trait::async_trait;

/// アプリケーション固有のステートマシン
/// Alopex DB と Skulk がそれぞれ実装
#[async_trait]
pub trait StateMachine: Send + Sync + 'static {
    /// コマンドの型（アプリケーション固有）
    type Command: Send + Sync + Clone + serde::Serialize + serde::de::DeserializeOwned;

    /// レスポンスの型
    type Response: Send + Sync + Clone + serde::Serialize + serde::de::DeserializeOwned;

    /// スナップショットの型
    type Snapshot: Send + Sync;

    /// コマンドを適用（Raft commitされた後に呼ばれる）
    async fn apply(&mut self, index: LogIndex, command: Self::Command) -> Result<Self::Response>;

    /// スナップショット生成
    async fn snapshot(&self) -> Result<Self::Snapshot>;

    /// スナップショットから復元
    async fn restore(&mut self, snapshot: Self::Snapshot) -> Result<()>;
}

/// Raftログとスナップショットの永続化
/// alopex-core の WAL を利用した実装を提供
#[async_trait]
pub trait RaftStorage: Send + Sync + 'static {
    /// ログエントリ追加
    async fn append_entries(&mut self, entries: Vec<LogEntry>) -> Result<()>;

    /// ログエントリ取得
    async fn get_entries(&self, start: LogIndex, end: LogIndex) -> Result<Vec<LogEntry>>;

    /// ログ切り詰め（スナップショット適用後）
    async fn truncate_before(&mut self, index: LogIndex) -> Result<()>;

    /// 永続化状態の取得
    async fn get_hard_state(&self) -> Result<HardState>;

    /// 永続化状態の保存
    async fn save_hard_state(&mut self, state: HardState) -> Result<()>;

    /// スナップショット保存
    async fn save_snapshot(&mut self, snapshot: SnapshotMeta, data: Vec<u8>) -> Result<()>;

    /// スナップショット読み込み
    async fn load_snapshot(&self) -> Result<Option<(SnapshotMeta, Vec<u8>)>>;
}
```

### 3.2 RaftNode API

```rust
//! Raft ノード管理

/// Raft グループ設定
pub struct RaftConfig {
    /// グループID
    pub group_id: GroupId,

    /// 自ノードID
    pub node_id: NodeId,

    /// 選挙タイムアウト（ミリ秒）
    pub election_timeout_ms: u64,

    /// ハートビート間隔（ミリ秒）
    pub heartbeat_interval_ms: u64,

    /// 最大ログエントリバッチサイズ
    pub max_batch_size: usize,

    /// スナップショット閾値（ログエントリ数）
    pub snapshot_threshold: u64,
}

/// Raft ノード
pub struct RaftNode<SM: StateMachine, S: RaftStorage> {
    config: RaftConfig,
    state_machine: SM,
    storage: S,
    transport: Arc<ChirpsTransport>,
    // ...内部状態
}

impl<SM: StateMachine, S: RaftStorage> RaftNode<SM, S> {
    /// 新規作成
    pub fn new(
        config: RaftConfig,
        state_machine: SM,
        storage: S,
        transport: Arc<ChirpsTransport>,
    ) -> Self;

    /// 起動
    pub async fn start(&mut self) -> Result<()>;

    /// コマンド提案（リーダーのみ）
    pub async fn propose(&self, command: SM::Command) -> Result<SM::Response>;

    /// 現在のリーダーを取得
    pub fn leader_id(&self) -> Option<NodeId>;

    /// リーダーかどうか
    pub fn is_leader(&self) -> bool;

    /// メンバーシップ変更を提案
    pub async fn change_membership(&self, change: MembershipChange) -> Result<()>;

    /// Raft メッセージを処理（Chirps から呼び出される）
    pub async fn handle_message(&mut self, msg: RaftMessage) -> Result<()>;

    /// 定期的なティック処理
    pub async fn tick(&mut self) -> Result<()>;
}
```

### 3.3 Multi-Raft グループ管理

```rust
//! 複数 Raft グループの管理

/// Multi-Raft マネージャ
pub struct MultiRaftManager<SM: StateMachine, S: RaftStorage> {
    /// グループIDからRaftノードへのマッピング
    groups: HashMap<GroupId, RaftNode<SM, S>>,

    /// Chirps トランスポート
    transport: Arc<ChirpsTransport>,

    /// ストレージファクトリ
    storage_factory: Box<dyn RaftStorageFactory<S>>,
}

impl<SM: StateMachine, S: RaftStorage> MultiRaftManager<SM, S> {
    /// グループを作成
    pub async fn create_group(
        &mut self,
        group_id: GroupId,
        initial_members: Vec<NodeId>,
        state_machine: SM,
    ) -> Result<()>;

    /// グループを取得
    pub fn get_group(&self, group_id: GroupId) -> Option<&RaftNode<SM, S>>;

    /// グループを削除
    pub async fn remove_group(&mut self, group_id: GroupId) -> Result<()>;

    /// メッセージをルーティング
    pub async fn route_message(&mut self, msg: RaftMessage) -> Result<()>;

    /// 全グループのティック処理
    pub async fn tick_all(&mut self) -> Result<()>;
}
```

### 3.4 タイムスタンプサービス

Chirpsは2つのレイヤーで異なるタイムスタンプ機能を提供する。

```
┌─────────────────────────────────────────────────────────────┐
│  Application Layer (Alopex DB / Skulk)                      │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Transaction: BEGIN → tso.get_timestamp() → COMMIT    │  │
│  │                           ↓                           │  │
│  │              Raft TSO (厳密な単調増加)                │  │
│  │   - MVCC、スナップショット分離、トランザクション順序   │  │
│  │   - Raft リーダーが集中発行                           │  │
│  └───────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  Infrastructure Layer (Chirps)                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  SWIM: node_joined(hlc), node_failed(hlc)             │  │
│  │  Gossip: message.timestamp = local_hlc.tick()         │  │
│  │                           ↓                           │  │
│  │              Gossip HLC (分散・低レイテンシ)          │  │
│  │   - ノード間イベント順序、メンバーシップ変更          │  │
│  │   - 各ノードがローカル発行、Gossipで収束              │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

| レイヤー | 方式 | 用途 | 提供バージョン |
|---------|------|------|---------------|
| インフラ層 | Gossip HLC | ノード間イベント順序、SWIM | v0.6 (chirps-gossip-swim) |
| アプリ層 | Raft TSO | MVCC、トランザクション | v0.6 (chirps-raft) |

#### 3.4.1 Raft TSO (アプリ層向け)

Raft API の一部として提供。クラスタ全体で一貫した単調増加タイムスタンプを発行。
TiKV の Placement Driver (PD) TSO に相当。

```rust
//! Raft Consensus API の一部としてのタイムスタンプ配信
//! アプリケーション層（Alopex DB / Skulk）が使用

use std::time::{Duration, SystemTime};

/// Hybrid Logical Clock タイムスタンプ
/// 物理時刻 + 論理カウンタで構成
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct HybridTimestamp {
    /// 物理時刻（ミリ秒、Unix epoch からの経過）
    pub physical: u64,
    /// 論理カウンタ（同一物理時刻内での順序付け）
    pub logical: u32,
}

impl HybridTimestamp {
    /// 現在時刻から生成
    pub fn now() -> Self {
        let physical = SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;
        Self { physical, logical: 0 }
    }

    /// 次のタイムスタンプを生成（単調増加保証）
    pub fn next(&self) -> Self {
        Self {
            physical: self.physical,
            logical: self.logical + 1,
        }
    }

    /// リモートタイムスタンプとマージ（HLC update rule）
    pub fn update(&mut self, remote: HybridTimestamp) {
        let now = Self::now();
        if remote.physical > self.physical && remote.physical > now.physical {
            self.physical = remote.physical;
            self.logical = remote.logical + 1;
        } else if remote.physical == self.physical {
            self.logical = self.logical.max(remote.logical) + 1;
        } else if now.physical > self.physical {
            self.physical = now.physical;
            self.logical = 0;
        } else {
            self.logical += 1;
        }
    }
}

/// Timestamp Oracle 設定
pub struct TsoConfig {
    /// バッチサイズ（一度に割り当てるタイムスタンプ数）
    pub batch_size: u32,
    /// 事前割り当て閾値（残りがこの数以下で次のバッチを取得）
    pub prefetch_threshold: u32,
    /// タイムスタンプ有効期限（リーダー切り替え時の安全マージン）
    pub timestamp_ttl: Duration,
}

impl Default for TsoConfig {
    fn default() -> Self {
        Self {
            batch_size: 10000,
            prefetch_threshold: 1000,
            timestamp_ttl: Duration::from_secs(3),
        }
    }
}

/// Timestamp Oracle サービス
/// Raft リーダーが運営し、クラスタ全体に一貫したタイムスタンプを提供
pub struct TimestampOracle {
    /// 現在のHLCタイムスタンプ
    current: HybridTimestamp,
    /// 設定
    config: TsoConfig,
    /// 割り当て済み上限（この値まで発行可能）
    allocated_until: HybridTimestamp,
    /// Raft グループ（永続化用）
    raft_node: Arc<RaftNode<TsoStateMachine, WalRaftStorage>>,
}

impl TimestampOracle {
    /// タイムスタンプを取得（クライアント向け）
    /// リーダーでない場合はリーダーにリダイレクト
    pub async fn get_timestamp(&self) -> Result<HybridTimestamp> {
        if !self.raft_node.is_leader() {
            return Err(Error::NotLeader(self.raft_node.leader_id()));
        }
        self.allocate_one().await
    }

    /// バッチでタイムスタンプを取得（高スループット向け）
    pub async fn get_timestamps(&self, count: u32) -> Result<(HybridTimestamp, HybridTimestamp)> {
        if !self.raft_node.is_leader() {
            return Err(Error::NotLeader(self.raft_node.leader_id()));
        }
        self.allocate_batch(count).await
    }

    /// 内部: 単一タイムスタンプ割り当て
    async fn allocate_one(&self) -> Result<HybridTimestamp> {
        // 事前割り当て範囲内であればローカルで発行
        if self.current < self.allocated_until {
            let ts = self.current;
            self.current = self.current.next();
            return Ok(ts);
        }
        // 範囲を超えた場合は Raft 経由で新しい範囲を確保
        self.extend_allocation().await?;
        self.allocate_one().await
    }

    /// 内部: Raft 経由で割り当て範囲を拡張
    async fn extend_allocation(&self) -> Result<()> {
        let command = TsoCommand::ExtendAllocation {
            batch_size: self.config.batch_size,
        };
        self.raft_node.propose(command).await?;
        Ok(())
    }
}

/// TSO 用ステートマシン
pub struct TsoStateMachine {
    /// 最後に割り当てたタイムスタンプ
    last_allocated: HybridTimestamp,
}

/// TSO コマンド
#[derive(Clone, Serialize, Deserialize)]
pub enum TsoCommand {
    /// 割り当て範囲を拡張
    ExtendAllocation { batch_size: u32 },
    /// リーダー切り替え時の同期
    SyncTimestamp { timestamp: HybridTimestamp },
}

/// TSO レスポンス
#[derive(Clone, Serialize, Deserialize)]
pub struct TsoResponse {
    /// 新しい割り当て開始
    pub start: HybridTimestamp,
    /// 新しい割り当て終了
    pub end: HybridTimestamp,
}

#[async_trait]
impl StateMachine for TsoStateMachine {
    type Command = TsoCommand;
    type Response = TsoResponse;
    type Snapshot = HybridTimestamp;

    async fn apply(&mut self, _index: LogIndex, command: Self::Command) -> Result<Self::Response> {
        match command {
            TsoCommand::ExtendAllocation { batch_size } => {
                let start = self.last_allocated.next();
                let end = HybridTimestamp {
                    physical: start.physical,
                    logical: start.logical + batch_size,
                };
                self.last_allocated = end;
                Ok(TsoResponse { start, end })
            }
            TsoCommand::SyncTimestamp { timestamp } => {
                if timestamp > self.last_allocated {
                    self.last_allocated = timestamp;
                }
                Ok(TsoResponse {
                    start: self.last_allocated,
                    end: self.last_allocated,
                })
            }
        }
    }

    async fn snapshot(&self) -> Result<Self::Snapshot> {
        Ok(self.last_allocated)
    }

    async fn restore(&mut self, snapshot: Self::Snapshot) -> Result<()> {
        self.last_allocated = snapshot;
        Ok(())
    }
}

/// TSO クライアント（アプリケーション側で使用）
pub struct TsoClient {
    /// キャッシュされたタイムスタンプ範囲
    cached_start: HybridTimestamp,
    cached_end: HybridTimestamp,
    /// Chirps 経由での TSO アクセス
    transport: Arc<ChirpsTransport>,
    /// 現在の TSO リーダー
    tso_leader: Option<NodeId>,
}

impl TsoClient {
    /// タイムスタンプを取得（ローカルキャッシュ優先）
    pub async fn get_timestamp(&mut self) -> Result<HybridTimestamp> {
        if self.cached_start < self.cached_end {
            let ts = self.cached_start;
            self.cached_start = self.cached_start.next();
            return Ok(ts);
        }
        // キャッシュ切れ: TSO から新しいバッチを取得
        self.refill_cache().await?;
        self.get_timestamp().await
    }

    /// 内部: TSO からバッチ取得
    async fn refill_cache(&mut self) -> Result<()> {
        let response = self.request_timestamps(100).await?;
        self.cached_start = response.start;
        self.cached_end = response.end;
        Ok(())
    }
}
```

**Raft TSO の特徴**:
1. **Raft ベース**: リーダーがタイムスタンプを発行、障害時は新リーダーが引き継ぎ
2. **HLC**: 物理時刻 + 論理カウンタで単調増加を保証
3. **バッチ割り当て**: 高スループットのためローカルキャッシュを活用
4. **クロックスキュー耐性**: HLC の update rule で収束

#### 3.4.2 Gossip HLC (インフラ層)

`chirps-gossip-swim` モジュールで提供。ノード間イベントの因果順序付けに使用。
各ノードがローカルでタイムスタンプを発行し、Gossipメッセージ交換で収束。

```rust
//! chirps-gossip-swim モジュールで提供
//! インフラ層（SWIM、Gossip）が内部で使用

/// ノードローカルの HLC
/// 各ノードが独立して管理し、メッセージ交換で同期
pub struct LocalHlc {
    /// 現在のタイムスタンプ
    current: HybridTimestamp,
    /// 最大許容クロックスキュー
    max_clock_skew: Duration,
}

impl LocalHlc {
    /// 新しいローカルイベント用タイムスタンプを発行
    pub fn tick(&mut self) -> HybridTimestamp {
        let now = HybridTimestamp::now();
        if now.physical > self.current.physical {
            self.current = now;
        } else {
            self.current = self.current.next();
        }
        self.current
    }

    /// リモートからのメッセージを受信した際に更新
    pub fn receive(&mut self, remote: HybridTimestamp) -> Result<HybridTimestamp> {
        let now = HybridTimestamp::now();

        // クロックスキューチェック
        let skew = remote.physical.saturating_sub(now.physical);
        if skew > self.max_clock_skew.as_millis() as u64 {
            return Err(Error::ClockSkewTooLarge(skew));
        }

        self.current.update(remote);
        Ok(self.current)
    }
}

/// SWIM メンバーシップイベント（HLC付き）
pub struct MembershipEvent {
    pub event_type: MembershipEventType,
    pub node_id: NodeId,
    pub timestamp: HybridTimestamp,  // LocalHlc から発行
    pub incarnation: u64,
}

pub enum MembershipEventType {
    Joined,
    Left,
    Failed,
    Suspect,
}
```

**Gossip HLC の特徴**:
1. **分散発行**: 各ノードがローカルで発行、リーダー不要
2. **低レイテンシ**: ネットワーク往復なし
3. **因果順序**: 同一ノードのイベントは厳密順序、異ノード間は因果順序
4. **Gossip収束**: メッセージ交換でクロックが徐々に同期

**使い分けガイド**:

| ユースケース | 推奨方式 | 理由 |
|-------------|---------|------|
| トランザクション開始時刻 | Raft TSO | 厳密な単調増加が必要 |
| MVCC read timestamp | Raft TSO | 一貫したスナップショット |
| SWIMメンバーシップ変更 | Gossip HLC | 因果順序で十分、低レイテンシ優先 |
| Gossipメッセージ順序 | Gossip HLC | 分散発行、高スループット |
| フェデレーション間同期 | Raft TSO | クラスタ間一貫性が必要 |

---

## 4. 製品別実装例

### 4.1 Alopex DB での利用

```rust
//! Alopex DB での Raft 利用例

use alopex_chirps::raft::{StateMachine, RaftStorage, RaftNode};

/// Range のコマンド
#[derive(Clone, Serialize, Deserialize)]
pub enum RangeCommand {
    Put { key: Vec<u8>, value: Vec<u8> },
    Delete { key: Vec<u8> },
    Split { split_key: Vec<u8> },
    Merge { target_range_id: RangeId },
}

/// Range のステートマシン
pub struct RangeStateMachine {
    range_id: RangeId,
    storage: RangeStorage,  // LSM-Tree based
}

#[async_trait]
impl StateMachine for RangeStateMachine {
    type Command = RangeCommand;
    type Response = RangeResponse;
    type Snapshot = RangeSnapshot;

    async fn apply(&mut self, index: LogIndex, command: Self::Command) -> Result<Self::Response> {
        match command {
            RangeCommand::Put { key, value } => {
                self.storage.put(&key, &value).await?;
                Ok(RangeResponse::Ok)
            }
            RangeCommand::Delete { key } => {
                self.storage.delete(&key).await?;
                Ok(RangeResponse::Ok)
            }
            RangeCommand::Split { split_key } => {
                let new_range = self.storage.split(&split_key).await?;
                Ok(RangeResponse::Split { new_range_id: new_range.id })
            }
            RangeCommand::Merge { target_range_id } => {
                self.storage.merge(target_range_id).await?;
                Ok(RangeResponse::Ok)
            }
        }
    }

    async fn snapshot(&self) -> Result<Self::Snapshot> {
        self.storage.create_snapshot().await
    }

    async fn restore(&mut self, snapshot: Self::Snapshot) -> Result<()> {
        self.storage.restore_from_snapshot(snapshot).await
    }
}

/// Alopex DB クラスタノード
pub struct AlopexClusterNode {
    multi_raft: MultiRaftManager<RangeStateMachine, WalRaftStorage>,
    range_manager: RangeManager,
}

impl AlopexClusterNode {
    /// 書き込みリクエスト処理
    pub async fn write(&self, key: &[u8], value: &[u8]) -> Result<()> {
        // 1. キーから Range を特定
        let range_id = self.range_manager.get_range_for_key(key)?;

        // 2. Raft グループを取得
        let raft_node = self.multi_raft.get_group(range_id)
            .ok_or(Error::RangeNotFound)?;

        // 3. コマンドを提案
        let command = RangeCommand::Put {
            key: key.to_vec(),
            value: value.to_vec(),
        };
        raft_node.propose(command).await?;

        Ok(())
    }
}
```

### 4.2 Alopex Skulk での利用

```rust
//! Alopex Skulk での Raft 利用例

use alopex_chirps::raft::{StateMachine, RaftStorage, RaftNode};

/// Shard のコマンド
#[derive(Clone, Serialize, Deserialize)]
pub enum ShardCommand {
    WritePoints { points: Vec<DataPoint> },
    DeleteSeries { series_id: SeriesId },
    Downsample { resolution: Duration },
    CompactPartition { partition: TimePartition },
}

/// Shard のステートマシン
pub struct ShardStateMachine {
    shard_id: ShardId,
    tsm_storage: TSMStorage,
}

#[async_trait]
impl StateMachine for ShardStateMachine {
    type Command = ShardCommand;
    type Response = ShardResponse;
    type Snapshot = ShardSnapshot;

    async fn apply(&mut self, index: LogIndex, command: Self::Command) -> Result<Self::Response> {
        match command {
            ShardCommand::WritePoints { points } => {
                let written = self.tsm_storage.write_batch(&points).await?;
                Ok(ShardResponse::Written { count: written })
            }
            ShardCommand::DeleteSeries { series_id } => {
                self.tsm_storage.delete_series(series_id).await?;
                Ok(ShardResponse::Ok)
            }
            ShardCommand::Downsample { resolution } => {
                self.tsm_storage.downsample(resolution).await?;
                Ok(ShardResponse::Ok)
            }
            ShardCommand::CompactPartition { partition } => {
                self.tsm_storage.compact_partition(&partition).await?;
                Ok(ShardResponse::Ok)
            }
        }
    }

    async fn snapshot(&self) -> Result<Self::Snapshot> {
        self.tsm_storage.create_snapshot().await
    }

    async fn restore(&mut self, snapshot: Self::Snapshot) -> Result<()> {
        self.tsm_storage.restore_from_snapshot(snapshot).await
    }
}

/// Skulk クラスタノード
pub struct SkulkClusterNode {
    multi_raft: MultiRaftManager<ShardStateMachine, TSMRaftStorage>,
    shard_router: ShardRouter,
}

impl SkulkClusterNode {
    /// メトリクス書き込み
    pub async fn write_metrics(&self, points: Vec<DataPoint>) -> Result<()> {
        // 1. メトリクスをシャードごとにグループ化
        let grouped = self.shard_router.group_by_shard(&points);

        // 2. 各シャードに並列で書き込み
        let futures: Vec<_> = grouped.into_iter().map(|(shard_id, shard_points)| {
            self.write_to_shard(shard_id, shard_points)
        }).collect();

        futures::future::try_join_all(futures).await?;
        Ok(())
    }

    async fn write_to_shard(&self, shard_id: ShardId, points: Vec<DataPoint>) -> Result<()> {
        let raft_node = self.multi_raft.get_group(shard_id)
            .ok_or(Error::ShardNotFound)?;

        let command = ShardCommand::WritePoints { points };
        raft_node.propose(command).await?;
        Ok(())
    }
}
```

---

## 5. 変更後のクレート依存関係

> **注**: 現行の2ワークスペース構成を反映した依存関係図

```
現行（2025-11-29時点）:
┌──────────────────────────────────────────────────────────────┐
│                     alopex/ workspace                         │
│  ┌────────────────────┐     ┌────────────────────┐           │
│  │   alopex-db        │     │   alopex-skulk     │           │
│  │ ┌────────────────┐ │     │ ┌────────────────┐ │           │
│  │ │ (未実装)       │ │     │ │ (未実装)       │ │           │
│  │ └────────────────┘ │     │ └────────────────┘ │           │
│  └─────────┬──────────┘     └─────────┬──────────┘           │
│            │                          │                       │
│            ▼                          ▼                       │
│  ┌─────────────────────────────────────────────────┐         │
│  │               alopex-core                        │         │
│  │  (WAL, KV, Vector, Columnar, etc.)              │         │
│  └─────────────────────────────────────────────────┘         │
└──────────────────────────────────────────────────────────────┘
                    ↑ 依存関係なし ↓
┌──────────────────────────────────────────────────────────────┐
│                     chirps/ workspace                         │
│  ┌─────────────────────────────────────────────────┐         │
│  │               alopex-chirps                      │         │
│  │  (QUIC, SWIM, MessageBackend)                   │         │
│  └─────────────────────────────────────────────────┘         │
└──────────────────────────────────────────────────────────────┘

Phase 1（Option B: path依存）:
┌──────────────────────────────────────────────────────────────┐
│                     alopex/ workspace                         │
│  ┌────────────────────┐     ┌────────────────────┐           │
│  │   alopex-db        │     │   alopex-skulk     │           │
│  │ ┌────────────────┐ │     │ ┌────────────────┐ │           │
│  │ │ alopex-cluster │ │     │ │ skulk-cluster  │ │           │
│  │ │ RangeStateMachine│ │    │ │ ShardStateMachine│ │          │
│  │ └────────────────┘ │     │ └────────────────┘ │           │
│  └─────────┬──────────┘     └─────────┬──────────┘           │
│            │                          │                       │
│            ▼                          ▼                       │
│  ┌─────────────────────────────────────────────────┐         │
│  │               alopex-core                        │ ◄───┐   │
│  │  (WAL, KV, Vector, Columnar - 共通ストレージ)    │     │   │
│  └─────────────────────────────────────────────────┘     │   │
└──────────────────────────────────────────────────────────│───┘
             │ crates.io 依存 (alopex-chirps)              │
             ▼                                             │
┌──────────────────────────────────────────────────────────│───┐
│                     chirps/ workspace                    │   │
│  ┌─────────────────────────────────────────────────┐     │   │
│  │               alopex-chirps                      │     │   │
│  │ ┌─────────────────────────────────────────────┐ │     │   │
│  │ │ chirps-raft (新規)                          │ │     │   │
│  │ │  - RaftNode, MultiRaftManager               │ │     │   │
│  │ │  - StateMachine/RaftStorage traits          │ │     │   │
│  │ │  - WalRaftStorage ─────────────────────────────────┘   │
│  │ │      (alopex-core::log::Wal* を利用)        │ │         │
│  │ └─────────────────────────────────────────────┘ │         │
│  │ ┌─────────────────────────────────────────────┐ │         │
│  │ │ chirps-transport-quic                       │ │         │
│  │ │ chirps-gossip-swim                          │ │         │
│  │ │ chirps-wire                                 │ │         │
│  │ └─────────────────────────────────────────────┘ │         │
│  └─────────────────────────────────────────────────┘         │
│                                                              │
│  Cargo.toml:                                                 │
│    alopex-core = { path = "../alopex/crates/alopex-core" }   │
└──────────────────────────────────────────────────────────────┘

Phase 2（Option A: crates.io公開）:
  1. alopex-core v0.1.0 を crates.io に公開
  2. chirps/Cargo.toml を更新:
     alopex-core = "0.1"  # path依存からcrates.io依存に変更
  3. 外部プロジェクトからも alopex-core を利用可能に
```

---

## 6. Chirps バージョン対応表

| Chirps Version | 機能 | Alopex DB | Alopex Skulk |
|----------------|------|-----------|--------------|
| v0.3 | Gossip, SWIM, Membership | v0.3+ | v0.1+ |
| v0.4 | Message Profiles | v0.4+ | v0.2+ |
| v0.5 | **Raft Consensus API** | v0.5+ | v0.3+ |
| v0.6 | Multi-Raft, Snapshot Transfer | v0.6+ | v0.4+ |
| v0.7 | Federation Gateway | v1.0+ | v0.5+ |
| v1.0 | Production Ready Raft | v1.0+ | v1.0+ |

---

## 7. 移行計画

### 7.1 フェーズ1: Chirps Raft Core (v0.5)

**期間**: 2週間

**タスク**:
1. `alopex-chirps` に Raft モジュール追加
2. `StateMachine`, `RaftStorage` trait 定義
3. `RaftNode` 基本実装 (openraft ラップ)
4. 単体テスト・ベンチマーク

**成果物**:
- `alopex-chirps::raft` モジュール
- Raft trait 定義
- 基本動作テスト

### 7.2 フェーズ2: alopex-core連携 & WalRaftStorage (v0.5後半)

**タスク**:
1. `chirps/Cargo.toml` に path 依存追加
2. `WalRaftStorage` 実装 (alopex-core::log::Wal* を利用)
3. 統合テスト

**成果物**:
- chirps → alopex-core 依存確立
- WAL ベースの Raft ログ永続化

### 7.3 フェーズ3: Multi-Raft & Snapshot (v0.6)

**タスク**:
1. `MultiRaftManager` 実装
2. スナップショット転送実装
3. 統合テスト

**成果物**:
- Multi-Raft グループ管理
- スナップショット機能

### 7.4 フェーズ4: alopex-core crates.io公開 (v0.6前後)

**タスク**:
1. `alopex-core` API の安定化レビュー
2. README, CHANGELOG, LICENSE 整備
3. `crates.io` に公開
4. `chirps/Cargo.toml` を crates.io 依存に切り替え

**成果物**:
- `alopex-core` v0.1.0 公開
- Option B → Option A 移行完了

### 7.5 フェーズ5: Alopex DB 移行

**タスク**:
1. `RangeStateMachine` 実装
2. 既存 Raft コード削除
3. クラスタテスト

**成果物**:
- Alopex DB Chirps Raft 統合

### 7.6 フェーズ6: Alopex Skulk 移行

**タスク**:
1. `ShardStateMachine` 実装
2. 既存 Raft コード削除
3. クラスタテスト

**成果物**:
- Alopex Skulk Chirps Raft 統合

---

## 8. リスクと対策

### 8.1 性能リスク

**リスク**: 抽象化によるオーバーヘッド

**対策**:
- trait object ではなく generics を使用
- hot path のインライン化
- ベンチマークによる継続的監視

### 8.2 互換性リスク

**リスク**: 既存クラスタとの互換性

**対策**:
- Raft プロトコルバージョンを明示
- ローリングアップデート手順を文書化
- 互換性テストスイート

### 8.3 複雑性リスク

**リスク**: Chirps の責務増大

**対策**:
- モジュール単位での分離
- feature flag による機能切り替え
- ドキュメント整備

---

## 9. 関連ドキュメント

- [technical-spec.md](technical-spec.md) - Alopex DB 技術仕様
- [technical-spec-tsdb.md](technical-spec-tsdb.md) - Alopex Skulk 技術仕様
- [design-spec.md](design-spec.md) - Alopex DB 方式設計
- [design-spec-tsdb.md](design-spec-tsdb.md) - Alopex Skulk 方式設計
- [tasks.md](tasks.md) - 開発タスク一覧

---

## 10. 承認

| 役割 | 名前 | 日付 | 承認 |
|------|------|------|------|
| 設計者 | | | |
| レビュアー | | | |
| 承認者 | | | |

---

## 付録A: 分散合意アルゴリズムと競合解決方式の技術ノート

（Raft / Multi-Raft / EPaxos / CRDT までの全体整理）

### A.1 問題設定：何を効率化したいのか

分散システムの「競合」はレイヤーごとに性質が異なるため、要求ごとに適切なアルゴリズムが変わる。

#### A.1.1 競合レイヤー

1. **レプリカ間の合意競合（リーダー選出・ログ分岐）**
   * 対象：Raft、Paxos、EPaxos

2. **同一キーへの同時書き込み（最終整合 or 強整合）**
   * 対象：CRDT、LWW、アプリケーションレベルのマージ

3. **トランザクション内の競合（ロック、MVCC、OCC）**
   * 対象：DB 内部機構

本議論は主に **1 と 2** が中心。

---

### A.2 高性能 Raft 実装の現状

#### A.2.1 現役で使われている主要実装

| 実装 | 言語 | 採用プロダクト | 特徴 |
|------|------|----------------|------|
| etcd/raft | Go | Kubernetes etcd | パイプライニング、バッチング最適化が充実 |
| Hashicorp Raft | Go | Consul, Nomad | シンプルで扱いやすい |
| Dragonboat | Go | - | 高スループット向け「マルチグループ Raft」設計 |
| raft-rs | Rust | TiKV | Rust 実装では最も成熟 |
| openraft | Rust | - | モダンなRust Raft実装、本提案で採用 |

#### A.2.2 Raft の高速化テクニック

* **ログ／ネットワークのバッチング**
  複数のリクエストをまとめて fsync / AppendEntries。

* **パイプライニング**
  ACK を待たず次のレプリケーションを送信。

* **ログ圧縮（スナップショット）**
  古いログの蓄積による I/O 劣化を抑制。

* **Multi-Raft（シャーディング）**
  キー空間をレンジ単位で分割し、Raft グループを多数動かす。
  TiKV / CockroachDB が成功事例。

**結論**: Raft の限界は「単一リーダーのボトルネック」に集約される。

---

### A.3 Raft を超えるスループットを狙う合意アルゴリズム

#### A.3.1 Multi-Paxos

* 安定リーダーがいる最適化された Paxos
* Raft と構造が近いが、Raft より実装が複雑

#### A.3.2 EPaxos（Egalitarian Paxos）

* **リーダーレス合意**
* 特徴：
  * どのレプリカでも書き込み開始できる
  * 高コンカレンシー、依存関係が少ないワークロードで性能が最大化
  * Geo 分散に強い
* トレードオフ：
  * 実装難度が高い
  * メタデータ管理が複雑
  * OSS エコシステムは Raft ほど成熟していない

**結論**: EPaxos は「特定のホットシャード」にのみ適用するハイブリッド構成が現実的。

---

### A.4 競合を「そもそも発生させない」アプローチ：CRDT

#### A.4.1 特徴

* 各レプリカがローカルで更新可能
* 可換／結合的／冪等なマージ関数を持つ
* 順不同で伝播しても最終状態が一致する

#### A.4.2 代表種類

| CRDT Type | 用途 | 特性 |
|-----------|------|------|
| G-Counter | 加算カウンタ | 増加のみ |
| PN-Counter | 加減算カウンタ | 増減可能 |
| OR-Set | 追加/削除セット | Observed-Remove |
| LWW-Register | 最終書き込み優先 | タイムスタンプベース |
| Nested/Composite | 複合データ構造 | 組み合わせ可能 |

#### A.4.3 利点と制約

* **利点**: レイテンシ最小、スループット最大、ネットワーク分断中も操作可能
* **制約**:
  * 強整合の制約（ユニーク制約、残高制約）は苦手
  * データモデル設計のコストが高い

**結論**: 「最終的整合で問題ないデータ」だけを CRDT 化するのが合理的。

---

### A.5 Alopex への適用指針

#### A.5.1 強整合が必須の領域

| 対象 | 一貫性モデル | 実装方式 |
|------|-------------|---------|
| クラスタメタデータ | 強整合 | 単一 Raft グループ |
| スキーマ管理 | 強整合 | 単一 Raft グループ |
| シャード配置 | 強整合 | 単一 Raft グループ |

⇒ **単一〜少数 Raft グループ**

#### A.5.2 データパス（key-value / document / range）

| データタイプ | 一貫性モデル | 実装方式 |
|--------------|-------------|---------|
| 強整合テーブル | 強整合 | Multi-Raft（シャードごとに 1 Raft グループ） |
| 最終整合テーブル | 最終整合 | CRDT ベースのレプリケーション |

#### A.5.3 ホットシャード最適化

1. Multi-Raft の上で最適化（バッチ・パイプライン・リーダー最適配置など）
2. それでも足りなければ ⇒ **EPaxos / 特殊 Paxos を部分的に導入**

#### A.5.4 一貫性レイヤーの構成

```
┌─────────────────────────────────────────────────────────────┐
│ 1. メタデータ層: 強整合（Raft）                              │
│    - クラスタ構成、スキーマ、シャード配置                    │
├─────────────────────────────────────────────────────────────┤
│ 2. トランザクション層: MVCC / OCC                           │
│    - DB 内部のロック管理                                    │
├─────────────────────────────────────────────────────────────┤
│ 3. データパス層: Raft or CRDT（テーブルごとに選択）          │
│    - 強整合テーブル → Multi-Raft                            │
│    - 最終整合テーブル → CRDT                                 │
├─────────────────────────────────────────────────────────────┤
│ 4. 高並列ワークロード: EPaxos（必要な箇所のみ）              │
│    - ホットシャード、Geo分散シナリオ                         │
└─────────────────────────────────────────────────────────────┘
```

---

### A.6 最適化の優先順位（実践的）

| 優先度 | 最適化項目 | 効果 | 実装コスト |
|--------|-----------|------|-----------|
| 1 | Raft を正しく実装し、バッチ・パイプライニングを有効化 | 高 | 低 |
| 2 | マルチ Raft（シャーディング）構造にする | 高 | 中 |
| 3 | CRDT で逃せる書き込みは Raft から逃がす | 中 | 中 |
| 4 | ホットシャードが残る場合のみ EPaxos を検討 | 中 | 高 |

この順番がもっとも効果が高く、実装負荷を抑えられる。

---

### A.7 まとめ（全体の要点）

1. **Raft は実装容易で信頼性が高く、最初に選ぶべき合意アルゴリズム。**

2. **スループットは Multi-Raft（シャーディング）で水平に伸ばすのが王道。**

3. **最終的整合でよいデータは CRDT を使って Raft の負荷を減らす。**

4. **さらに性能が必要なら、EPaxos などのリーダーレス合意を部分導入する。**

5. **要件に応じて複数の一貫性モデルを併用するハイブリッド構成がベスト。**

---

### A.8 参考文献

* [Raft Consensus Algorithm](https://raft.github.io/)
* [In Search of an Understandable Consensus Algorithm (Raft Paper)](https://raft.github.io/raft.pdf)
* [EPaxos: There Is More Consensus in Egalitarian Parliaments](https://www.cs.cmu.edu/~dga/papers/epaxos-sosp2013.pdf)
* [CRDTs: Consistency without consensus](https://crdt.tech/)
* [TiKV: A Distributed Transactional Key-Value Database](https://tikv.org/)
* [CockroachDB Architecture](https://www.cockroachlabs.com/docs/)
