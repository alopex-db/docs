# 分散クエリ実行アーキテクチャ設計 (Distributed Query Execution)

> Status: **Draft (設計提案)** / 2026-07-14
> 対象: alopex-sql v0.9.0+ (Distributed Query Planner) / 対応 Alopex DB v0.7-v0.8
> 依存: Chirps v0.3+ (合意・ノード間通信メッシュ)
> 関連: [alopex-sql-milestone.md](../roadmap/alopex-sql-milestone.md#v090-distributed-query-chirps-依存--予定),
> [alopex-db-design-spec.md §3.4 / §4.3](../concepts/alopex-db-design-spec.md),
> [chirps-raft-integration-proposal.md](./chirps-raft-integration-proposal.md)

## 0. この文書の位置づけ

alopex-db は単なる RDBMS ではなく**分散データベース**である。したがって SQL エンジンの本質的な設計課題は「どの組み込み関数を実装するか」ではなく、**クラスタ内の複数ノードにまたがって演算をどう分割し、各ノードで計算した部分結果をどう戻し、どう最終集約するか**にある。

本文書はその分散クエリ実行機構を設計する。現状（後述）は SQL エンジンが完全に単一ノード実行であり、分散に必要な最小の基盤（部分状態を持つ集約器、再分配演算子、分散プラン表現）が存在しない。本設計はそのギャップを、参考実装（CockroachDB DistSQL, TiDB MPP, YugabyteDB pushdown, DataFusion, cnosdb）の実証済みパターンに基づいて埋める。

## 1. 現状 (As-Is) — 事実

コード調査に基づく事実（憶測を含まない）。

| 観点 | 現状 | 根拠 |
|---|---|---|
| `alopex-cluster` クレート | 14 行のスタブ（`add(l,r)` テンプレート、依存ゼロ） | `alopex/crates/alopex-cluster/src/lib.rs` |
| SQL 論理プラン | `Scan/Filter/Project/Join/Aggregate/Sort/Limit` のみ。Exchange/Shuffle/Repartition/ScatterGather 無し | `alopex/crates/alopex-sql/src/planner/logical_plan.rs:69-` |
| 集約器 `Accumulator` | `update` / `finalize` / `clone_box` のみ。**`state()`（部分状態出力）と `merge()`（部分状態統合）が無い** | `alopex/crates/alopex-sql/src/executor/query/aggregate.rs:89-93` |
| 分散プラン | ドキュメント内の型スケッチ `DistributedPlan`/`GatherType` のみ。実ファイル `planner/distributed.rs` は未作成 | `docs-public/roadmap/alopex-sql-milestone.md:1025-1053` |
| 実行モデル | 100% 単一ノード。gateway でプランを直接実行 | `alopex/crates/alopex-sql/src/executor/mod.rs:146-174` |

**結論**: 分散クエリ実行は構想段階。`Accumulator` に部分状態が無いことが、分散集約を原理的に不可能にしている最大の欠落である。

## 2. 参考実装からの設計原則 (証拠に基づく)

3つのアーキテクチャ系統と、全系統に共通する不変則を調査した。

### 2.1 三つのアーキテクチャ系統

| モデル | 代表 | 再分配 | 集約分割 | コスト |
|---|---|---|---|---|
| フル分散データフロー | CockroachDB DistSQL | processor/stream/router をノード配置、hash router で shuffle | 宣言的分解表 `DistAggregationTable` | 最重 |
| MPP + プッシュダウン | TiDB | ExchangeSender/Receiver (Hash/Broadcast/PassThrough) | Partial1/Partial2/Final 多段、DISTINCT は3段 | 重 |
| 集約プッシュダウン + gather | YugabyteDB, cnosdb | 汎用 shuffle 無し。スキャン層で部分集約 → coordinator が集める | coordinator が単一 Final 点 | 軽 |

- CockroachDB: `pkg/sql/physicalplan/aggregator_funcs.go` (`DistAggregationTable`), `pkg/sql/distsql_physical_planner.go` (2段プラン, `OutputRouterSpec_BY_HASH`)
- TiDB: `pkg/planner/core/operator/physicalop/base_physical_agg.go` (`ConvertAvgForMPP`), `physical_exchange_sender.go` (`ExchangeType`)
- YugabyteDB: `src/postgres/src/backend/executor/nodeAgg.c` (`yb_agg_pushdown`, AVG→SUM/COUNT 分解), `src/yb/docdb/doc_expr.cc` (tablet 側集約)
- cnosdb: `coordinator/src/reader/table_scan/opener.rs:53-113` (local/remote 分岐), `push_down_aggregation.rs`
- DataFusion: `physical-plan/src/aggregates/mod.rs:84` (`AggregateMode`), `expr-common/src/accumulator.rs:51` (`Accumulator`), `functions-aggregate/src/average.rs:510` (`AvgAccumulator`)

### 2.2 全系統に共通する不変則 (alopex が必ず従う)

1. **集約関数は「部分状態 (state) + マージ (merge)」型に統一する。** 部分状態は可換・結合的でなければならない。DataFusion `Accumulator`（`state()`/`merge_batch()`）が模範。
2. **AVG は必ず (sum, count) の2要素状態で運ぶ。** 割り算は最終段まで遅延する。3系統すべて同一戦略。0除算対策は TiDB 方式 `case when count=0 then 1 else count` が安全。
3. **GROUP BY 列は first-row / any-not-null 集約で持ち回る。**
4. **再分配の基本形は「group-by 列でのハッシュ分配」。** 同一グループを同一ノードへ集めることが最終集約の正しさの前提。
5. **COUNT(DISTINCT) は2段では不正。** ハッシュ再分配後も重複が残る。3段集約、または distinct 列で先に repartition + dedup が必要。
6. **プッシュダウン可否は明示的なホワイトリスト判定にする** (YugabyteDB `yb_agg_pushdown_supported`)。押し下げ不能なら安全にコーディネータ集約へフォールバック。

## 2.5 二系統の分離 — 本設計の骨格

分散DBの SQL 実装は、性質の異なる**二つの系統**に分かれる。実装計画とは、この二系統をどのバージョンで実装するかの割り付けに他ならない。

- **系統A: SQL言語・ライブラリ関数の実装**（単一ノードで意味が閉じる）
  - スカラー関数・集約関数・演算子の意味論と評価、関数レジストリ、型検査。
  - 「1ノード上で正しい答えを出す」ことが責務。分散を意識しない。
  - 例: `ABS`, `UPPER`, `COALESCE`, `SUM`, `AVG`（単一ノード上の計算として）。

- **系統B: クラスタ全体の結果整合性の実装**（ノードを跨いで正しい答えを出す）
  - 部分状態を持つ集約器、部分集約→再分配→最終集約、分散プラン、プッシュダウン、coordinator/gather。
  - 「複数ノードの部分結果を統合して、単一ノードと同一の答えを保証する」ことが責務。
  - 系統Aの関数のうち、分散可能な形（可換・結合的な部分状態）に再定義できるものだけが系統Bに載る。

**依存関係**: 系統B（分散集約）は系統A（集約関数の意味論）の上に立つが、系統Aの集約器を「部分状態 + マージ」型で設計しておかないと系統Bに載らない（§4.1）。よって集約関数は系統Aの段階から `state()`/`merge()` を備えて実装するのが正しく、後付けの改修は避ける。スカラー関数は分散に関して中立（各行独立に評価できるため、どのノードで評価しても結果が同じ）であり、系統Aで完結する。

## 2.6 Chirps との責務分離 (基盤 vs メタデータ管理)

系統B（クラスタ整合性）は自前でノード管理・通信・合意を実装しない。**それらは基盤 Chirps が提供し、alopex-db はその上に DB のメタデータ管理と分散クエリ実行を載せる。** この分離を誤ると責務が二重化する。

### 責務境界表

| 機能 | 担当 | 状態 | 根拠 |
|---|---|---|---|
| ノードメンバーシップ (discovery / failure detection) | **Chirps** (SWIM) | 実装済 | `chirps/crates/chirps-gossip-swim/src/engine.rs`, `alopex-chirps/src/mesh.rs:280-341` |
| ノード間通信 (QUIC / Mesh) | **Chirps** | 実装済 | `chirps/crates/chirps-transport-quic/`, `chirps-core/src/backend.rs:10-28` |
| 合意 (Raft: 選挙・複製・メンバーシップ・スナップショット) | **Chirps** (openraft ラッパ) | 実装済 (単一グループ) | `alopex-chirps/src/raft/node.rs:106-337` |
| Multi-Raft グループ管理 (`MultiRaftManager`) | **Chirps** | v0.6 予定 (未実装) | proposal `chirps-raft-integration-proposal.md:389-427`, `chirps-v0-6-requirements.md:60-99` |
| タイムスタンプ (Raft TSO / Gossip HLC) | **Chirps** | v0.6 予定 (未実装) | proposal:429-772, `chirps-v0-6-requirements.md:129-248` |
| Range Descriptor (キーレンジ→シャード対応) | **alopex-db** | 設計のみ | `alopex-db-design-spec.md:636-663` |
| シャード配置 (Range→ノード) / Split・Merge | **alopex-db** | 設計のみ | spec:653, 665-687 |
| ステートマシン中身 (KV/LSM 操作) | **alopex-db** (`RangeStateMachine`) | 設計のみ | proposal:230, 791-831 |
| キー→Range 解決 (`RangeManager`) | **alopex-db** | 設計のみ | proposal:833-858 |
| クエリルーティング (`GlobalRouter`) | **alopex-db** | 設計のみ | spec:1446-1470 |
| 分散クエリ実行 (部分集約→再分配→最終集約) | **alopex-db** | 本文書 | — |
| MVCC のための TSO 利用 | **alopex-db** (Chirps TSO の利用側) | 設計のみ | proposal:437-442 |

**要約**: Chirps = 「合意・通信・メンバーシップ・（将来）グループの器と時刻」。alopex-db = 「どのデータがどのノードにあるか（メタデータ）」「それをどうルーティングし分散演算するか」。**系統Bの分散集約は、Chirps が提供する通信・グループの上で、alopex-db 自身のメタデータ（Range Descriptor）に従ってプランを配る**。

### 分離上の未決事項 (事実として要議論)

コードとドキュメントの差分から判明した、計画確定前に潰すべき点:

1. **メタデータ複製グループの帰属が未確定。** Range Descriptor（`MetadataStore.change_log`）自体も Raft で複製する想定（spec:645-646, 677-679）だが、その「メタデータ用 Raft グループ」を Chirps Multi-Raft のどのグループに割り当てるか（TiKV の PD 相当を alopex が持つか Chirps が持つか）が明記されていない。
2. **キー→group_id 解決の責務が二段に見える。** Chirps `MultiRaftManager.route_message`（proposal:422）と alopex `RangeManager.get_range_for_key`（proposal:843）の境界。実装で確定が必要（現行コードにはどちらも未実装、単一 `RaftNode` のみ）。
3. **Chirps 公開 trait と実コードの乖離。** proposal §3.1 の独自 `StateMachine`/`RaftStorage` trait と、実コードの openraft 直用（node.rs:118-130）が一致しない。alopex が実装すべきインターフェースが未確定。
4. **`crates/alopex-chirps`（alopex-db 直下）が空。** alopex-db が Chirps をサブツリー `chirps/` 経由で使うか crates.io 公開版で使うかが未確定（proposal §7 移行計画で議論中）。

系統Bの本実装（ノード跨ぎ）は、**少なくとも 1・2 の確定と、Chirps Multi-Raft（v0.6）の提供を前提とする**。それ以前は系統Bのうち「単一プロセス内で成立する部分（部分状態 Accumulator・2段集約・ローカル多インスタンス simulation）」までしか進められない。

## 3. 目標アーキテクチャ (To-Be)

alopex-db はシャード型（Range Descriptor + Raft、`design-spec §3.4`）であり、時系列・ベクトル志向である。参考実装の教訓は「**汎用 hash-shuffle（任意演算子間のノード跨ぎ再分配）は最も重いので、データ局所性で済むなら避ける**」。よって **cnosdb / YugabyteDB 型の「集約プッシュダウン + coordinator gather」を第一目標**とし、汎用 shuffle は将来拡張とする。

### 3.1 実行モデル

```
                    ┌─────────────────────────┐
   SQL ──► Planner ─┤ 論理プラン (単一ノード)   │
                    │  Aggregate(AVG, GROUP BY) │
                    └───────────┬─────────────┘
                                │  DistributedPlanner
                                ▼
                    ┌─────────────────────────┐
                    │ 分散プラン                │
                    │  ScatterGather {          │
                    │    scatter: Partial集約   │  ← 各シャードへ配布
                    │    gather : Final集約     │  ← coordinator で統合
                    │    repartition: HashByKey │  (GROUP BY 有時のみ)
                    │  }                        │
                    └───────────┬─────────────┘
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
   ┌─────────┐            ┌─────────┐            ┌─────────┐
   │ Shard A │            │ Shard B │            │ Shard C │
   │ Scan    │            │ Scan    │            │ Scan    │
   │ Filter↓ │  push down │ Filter↓ │            │ Filter↓ │
   │ Partial │            │ Partial │            │ Partial │
   │ (sum,   │            │ (sum,   │            │ (sum,   │
   │  count) │            │  count) │            │  count) │
   └────┬────┘            └────┬────┘            └────┬────┘
        │  state (IPC)         │  state              │  state
        └───────────────────────┼───────────────────────┘
                                ▼
                    ┌─────────────────────────┐
                    │ Coordinator (gateway)    │
                    │  merge states → Final    │
                    │  AVG = Σsum / Σcount     │
                    └─────────────────────────┘
```

### 3.2 集約モードと再分配

DataFusion `AggregateMode` に倣い、以下を導入する。

- `AggregateMode::Partial` — 生入力から部分状態を作る（各シャード）。入力分配は不問。
- `AggregateMode::Final` — 部分状態を統合して最終値を出す（coordinator）。入力は単一 partition に集約されていること。
- `AggregateMode::FinalPartitioned` — group-by 列でハッシュ分配済みの部分状態を統合（複数 Final ノードで並列）。将来の汎用 shuffle 導入時に使用。
- `AggregateMode::Single` — 単一ノードで完結（分散不要時。既存経路と同じ）。

`GatherType`（既存構想を踏襲）:
- `Union` — 部分結果の単純連結（GROUP BY 無し・非集約）。
- `MergeSort` — ソート済み部分結果のマージ（ORDER BY + LIMIT）。
- `Aggregate` — 部分状態の統合（本設計の主対象）。

## 4. コンポーネント設計

### 4.1 部分状態を持つ Accumulator (フェーズ1の核心)

既存 `Accumulator` トレイトを拡張する。**これが分散集約の土台であり、単一プロセス並列としても価値がある。**

```rust
// alopex-sql/src/executor/query/aggregate.rs (拡張案)

pub trait Accumulator: Send {
    /// 生入力を1行取り込む (Partial 段 / Single 段)
    fn update(&mut self, values: &[Value]) -> Result<(), ExecutorError>;

    /// 部分状態を吐き出す。可換・結合的な中間値の列であること。
    /// 例: AVG なら [sum, count]、COUNT なら [count]、SUM なら [sum]。
    fn state(&self) -> Result<Vec<Value>, ExecutorError>;

    /// 他インスタンスの state() 出力を取り込む (Final / FinalPartitioned 段)
    fn merge(&mut self, state: &[Value]) -> Result<(), ExecutorError>;

    /// 最終値を確定する (Final 段 / Single 段)
    fn finalize(&self) -> Result<Value, ExecutorError>;

    fn clone_box(&self) -> Box<dyn Accumulator>;
}
```

**関数ごとの部分状態設計**（参考実装で実証済み）:

| 関数 | 部分状態 (state) | merge | finalize |
|---|---|---|---|
| COUNT | `[count]` | Σcount | count |
| SUM | `[sum]` | Σsum | sum |
| MIN / MAX | `[extremum]` | min/max | extremum |
| AVG | `[sum, count]` | Σsum, Σcount | `count==0 ? NULL : sum/count` |
| TOTAL | `[sum]` | Σsum | sum (空は 0.0) |
| GROUP_CONCAT / STRING_AGG | `[concatenated, sep]` | 順序保持で連結 | 連結結果 |
| COUNT(DISTINCT) | **2段不可** — §4.4 参照 | — | — |

### 4.2 分散プラン表現

既存の `DistributedPlan`（`alopex-sql-milestone.md:1025`）を土台に、集約の2段分割を明示できるよう精緻化する。

```rust
// alopex-sql/src/planner/distributed.rs (新規)

pub enum DistributedPlan {
    Local(LogicalPlan),
    ScatterGather {
        /// 各シャードで実行する断片 (Partial 集約・Filter・Projection を含む)
        scatter: Box<LogicalPlan>,
        /// coordinator での統合方法
        gather: GatherType,
        /// GROUP BY 有時: group-by 列でのハッシュ再分配 (将来の多 Final 用)
        repartition: Option<RepartitionSpec>,
        shards: Vec<ShardId>,
    },
    Remote { plan: Box<LogicalPlan>, target: ShardId },
}

pub struct RepartitionSpec {
    pub scheme: RepartitionScheme,   // HashBy(cols) | Broadcast | PassThrough | RangeBy(cols)
    pub num_partitions: usize,
}
```

### 4.3 DistributedPlanner (論理プラン → 分散プラン変換)

DataFusion `physical_planner.rs:823` / CockroachDB `planAggregators` に相当。

変換規則（集約に着目）:
1. 対象テーブルが単一シャードに収まる → `Local`（既存経路）。
2. 複数シャードにまたがる `Aggregate` →
   - `scatter` = 元の `Aggregate` を `AggregateMode::Partial` に書き換えたもの（+ push-down 可能な Filter/Projection を内包）。
   - `gather` = `GatherType::Aggregate`（`AggregateMode::Final`）。
   - GROUP BY 有 → `repartition = Some(HashBy(group_cols))`（当面は coordinator 単一 Final のため `PassThrough` 相当でも可）。
3. **AVG の書き換え**: Partial 段で `AVG(x)` を内部的に `[SUM(x), COUNT(x)]` の2状態へ、Final 段で `Σsum / Σcount` へ変換する（TiDB `ConvertAvgForMPP` パターン、0除算は case でガード）。
4. **プッシュダウン判定**: `Filter` / `Projection` / 上記対応集約のみを scatter 側に押し下げる。非対応（COUNT(DISTINCT) 等）は §4.4 に委ねるか、行を吸い上げて coordinator 集約にフォールバック（YugabyteDB `yb_agg_pushdown_supported` 方式）。

### 4.4 COUNT(DISTINCT) の扱い

2段（Partial→Final）では再分配後に重複が残り不正。以下のいずれかを採る:
- **フェーズ1**: distinct 列で先に repartition + dedup（CockroachDB `DistinctSpec` 先行方式）。当面は coordinator 単一集約なので「全行を coordinator に集めて distinct 集約」で正しさを担保（性能は劣後、明示的にフォールバックと記録）。
- **将来**: 3段集約（TiDB `canUse3Stage4SingleDistinctAgg`）を導入し、distinct 列でハッシュ分配してから2段集約。

### 4.5 実行層: coordinator と shard executor

- **Shard Executor**: scatter 断片を受け取り、ローカルデータで Partial 集約を実行、`state()` 出力を IPC 形式でエンコードして返す。cnosdb `opener.rs` の local 分岐に相当。
- **Coordinator (gateway)**: 各シャードの state ストリームを集め、`merge()` で統合し `finalize()`。cnosdb `CheckedCoordinatorRecordBatchStream` に相当（failover は将来）。
- **ノード間通信**: Chirps Mesh（`design-spec §4.3.2` の QUIC 接続）を利用。部分状態のシリアライズ形式は §5 参照。

## 5. ノード跨ぎで追加が必要なもの (フェーズ2)

単一プロセス並列（フェーズ1）には不要だが、真の分散に必須:

1. **部分状態のシリアライズ形式**: `state()` の `Vec<Value>` を IPC / MessagePack でエンコード（Nim FFI で既に MessagePack 実績あり。cnosdb は gRPC+Arrow）。単一の真実となるスキーマを持つこと（FFI AST 契約と同思想）。
2. **物理プラン断片のリモート実行 RPC**: scatter 断片を対象シャードのノードへ送り実行させる。各演算子が自身をシリアライズできる `to_fragment()` を持つ設計（CockroachDB `execinfrapb`, TiDB `ToPB`）。
3. **データ配置メタデータ**: どのシャード/キーレンジがどのノードにあるか（`design-spec §3.4.1` Range Descriptor）。スケジューリングはデータ局所性（leaseholder/leader 配置）に従う（CockroachDB `span_resolver` 方式）。
4. **部分障害処理**: シャード応答欠落時の failover / リトライ（cnosdb vnode failover）。

## 6. 実装計画 — 二系統 × バージョン割り付け

実装計画の本質は、系統A（SQL言語・ライブラリ関数）と系統B（クラスタ整合性）を**どのバージョンで実装するか**の割り付けである。両系統は独立に進むのではなく、系統Aの集約器を系統Bに載る形（部分状態 + マージ）で設計することで接続する。系統Bのノード跨ぎ本実装は Chirps Multi-Raft/TSO（v0.6 予定）に律速される。

### 6.1 系統A: SQL言語・ライブラリ関数（単一ノードで完結）

既存の [alopex-sql-milestone.md](../roadmap/alopex-sql-milestone.md) の関数ロードマップに対応する。分散に中立で、Chirps に依存しない。

| alopex-sql版 | 範囲 | 系統Bへの接続 |
|---|---|---|
| v0.5.0 | GROUP BY / 集約基盤。**この時点で集約器を「部分状態 + マージ」型で設計する**（`state()`/`merge()`, AVG=(sum,count)）。関数レジストリ基盤 | 系統Bの土台。ここを誤ると後の分散集約が全て後付け改修になる |
| v0.5.1-v0.5.4 | ハッシュ/UUID・システム関数・コアスカラー関数（ABS/UPPER/COALESCE 等）・日付時刻 | スカラーは分散中立（各行独立）。系統Aで完結 |
| v0.6.0 | JOIN / Subquery（単一ノード） | 分散 JOIN は系統B（将来）。まず単一ノードで意味論を確立 |

**方針**: v0.5.0 の集約器実装時点で `state()`/`merge()` を必須とする。スカラー関数（v0.5.3）は分散を考慮不要（どのノードで評価しても結果不変）。

### 6.2 系統B: クラスタ全体の結果整合性（ノード跨ぎ）

Chirps 基盤の上に、alopex-db のメタデータ（Range Descriptor）に従って分散演算を配る。

| フェーズ | 範囲 | Chirps 依存 | 対応バージョン |
|---|---|---|---|
| **B-1. 分散集約の土台（単一プロセス）** | `AggregateMode`(Partial/Final) 導入、単一プロセス内 Partial→Final 並列。系統A v0.5.0 の部分状態 Accumulator を使う | なし | alopex-sql v0.9.0 準備 |
| **B-2. 分散プラン表現** | `planner/distributed.rs`、`DistributedPlanner`、プッシュダウン判定（ホワイトリスト）、COUNT(DISTINCT) フォールバック | なし | alopex-sql v0.9.0 |
| **B-3. Scatter-Gather simulation** | coordinator + shard executor をローカル多インスタンスでシミュレート（Chirps 無し）。Range Descriptor のローカル実装 | なし（模擬） | DB v0.7 |
| **B-4. ノード跨ぎ本実装** | 部分状態 IPC 化、リモート実行 RPC、Range Descriptor を Chirps Mesh 越しに配信、キー→Range 解決、failover | **Chirps Multi-Raft + TSO (v0.6)**、および §2.6 未決 1・2 の確定 | DB v0.8 / alopex-sql v0.9.0-index |
| **B-5. 汎用 shuffle / 多 Final** | `FinalPartitioned`、group-by hash 分配のノード跨ぎ exchange、3段 DISTINCT、分散 JOIN | Chirps Multi-Raft 成熟 | DB v0.10-v0.11+ |

### 6.3 依存関係と律速

```
系統A v0.5.0 (部分状態 Accumulator) ──┬──► B-1 (単一プロセス並列)
                                      │
                                      └──► B-2 (分散プラン) ──► B-3 (simulation, DB v0.7)
                                                                    │
              Chirps Multi-Raft + TSO (v0.6) ──────────────────────┤
              §2.6 未決 1・2 の確定 ────────────────────────────────┴──► B-4 (本実装, DB v0.8)
                                                                                │
                                                                                └──► B-5 (v0.10+)
```

**律速の要点**:
- **B-1〜B-3 は Chirps に依存しない**。系統A v0.5.0 の部分状態 Accumulator さえあれば、単一プロセス並列とローカル simulation まで進められる（DB v0.7 の "Scatter-Gather simulation" に一致）。
- **B-4（真の分散）は Chirps v0.6（Multi-Raft/TSO）と §2.6 未決点の確定が前提**。これらが揃うまで B-4 は着手不可。逆に言えば、B-4 を待つ間に系統A（関数拡充）と B-1〜B-3 を先行できる。
- **最重要の先行タスクは系統A v0.5.0 の集約器を部分状態型で作ること**。これが両系統の結節点であり、ここを飛ばすと後続すべてが後付け改修になる。

## 7. 未決事項 (要議論)

- 部分状態のシリアライズ形式: MessagePack（Nim FFI 流用）か Arrow IPC（cnosdb 流用）か。§5-1。
- coordinator を固定 gateway にするか、クエリごとに選出するか（`design-spec §4.3.4` GlobalRouter との整合）。
- ベクトル検索（Top-K）の分散: 各シャードで局所 Top-K → coordinator でマージ Top-K（部分状態 = 上位 K 件）。集約と同じ枠組みで表現可能か要検討。
- 単一プロセス並列（フェーズ1）を tokio タスク並列で行うか、既存の async facade（alopex-sql v0.4.0）に載せるか。

---

### 参照ファイル一覧 (実装着手時の出発点)

- 集約器: `alopex/crates/alopex-sql/src/executor/query/aggregate.rs`
- 論理プラン: `alopex/crates/alopex-sql/src/planner/logical_plan.rs`
- エグゼキュータ: `alopex/crates/alopex-sql/src/executor/mod.rs`
- クラスタ (スタブ): `alopex/crates/alopex-cluster/src/lib.rs`
- 既存分散構想: `docs-public/roadmap/alopex-sql-milestone.md` v0.9.0+ 節, `docs-public/concepts/alopex-db-design-spec.md` §3.4/§4.3
