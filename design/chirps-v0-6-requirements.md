# Chirps v0.6 - Multi-Raft + TSO + Observability Requirements

## Introduction

Chirps v0.6は、v0.5で構築したRaft Consensus APIを拡張し、大規模分散システムに必要な機能を提供するマイルストーンです。MultiRaftManager、Timestamp Oracle（TSO）、Gossip HLC、そして包括的なメトリクスAPIを実装します。

**主な機能**:
- **MultiRaftManager**: 複数Raftグループの効率的な管理とメッセージルーティング
- **Raft TSO**: Raftベースの分散タイムスタンプサービス（MVCC/トランザクション用）
- **Gossip HLC**: Gossipプロトコル内のHybrid Logical Clock（イベント順序付け用）
- **メトリクスAPI**: Prometheus互換の包括的なメトリクスエクスポート
- **alopex-core crates.io公開**: 外部プロジェクトからも利用可能に

### Scope Clarification

**v0.6 スコープ内**:
- MultiRaftManager実装
- Raft TSO（TimestampOracle）
- Gossip HLC（LocalHlc）
- スナップショット転送最適化（チャンク転送、並列化）
- 包括的なメトリクスAPI（Prometheus形式）
- alopex-core v0.1.0 crates.io公開

**v0.6 スコープ外（将来バージョン）**:
- Durableプロファイル / IggyBackend（v0.7）
- Federation Profile（v0.8）
- クラスタ間レプリケーション（v1.0）
- CRDT実装（v0.9）

### Version Dependencies

| Alopex | Chirps | 利用可能機能 |
|--------|--------|-------------|
| v0.7 | v0.3 | Control, Ephemeral profiles |
| v0.8 | v0.4 | Raft優先ストリーム |
| v0.8+ | **v0.5** | 単一Raft Consensus API |
| **v0.8+** | **v0.6** | Multi-Raft, TSO, HLC, Metrics |
| v0.9+ | v0.7 | Durable profile（Iggy） |

### Compatibility Model

| 互換性の種類 | v0.6での対応 |
|-------------|-------------|
| **APIシグネチャ互換** | 維持 ― v0.5のRaftNode APIはそのまま動作 |
| **クロスバージョン互換** | 非対応 ― v0.5ノードとv0.6ノードの混在クラスタは拒否 |
| **crates.io互換** | alopex-core v0.1.xとの互換性を維持 |

## Alignment with Product Vision

本機能はAlopex DBの製品ビジョン「Silent. Adaptive. Unbreakable.」を支える基盤として、以下の目標に貢献します:

- **スケーラビリティ**: Multi-Raftによるシャード単位のRaftグループ管理
- **分散トランザクション**: TSOによるMVCC/スナップショット分離の実現
- **運用性**: Prometheus互換メトリクスによる統合監視

設計ドキュメント（`design/chirps-raft-integration-proposal.md`）セクション3.4「タイムスタンプサービス」で定義されている要件を実装します。

## Requirements

### Requirement 1: MultiRaftManager

**User Story:** 分散DBオペレータとして、シャード（Range/Shard）ごとに独立したRaftグループを管理したい。MultiRaftManagerを通じて、数百〜数千のRaftグループを効率的に運用できる。

#### Acceptance Criteria

1. WHEN MultiRaftManagerが初期化される THEN システムSHALL ChirpsTransportとRaftStorageFactoryを受け取る
2. WHEN `create_group(group_id, initial_members, state_machine)`が呼び出される THEN システムSHALL 新規RaftNodeを作成し、管理下に追加する
3. WHEN `get_group(group_id)`が呼び出される THEN システムSHALL 対応するRaftNodeへの参照を返す（存在しない場合はNone）
4. WHEN `remove_group(group_id)`が呼び出される THEN システムSHALL RaftNodeを停止し、管理から削除する
5. WHEN Chirps Transportからメッセージを受信する THEN システムSHALL `route_message()`でgroup_idに基づいて適切なRaftNodeにルーティングする
6. WHEN `tick_all()`が呼び出される THEN システムSHALL 全てのRaftNodeの`tick()`を効率的に呼び出す
7. WHEN 複数のRaftグループが同一ノード上で動作する THEN システムSHALL リソース（スレッド、メモリ、I/O）を効率的に共有する

**API定義（参考）**:
```rust
pub struct MultiRaftManager<SM: StateMachine, S: RaftStorage> {
    groups: HashMap<GroupId, RaftNode<SM, S>>,
    transport: Arc<ChirpsTransport>,
    storage_factory: Box<dyn RaftStorageFactory<S>>,
}

impl<SM: StateMachine, S: RaftStorage> MultiRaftManager<SM, S> {
    pub async fn create_group(
        &mut self,
        group_id: GroupId,
        initial_members: Vec<NodeId>,
        state_machine: SM,
    ) -> Result<()>;

    pub fn get_group(&self, group_id: GroupId) -> Option<&RaftNode<SM, S>>;
    pub fn get_group_mut(&mut self, group_id: GroupId) -> Option<&mut RaftNode<SM, S>>;
    pub async fn remove_group(&mut self, group_id: GroupId) -> Result<()>;
    pub async fn route_message(&mut self, msg: RaftMessage) -> Result<()>;
    pub async fn tick_all(&mut self) -> Result<()>;
    pub fn groups_count(&self) -> usize;
    pub fn list_groups(&self) -> Vec<GroupId>;
}
```

### Requirement 2: RaftStorageFactory

**User Story:** MultiRaftManager利用者として、新規Raftグループ作成時に適切なストレージインスタンスを自動生成したい。

#### Acceptance Criteria

1. WHEN MultiRaftManagerが新規グループを作成する THEN システムSHALL RaftStorageFactoryを呼び出してストレージインスタンスを生成する
2. WHEN `create_storage(group_id)`が呼び出される THEN システムSHALL グループ固有のストレージパス/設定でRaftStorageを作成する
3. WHEN 複数のグループが作成される THEN システムSHALL 各グループのストレージを分離する（データ混在防止）

**Trait定義（参考）**:
```rust
pub trait RaftStorageFactory<S: RaftStorage>: Send + Sync {
    fn create_storage(&self, group_id: GroupId) -> Result<S>;
}

pub struct WalRaftStorageFactory {
    base_path: PathBuf,
    wal_config: WalConfig,
}

impl RaftStorageFactory<WalRaftStorage> for WalRaftStorageFactory {
    fn create_storage(&self, group_id: GroupId) -> Result<WalRaftStorage> {
        let path = self.base_path.join(format!("raft-{}", group_id));
        WalRaftStorage::new(path, self.wal_config.clone())
    }
}
```

### Requirement 3: Raft TSO（Timestamp Oracle）

**User Story:** 分散トランザクションシステムとして、クラスタ全体で一貫した単調増加タイムスタンプを取得したい。TSOはMVCC、スナップショット分離、トランザクション順序付けに使用する。

#### Acceptance Criteria

1. WHEN TSOが初期化される THEN システムSHALL 専用のRaftグループで状態を管理する
2. WHEN `get_timestamp()`がTSOリーダーで呼び出される THEN システムSHALL 単調増加するHybridTimestampを返す
3. WHEN `get_timestamp()`がTSOフォロワーで呼び出される THEN システムSHALL `Error::NotLeader(leader_id)`を返す
4. WHEN `get_timestamps(count)`が呼び出される THEN システムSHALL 指定数のタイムスタンプ範囲（start, end）を返す
5. WHEN タイムスタンプ要求が高頻度で発生する THEN システムSHALL バッチ割り当てとローカルキャッシュで性能を最適化する
6. WHEN TSOリーダーが変更される THEN システムSHALL 新リーダーは旧リーダーのリースタイムアウト後に発行を開始する（ギャップ防止）
7. WHEN 物理クロックが巻き戻される THEN システムSHALL HLCの論理カウンタで単調増加を維持する

**HybridTimestamp定義（参考）**:
```rust
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct HybridTimestamp {
    /// 物理時刻（ミリ秒、Unix epoch）
    pub physical: u64,
    /// 論理カウンタ（同一物理時刻内での順序付け）
    pub logical: u32,
}

impl HybridTimestamp {
    pub fn now() -> Self;
    pub fn next(&self) -> Self;
    pub fn update(&mut self, remote: HybridTimestamp);
}
```

**TimestampOracle API（参考）**:
```rust
pub struct TimestampOracle {
    raft_node: Arc<RaftNode<TsoStateMachine, WalRaftStorage>>,
    current: HybridTimestamp,
    allocated_until: HybridTimestamp,
    config: TsoConfig,
}

impl TimestampOracle {
    pub async fn get_timestamp(&self) -> Result<HybridTimestamp>;
    pub async fn get_timestamps(&self, count: u32) -> Result<(HybridTimestamp, HybridTimestamp)>;
    pub fn is_leader(&self) -> bool;
    pub fn leader_id(&self) -> Option<NodeId>;
}

pub struct TsoConfig {
    pub batch_size: u32,           // デフォルト: 10000
    pub prefetch_threshold: u32,    // デフォルト: 1000
    pub timestamp_ttl: Duration,    // デフォルト: 3秒
}
```

### Requirement 4: TSOクライアント

**User Story:** アプリケーション開発者として、TSOからタイムスタンプを効率的に取得したい。ローカルキャッシュとバッチ取得で、ネットワーク往復を最小化できる。

#### Acceptance Criteria

1. WHEN TsoClientが作成される THEN システムSHALL ChirpsTransportとTSOリーダー情報を受け取る
2. WHEN `get_timestamp()`が呼び出される THEN システムSHALL ローカルキャッシュから可能な限り返す
3. WHEN ローカルキャッシュが空になる THEN システムSHALL TSOリーダーからバッチ取得する
4. WHEN TSOリーダーが変更される THEN システムSHALL 新リーダーを自動検出してリダイレクトする
5. WHEN ネットワークエラーが発生する THEN システムSHALL 指数バックオフでリトライする

**TsoClient API（参考）**:
```rust
pub struct TsoClient {
    transport: Arc<ChirpsTransport>,
    cached_start: HybridTimestamp,
    cached_end: HybridTimestamp,
    tso_leader: Option<NodeId>,
}

impl TsoClient {
    pub async fn get_timestamp(&mut self) -> Result<HybridTimestamp>;
    pub async fn get_timestamps(&mut self, count: u32) -> Result<Vec<HybridTimestamp>>;
    pub async fn refresh_leader(&mut self) -> Result<()>;
}
```

### Requirement 5: Gossip HLC

**User Story:** Chirpsインフラ層として、ノード間イベント（SWIMメンバーシップ変更、Gossipメッセージ）の因果順序を維持したい。各ノードがローカルでタイムスタンプを発行し、Gossip収束で同期する。

#### Acceptance Criteria

1. WHEN LocalHlcが作成される THEN システムSHALL ローカルクロックとmax_clock_skew設定を受け取る
2. WHEN `tick()`が呼び出される THEN システムSHALL 新しいローカルイベント用タイムスタンプを発行する
3. WHEN `receive(remote_ts)`が呼び出される THEN システムSHALL HLC updateルールに従って内部タイムスタンプを更新する
4. WHEN リモートタイムスタンプが大幅にスキューしている THEN システムSHALL `Error::ClockSkewTooLarge`を返す
5. WHEN SWIMメンバーシップイベントが発生する THEN システムSHALL LocalHlcのタイムスタンプを付与する
6. WHEN Gossipメッセージを送信する THEN システムSHALL LocalHlcのタイムスタンプをメッセージに含める

**LocalHlc API（参考）**:
```rust
pub struct LocalHlc {
    current: HybridTimestamp,
    max_clock_skew: Duration,
}

impl LocalHlc {
    pub fn new(max_clock_skew: Duration) -> Self;
    pub fn tick(&mut self) -> HybridTimestamp;
    pub fn receive(&mut self, remote: HybridTimestamp) -> Result<HybridTimestamp>;
    pub fn current(&self) -> HybridTimestamp;
}
```

**使い分けガイド**:

| ユースケース | 推奨方式 | 理由 |
|-------------|---------|------|
| トランザクション開始時刻 | Raft TSO | 厳密な単調増加が必要 |
| MVCC read timestamp | Raft TSO | 一貫したスナップショット |
| SWIMメンバーシップ変更 | Gossip HLC | 因果順序で十分、低レイテンシ優先 |
| Gossipメッセージ順序 | Gossip HLC | 分散発行、高スループット |
| フェデレーション間同期 | Raft TSO | クラスタ間一貫性が必要 |

### Requirement 6: スナップショット転送最適化

**User Story:** 大規模ステートを持つRaftグループとして、スナップショット転送を高速化したい。チャンク転送と並列化でネットワーク帯域を有効活用する。

#### Acceptance Criteria

1. WHEN スナップショットサイズが`chunk_threshold`を超える THEN システムSHALL チャンク単位で転送する
2. WHEN チャンク転送中にエラーが発生する THEN システムSHALL 該当チャンクのみ再送する
3. WHEN 複数チャンクを転送する THEN システムSHALL 受信側でチャンクを再構成してStateMachineに適用する
4. WHEN スナップショット転送が進行中 THEN システムSHALL 進捗状況をメトリクスで公開する
5. WHEN ネットワーク帯域が許す場合 THEN システムSHALL 複数チャンクの並列転送を行う

**スナップショット転送設定（参考）**:
```rust
pub struct SnapshotTransferConfig {
    pub chunk_size: usize,              // デフォルト: 1MB
    pub chunk_threshold: usize,         // デフォルト: 10MB
    pub max_concurrent_chunks: usize,   // デフォルト: 4
    pub transfer_timeout: Duration,     // デフォルト: 60秒
}
```

### Requirement 7: 包括的メトリクスAPI

**User Story:** 運用担当者として、Chirpsクラスタ全体の健全性と性能をPrometheusで監視したい。

#### Acceptance Criteria

1. WHEN `/metrics`エンドポイントが呼び出される THEN システムSHALL Prometheus形式でメトリクスを返す
2. WHEN Multi-Raftが動作している THEN システムSHALL グループごとのメトリクスをラベルで区別する
3. WHEN TSOが動作している THEN システムSHALL TSO固有のメトリクスを公開する
4. WHEN Gossip HLCが動作している THEN システムSHALL HLC関連のメトリクスを公開する

**メトリクス一覧**:

#### Multi-Raftメトリクス
| メトリクス名 | タイプ | ラベル | 説明 |
|-------------|--------|--------|------|
| `chirps_raft_groups_total` | Gauge | - | 管理中のRaftグループ数 |
| `chirps_raft_state` | Gauge | group_id, state | グループごとのステート（Leader=1, Follower=2, etc） |
| `chirps_raft_term` | Gauge | group_id | 現在のterm |
| `chirps_raft_commit_index` | Gauge | group_id | コミット済みインデックス |
| `chirps_raft_applied_index` | Gauge | group_id | 適用済みインデックス |
| `chirps_raft_proposals_total` | Counter | group_id, result | 提案数（success/failed） |
| `chirps_raft_proposals_latency_seconds` | Histogram | group_id | 提案レイテンシ |
| `chirps_raft_messages_sent_total` | Counter | group_id, msg_type | 送信メッセージ数 |
| `chirps_raft_messages_received_total` | Counter | group_id, msg_type | 受信メッセージ数 |
| `chirps_raft_log_entries` | Gauge | group_id | ログエントリ数 |
| `chirps_raft_snapshot_total` | Counter | group_id | スナップショット生成数 |
| `chirps_raft_snapshot_size_bytes` | Gauge | group_id | 最新スナップショットサイズ |

#### TSOメトリクス
| メトリクス名 | タイプ | ラベル | 説明 |
|-------------|--------|--------|------|
| `chirps_tso_requests_total` | Counter | result | タイムスタンプ要求数 |
| `chirps_tso_request_latency_seconds` | Histogram | - | 要求レイテンシ |
| `chirps_tso_allocated_total` | Counter | - | 割り当て済みタイムスタンプ総数 |
| `chirps_tso_physical_time` | Gauge | - | 最新物理時刻 |
| `chirps_tso_logical_counter` | Gauge | - | 現在の論理カウンタ |
| `chirps_tso_batch_size` | Histogram | - | バッチ取得サイズ分布 |

#### Gossip HLCメトリクス
| メトリクス名 | タイプ | ラベル | 説明 |
|-------------|--------|--------|------|
| `chirps_hlc_ticks_total` | Counter | - | tick呼び出し数 |
| `chirps_hlc_receives_total` | Counter | result | receive呼び出し数（success/skew_error） |
| `chirps_hlc_clock_skew_seconds` | Histogram | - | 観測されたクロックスキュー |
| `chirps_hlc_logical_advances_total` | Counter | - | 論理カウンタ進行回数 |
| `chirps_hlc_physical_advances_total` | Counter | - | 物理時刻進行回数 |

### Requirement 8: alopex-core crates.io公開

**User Story:** 外部開発者として、alopex-coreをcrates.ioから取得して独自プロジェクトで使用したい。

#### Acceptance Criteria

1. WHEN alopex-core v0.1.0がリリースされる THEN システムSHALL crates.ioに公開する
2. WHEN 公開される THEN システムSHALL 適切なREADME、CHANGELOG、LICENSEを含める
3. WHEN chirps-raftがalopex-coreを使用する THEN システムSHALL crates.io版への依存に切り替える
4. WHEN APIに破壊的変更がある THEN システムSHALL セマンティックバージョニングに従う

**公開前チェックリスト**:
- [ ] API安定性レビュー完了
- [ ] 公開ドキュメント（Rustdoc）整備
- [ ] README.md作成
- [ ] CHANGELOG.md作成
- [ ] LICENSE（Apache-2.0 / MIT）選定
- [ ] CIパイプライン整備（テスト、clippy、fmt）
- [ ] 最小限の外部依存確認

## Non-Functional Requirements

### Code Architecture and Modularity
- **Single Responsibility Principle**: MultiRaftManager、TSO、HLCは独立モジュール
- **Modular Design**: feature flagで機能の有効/無効切り替え
  - `multi-raft`: MultiRaftManager
  - `tso`: Timestamp Oracle
  - `hlc`: Gossip HLC
- **Dependency Management**: openraftのAsync Raft Nodeを拡張

### Performance

**標準ベンチマーク条件**:
- ノード数: 3ノードクラスタ
- Raftグループ数: 100グループ
- メッセージサイズ: 1KB
- ネットワーク: 1ms RTT
- 測定期間: 60秒間の定常状態

**性能目標**（標準ベンチマーク条件下）:
- **Multi-Raftスループット**: 全グループ合計 100,000 proposals/sec
- **Multi-Raftオーバーヘッド**: 単一グループ比 < 10%
- **TSOスループット**: 100,000 timestamps/sec
- **TSOレイテンシ**: p99 < 1ms（ローカルキャッシュヒット時）
- **TSOレイテンシ**: p99 < 5ms（ネットワーク往復時）
- **Gossip HLC tick**: < 100ns
- **スナップショット転送**: 100MB/s（1Gbps環境）

### Security
- **TSO認証**: タイムスタンプ要求はノード認証必須
- **HLC検証**: 不正なクロックスキューを検出・拒否
- **メトリクスエンドポイント**: 認証オプション（本番環境推奨）

### Reliability
- **Multi-Raft分離**: 一つのグループの障害が他に影響しない
- **TSO可用性**: リーダーフェイルオーバー時も < 3秒の不可用時間
- **HLC耐障害性**: ノード障害時も他ノードのHLCは継続動作

### Usability
- **メトリクス統合**: Grafanaダッシュボードテンプレート提供
- **設定簡素化**: デフォルト設定で100グループまで対応
- **移行ガイド**: v0.5 → v0.6の移行手順ドキュメント

## Design Decisions

### DD-1: TSO専用Raftグループ

**決定**: TSOは専用のRaftグループで管理
**根拠**:
- TiKV PD TSOと同様のアーキテクチャ
- 高頻度アクセスに耐えるためデータRaftグループと分離
- リーダーリース延長で読み取り最適化可能
**影響**: 追加のRaftグループによるリソース消費（微小）

### DD-2: Gossip HLCとRaft TSOの二層構造

**決定**: インフラ層（Gossip HLC）とアプリ層（Raft TSO）で異なるタイムスタンプを使用
**根拠**:
- 因果順序で十分なユースケース（SWIM、Gossip）には低レイテンシなHLC
- 厳密な単調増加が必要なユースケース（MVCC）にはRaft TSO
- TiKV/CockroachDBの設計を参考
**影響**: 開発者が適切な方式を選択する必要あり（ドキュメントで明確化）

### DD-3: メトリクスのラベル設計

**決定**: group_idをラベルとして使用し、Prometheusのカーディナリティを考慮
**根拠**:
- 数百グループまでは実用的
- 数千グループの場合はサマリーメトリクスも提供
- Grafanaでのフィルタリングが容易
**影響**: 大規模クラスタではメトリクスストレージ容量に注意

## References

- [design/chirps-raft-integration-proposal.md](chirps-raft-integration-proposal.md) セクション3.3, 3.4
- [design/technical-spec.md](technical-spec.md)
- [reference/cnosdb/replication/src/multi_raft.rs](../reference/cnosdb/replication/src/multi_raft.rs) - Multi-Raft実装例
- [reference/yugabyte-db/architecture/design/docdb-raft-enhancements.md](../reference/yugabyte-db/architecture/design/docdb-raft-enhancements.md) - Leader Leases, Group Commits
- TiKV PD TSO設計: https://tikv.org/docs/dev/concepts/explore-tikv-features/pd-control/
- Hybrid Logical Clocks論文: https://cse.buffalo.edu/tech-reports/2014-04.pdf
