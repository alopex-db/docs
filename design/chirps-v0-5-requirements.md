# Chirps v0.5 - Raft Consensus API Requirements

## Introduction

Chirps v0.5は、Alopex DBおよびAlopex Skulkの分散合意基盤として、Raft Consensus APIを提供するマイルストーンです。v0.4で整備したRaft-ready Transportの上に、StateMachine/RaftStorage traitと基本的なRaftNode実装を構築します。

**主な機能**:
- **StateMachine trait**: アプリケーション固有のステートマシンインターフェース
- **RaftStorage trait**: Raftログとスナップショットの永続化インターフェース
- **WalRaftStorage**: alopex-core WALを利用したRaftStorage実装
- **RaftNode**: 単一Raftグループの管理と操作API

### Scope Clarification

**v0.5 スコープ内**:
- StateMachine / RaftStorage trait定義
- WalRaftStorage実装（alopex-core WAL連携）
- RaftNode基本実装（openraftベース）
- 単一Raftグループの操作API
- メンバーシップ変更（Joint Consensus対応）
- 基本的なスナップショット生成/復元

**v0.5 スコープ外（将来バージョン）**:
- MultiRaftManager（v0.6）
- Timestamp Oracle / TSO（v0.6）
- Gossip HLC（v0.6）
- スナップショット転送の最適化（v0.6）
- Durableプロファイル連携（v0.7）

### Compatibility Model

| 互換性の種類 | v0.5での対応 |
|-------------|-------------|
| **APIシグネチャ互換** | 維持 ― v0.4のStreamKind::Raft/RaftSnapshotをそのまま使用 |
| **クロスバージョン互換** | 非対応 ― v0.4ノードとv0.5ノードの混在クラスタは拒否 |

## Alignment with Product Vision

本機能はAlopex DBの製品ビジョン「Silent. Adaptive. Unbreakable.」を支える基盤として、以下の目標に貢献します:

- **分散合意基盤**: Alopex DB / Skulk共通のRaft実装による保守性向上
- **高可用性**: リーダー選出とログ複製による障害耐性
- **拡張性**: StateMachine traitによるアプリケーション固有ロジックの分離

設計ドキュメント（`design/chirps-raft-integration-proposal.md`）で定義されているChirps Raft統合の要件を実装します。現行の公開入口は独立した crate ではなく、`alopex-chirps::raft` です。storage trait は `alopex-chirps-raft-storage` が提供します。

## Requirements

### Requirement 1: StateMachine Trait

**User Story:** 分散アプリケーション開発者として、Raftコンセンサスで保護されたステートマシンを実装したい。StateMachine traitを実装することで、Raft層から独立してアプリケーションロジックを定義できる。

#### Acceptance Criteria

1. WHEN StateMachine traitを実装したアプリケーションがRaftNodeに登録される THEN システムSHALL コミットされたエントリを順番に`apply()`メソッドで適用する
2. WHEN `apply()`メソッドが呼び出される THEN システムSHALL ログインデックスとコマンドを引数として渡す
3. WHEN スナップショット生成が要求される THEN システムSHALL `snapshot()`メソッドを呼び出し、現在状態のシリアライズ可能な表現を取得する
4. WHEN スナップショットから復元が要求される THEN システムSHALL `restore()`メソッドを呼び出し、指定されたスナップショットから状態を復元する
5. WHEN StateMachine traitが定義される THEN Command/Response型は`Send + Sync + Clone + Serialize + DeserializeOwned`を要求し、snapshot は非同期 reader (`Box<dyn AsyncSnapshotData>`) として受け渡す

**Trait定義（v0.6現行契約）**:
```rust
use alopex_chirps_raft_storage::traits::{AsyncSnapshotData, StateMachineResult};
use alopex_chirps_raft_storage::types::{ChirpsNodeId, LogId};

#[async_trait]
pub trait StateMachine: Send + Sync + 'static {
    type Command: Send + Sync + Clone + serde::Serialize + serde::de::DeserializeOwned;
    type Response: Send + Sync + Clone + serde::Serialize + serde::de::DeserializeOwned;

    async fn apply(
        &mut self,
        log_id: LogId<ChirpsNodeId>,
        command: Self::Command,
    ) -> StateMachineResult<Self::Response>;
    async fn snapshot(&self) -> StateMachineResult<Box<dyn AsyncSnapshotData>>;
    async fn restore(
        &mut self,
        snapshot: Box<dyn AsyncSnapshotData>,
    ) -> StateMachineResult<()>;
}
```

`Snapshot` associated type を追加する互換 facade は v0.7 以降の計画であり、v0.6
では導入しない。

### Requirement 2: RaftStorage Trait

**User Story:** 分散アプリケーション開発者として、Raftログとスナップショットの永続化方式を選択可能にしたい。RaftStorage traitを実装することで、様々なストレージバックエンド（WAL、RocksDB、メモリ等）を使用できる。

#### Acceptance Criteria

1. WHEN ログエントリが追加される THEN システムSHALL `append(entries, callback)` でバッチを受け取り、flush 完了を `LogFlushed` callback へ通知する
2. WHEN ログエントリが要求される THEN システムSHALL `try_get_log_entries(range)` で `RangeBounds<u64>` の範囲を取得する
3. WHEN ログの競合またはパージが要求される THEN システムSHALL `truncate(log_id)` または `purge(log_id)` を使用する
4. WHEN vote または適用済み状態が永続化される THEN システムSHALL `save_vote()`/`read_vote()` と `applied_state()` を使用する（v0.5設計の HardState 型は公開しない）
5. WHEN スナップショットの受信・適用・取得が要求される THEN システムSHALL `begin_receiving_snapshot()`、`install_snapshot()`、`get_current_snapshot()`、`get_snapshot_builder()` を使用する
6. WHEN `append()` の callback が flush 完了を通知する THEN エントリは storage 実装が定める fsync 相当の耐久性境界を越えている

`append_entries`、`get_entries`、`truncate_before`、`save_hard_state`、`load_snapshot`
は v0.5 設計上の移行用語であり、v0.6 の追加メソッドではない。現行 trait は
openraft v0.9.17 storage-v2 の形状である。

**Trait定義（v0.6現行契約の要約）**:
```rust
#[async_trait]
pub trait RaftStorage<C: openraft::RaftTypeConfig>: Send + Sync + 'static {
    type LogReader: openraft::storage::RaftLogReader<C>;
    type SnapshotBuilder: openraft::storage::RaftSnapshotBuilder<C>;

    async fn get_log_state(&mut self) -> Result<openraft::LogState<C>, openraft::StorageError<C::NodeId>>;
    async fn try_get_log_entries<RB>(&mut self, range: RB) -> Result<Vec<C::Entry>, openraft::StorageError<C::NodeId>>
    where RB: RangeBounds<u64> + Clone + Debug + openraft::OptionalSend;
    async fn append<I>(&mut self, entries: I, callback: openraft::storage::LogFlushed<C>)
    where I: IntoIterator<Item = C::Entry> + Send, I::IntoIter: Send;
    async fn truncate(&mut self, log_id: openraft::LogId<C::NodeId>) -> Result<(), openraft::StorageError<C::NodeId>>;
    async fn purge(&mut self, log_id: openraft::LogId<C::NodeId>) -> Result<(), openraft::StorageError<C::NodeId>>;
    async fn applied_state(&mut self) -> Result<(Option<openraft::LogId<C::NodeId>>, openraft::StoredMembership<C::NodeId, C::Node>), openraft::StorageError<C::NodeId>>;
    async fn apply<I>(&mut self, entries: I) -> Result<Vec<C::R>, openraft::StorageError<C::NodeId>>
    where I: IntoIterator<Item = C::Entry> + Send, I::IntoIter: Send;
    async fn save_vote(&mut self, vote: &openraft::Vote<C::NodeId>) -> Result<(), openraft::StorageError<C::NodeId>>;
    async fn read_vote(&mut self) -> Result<Option<openraft::Vote<C::NodeId>>, openraft::StorageError<C::NodeId>>;
    async fn begin_receiving_snapshot(&mut self) -> Result<Box<C::SnapshotData>, openraft::StorageError<C::NodeId>>;
    async fn install_snapshot(&mut self, meta: &openraft::SnapshotMeta<C::NodeId, C::Node>, snapshot: Box<C::SnapshotData>) -> Result<(), openraft::StorageError<C::NodeId>>;
    async fn get_current_snapshot(&mut self) -> Result<Option<openraft::Snapshot<C>>, openraft::StorageError<C::NodeId>>;
    fn set_purgeable_horizon(&mut self, horizon: Option<openraft::LogId<C::NodeId>>);
    async fn get_log_reader(&mut self) -> Self::LogReader;
    async fn get_snapshot_builder(&mut self) -> Self::SnapshotBuilder;
}
```

### Requirement 3: WalRaftStorage実装

**User Story:** Chirpsユーザーとして、alopex-core WALを利用したRaftログ永続化を使用したい。WALの高性能な追記書き込みとfsync保証を活用できる。

#### Acceptance Criteria

1. WHEN WalRaftStorageがインスタンス化される THEN システムSHALL alopex-core::log::WalWriterを内部で使用する
2. WHEN `append_entries()`が呼び出される THEN システムSHALL WALにエントリを追記し、fsyncで永続化する
3. WHEN `get_entries()`が呼び出される THEN システムSHALL WALおよびインメモリキャッシュからエントリを取得する
4. WHEN `truncate_before()`が呼び出される THEN システムSHALL 指定インデックス以前のWALセグメントを安全に削除する
5. WHEN HardStateが変更される THEN システムSHALL WALの専用セクションに永続化する
6. WHEN 再起動後にWalRaftStorageが初期化される THEN システムSHALL WALからHardStateとログエントリを復元する
7. WHEN スナップショットが保存される THEN システムSHALL `.alopex`ファイル形式のスナップショットセクションに保存する

**依存関係**:
- `alopex-core` への依存（Phase 1: path依存、Phase 2: crates.io公開後）
- technical-spec.md セクション1.3「Unified Data File Format」準拠

### Requirement 4: RaftNode基本実装

**User Story:** 分散アプリケーション開発者として、単一のRaftグループを管理するノードを操作したい。RaftNodeを通じて、コマンド提案、リーダー確認、メンバーシップ変更ができる。

#### Acceptance Criteria

1. WHEN RaftNodeが作成される THEN システムSHALL RaftConfig、StateMachine、RaftStorage、ChirpsTransportを受け取る
2. WHEN `start()`が呼び出される THEN システムSHALL Raftプロトコルを開始し、既存クラスタへの参加またはリーダー選出を行う
3. WHEN `propose(command)`がリーダーノードで呼び出される THEN システムSHALL コマンドをRaftログに追加し、過半数への複製後にコミットする
4. WHEN `propose(command)`がフォロワーノードで呼び出される THEN システムSHALL `Error::NotLeader(leader_id)`を返す
5. WHEN `leader_id()`が呼び出される THEN システムSHALL 現在認識しているリーダーのNodeIdを返す（不明な場合はNone）
6. WHEN `is_leader()`が呼び出される THEN システムSHALL 自身がリーダーかどうかをboolで返す
7. WHEN `change_membership(change)`が呼び出される THEN システムSHALL Joint Consensusプロトコルに従ってメンバーシップを変更する
8. WHEN `handle_message(msg)`が呼び出される THEN システムSHALL Chirps Transportから受信したRaftメッセージを処理する
9. WHEN `tick()`が定期的に呼び出される THEN システムSHALL タイムアウト検出、ハートビート送信等の時間ベース処理を実行する

**RaftConfig（参考）**:
```rust
pub struct RaftConfig {
    pub group_id: GroupId,
    pub node_id: NodeId,
    pub election_timeout_ms: u64,       // デフォルト: 1000
    pub heartbeat_interval_ms: u64,     // デフォルト: 200
    pub max_batch_size: usize,          // デフォルト: 64
    pub snapshot_threshold: u64,        // デフォルト: 10000
}
```

### Requirement 5: Chirps Transport統合

**User Story:** RaftNodeとして、Chirps Transportを通じて他のノードとRaftメッセージを交換したい。v0.4で追加されたStreamKind::Raft/RaftSnapshotと優先ストリームを活用できる。

#### Acceptance Criteria

1. WHEN Raftメッセージをリモートノードに送信する THEN システムSHALL `StreamKind::Raft`と`Priority::High`を使用する
2. WHEN Raftスナップショットを転送する THEN システムSHALL `StreamKind::RaftSnapshot`と`Priority::Normal`を使用する
3. WHEN Chirps Transportからメッセージを受信する THEN システムSHALL 適切なRaftNodeの`handle_message()`にルーティングする
4. WHEN リモートノードへの送信が失敗する THEN システムSHALL v0.4の再送バッファを活用して自動再送する
5. WHEN 複数のRaftグループが存在する場合（v0.6以降） THEN システムSHALL メッセージヘッダのgroup_idでルーティングする

### Requirement 6: メンバーシップ変更

**User Story:** クラスタ管理者として、Raftグループのメンバーを動的に追加・削除したい。Joint Consensusにより、設定変更中も可用性を維持できる。

#### Acceptance Criteria

1. WHEN 新規ノードをLearnerとして追加する THEN システムSHALL `add_learner(node_id, node_info)`でノンボーティングメンバーとして追加する
2. WHEN LearnerをVoterに昇格する THEN システムSHALL `change_membership()`でJoint Consensus経由で昇格する
3. WHEN Voterを削除する THEN システムSHALL `change_membership()`でJoint Consensus経由で削除する
4. WHEN メンバーシップ変更がコミットされる THEN システムSHALL ConfState（voters, learners）を更新する
5. WHEN Joint Consensus状態にある場合 THEN システムSHALL 新旧両方の設定の過半数からACKを要求する

**MembershipChange列挙（参考）**:
```rust
pub enum MembershipChange {
    AddLearner { node_id: NodeId, info: NodeInfo },
    AddVoter { node_id: NodeId },
    RemoveNode { node_id: NodeId },
    ReplaceVoter { old_node: NodeId, new_node: NodeId, new_info: NodeInfo },
}
```

### Requirement 7: スナップショット基本機能

**User Story:** RaftNodeとして、ログが肥大化した際にスナップショットを生成し、古いログを切り詰めたい。また、新規ノードにスナップショットを転送して高速に追いつかせたい。

#### Acceptance Criteria

1. WHEN ログエントリ数が`snapshot_threshold`を超える THEN システムSHALL 自動的にスナップショット生成をトリガーする
2. WHEN `trigger_snapshot()`が手動で呼び出される THEN システムSHALL StateMachineの`snapshot()`を呼び出してスナップショットを生成する
3. WHEN スナップショットが生成される THEN システムSHALL SnapshotMeta（last_included_index, last_included_term, conf_state）を含める
4. WHEN Followerがリーダーより大幅に遅れている THEN システムSHALL ログエントリの代わりにスナップショットを送信する
5. WHEN スナップショットを受信する THEN システムSHALL StateMachineの`restore()`を呼び出して状態を復元する
6. WHEN スナップショット適用が完了する THEN システムSHALL 適用済みインデックス以前のログを切り詰める

### Requirement 8: メトリクスとオブザーバビリティ

**User Story:** 運用担当者として、Raftグループの状態と性能を監視したい。

#### Acceptance Criteria

1. WHEN メトリクスAPIが呼び出される THEN システムSHALL 以下のメトリクスを返す:
   - Raftステート（`raft_state`: Leader/Follower/Candidate/Learner）
   - 現在のterm（`raft_term`）
   - コミット済みインデックス（`raft_commit_index`）
   - 適用済みインデックス（`raft_applied_index`）
   - 最終ログインデックス（`raft_last_log_index`）
   - リーダーID（`raft_leader_id`）
   - 投票数（`raft_votes_granted`）
   - ログエントリ数（`raft_log_entries_count`）
   - スナップショット回数（`raft_snapshot_total`）
   - 提案成功/失敗数（`raft_proposals_total`, `raft_proposals_failed_total`）

2. WHEN 以下のイベントが発生する THEN システムSHALL 構造化ログ（JSON形式）を出力する:
   - `raft_initialized`: Raft初期化完了（group_id, node_id, initial_members）
   - `raft_state_changed`: ステート遷移（group_id, old_state, new_state, term）
   - `raft_leader_elected`: リーダー選出（group_id, leader_id, term）
   - `raft_membership_changed`: メンバーシップ変更（group_id, change_type, affected_node）
   - `raft_snapshot_created`: スナップショット生成（group_id, last_included_index, size_bytes）
   - `raft_snapshot_installed`: スナップショット適用（group_id, source_node, last_included_index）
   - `raft_log_compacted`: ログ圧縮（group_id, compacted_to_index, entries_removed）

## Non-Functional Requirements

### Code Architecture and Modularity
- **Single Responsibility Principle**: RaftNode、StateMachine、RaftStorageは明確に分離
- **Modular Design**: `alopex-chirps::raft` module として独立し、feature flagで有効/無効切り替え可能
- **Dependency Management**: openraftをベースとし、Chirps固有のトランスポート層を統合
- **Clear Interfaces**: traitベースの抽象化でテスタビリティを確保

### Performance

**標準ベンチマーク条件**:
- ノード数: 3ノードクラスタ
- メッセージサイズ: 1KB（コマンドペイロード）
- ネットワーク: 1ms RTT、パケットロス0%
- 測定期間: 60秒間の定常状態

**性能目標**（標準ベンチマーク条件下）:
- **書き込みスループット**: 10,000 proposals/sec以上（単一リーダー）
- **書き込みレイテンシ**: p99 < 10ms（ネットワーク往復含む）
- **リーダー選出時間**: 平均 < 500ms（タイムアウト後）
- **スナップショット生成**: < 1秒（100MB状態）
- **ログ追記レイテンシ**: p99 < 1ms（ローカルfsync）

### Security
- **トランスポート暗号化**: 全Raftメッセージはv0.4のQUIC/TLS経由
- **認証**: ノード間の相互TLS認証
- **入力検証**: 不正なRaftメッセージ（term異常、不正なindex）の検出と拒否

### Reliability
- **Raft Safety保証**: Raftプロトコルの安全性特性（Election Safety, Leader Append-Only, Log Matching, Leader Completeness, State Machine Safety）を維持
- **耐障害性**: 3ノード中1ノード障害時も動作継続
- **データ永続性**: コミット済みエントリはfsync保証
- **メンバーシップ安全性**: Joint Consensusによる設定変更時の可用性維持

### Usability
- **APIシンプル性**: `propose()`, `is_leader()`, `leader_id()`等の直感的なAPI
- **設定の簡素化**: RaftConfigのデフォルト値でほとんどのユースケースに対応
- **ドキュメント**: Rustdoc、使用例、トラブルシューティングガイドを整備

## Design Decisions

### DD-1: openraftの採用

**決定**: openraftをRaft実装の基盤として採用
**根拠**:
- Rust実装で最もアクティブなプロジェクト
- CnosDBなど実績のあるプロダクトで採用
- 非同期（async/await）ネイティブ設計
- Genericsによるカスタマイズ性
**影響**: openraftのバージョンアップに追従が必要

### DD-2: alopex-core依存方式

**決定**: Phase 1でpath依存、Phase 2でcrates.io公開に移行
**根拠**:
- WAL実装の重複を回避（DRY原則）
- 即座に開発開始可能
- 早期にcrates.io公開することで外部利用も可能に
**影響**: alopex-coreのAPI安定化が必要

### DD-3: 単一RaftNode先行実装

**決定**: v0.5では単一RaftNode、v0.6でMultiRaftManager
**根拠**:
- 複雑性を段階的に導入
- 単一グループで十分なユースケースも存在
- API設計を単一グループで検証してからマルチグループに拡張
**影響**: v0.5では複数グループの効率的な管理は未対応

## References

- [design/chirps-raft-integration-proposal.md](chirps-raft-integration-proposal.md)
- [design/technical-spec.md](technical-spec.md) セクション1.3「Unified Data File Format」
- [reference/cnosdb/replication/src/raft_node.rs](../reference/cnosdb/replication/src/raft_node.rs) - openraft使用例
- [reference/cockroach/pkg/raft/raftpb/raft.proto](../reference/cockroach/pkg/raft/raftpb/raft.proto) - Raftメッセージ定義
- [reference/yugabyte-db/architecture/design/docdb-raft-enhancements.md](../reference/yugabyte-db/architecture/design/docdb-raft-enhancements.md) - Raft最適化手法
