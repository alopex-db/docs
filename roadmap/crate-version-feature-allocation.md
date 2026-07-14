# クレート × バージョン × 機能 割り付け表 (Feature Allocation Matrix)

> Status: **割り付け提案** / 2026-07-14
> 目的: 実装漏れ債務と今後の機能を、担当クレートと着手バージョンに **1つずつ明示配置** する。
> 「全部いっぺんに」を禁じ、各機能に責任クレートと期日を持たせることで実装漏れの再発を防ぐ。
> 関連: [distributed-implementation-gap-audit.md](../design/distributed-implementation-gap-audit.md)（漏れの棚卸し）,
> [distributed-query-execution-design.md](../design/distributed-query-execution-design.md)（分散設計）

## 0. 原則

1. **1機能は1クレート・1バージョンに配置する。** 複数バージョンにまたがる場合は分割して別項目にする。
2. **「全部」を1バージョンに入れない。** 割り付けの無い機能は着手しない（＝スコープ外と明示）。
3. **各機能に受入基準（DoD）を持たせる。** 「実装した」だけでなく「何が満たされたら完了か」を定義する。
4. **依存の逆流を禁じる。** 下位（core）→上位（sql→embedded/server）の一方向。分散基盤は Chirps に依存。

## 1. クレート責務とリリース実態 (割り付けの前提)

### 1.1 実リリース状況 (2026-07-14、crates.io/PyPI/git を観測で確定)

**v0.7.0 は crates.io・PyPI 両方で公開済み。** 製品バージョンは v0.7 系に入っている (v0.7.1 リリース作業中 → 本 spec は v0.7.2)。

| クレート | 実公開版 (crates.io/PyPI) | Cargo.toml 版定義 | 版定義の種別 |
|---|---|---|---|
| alopex-core | crates.io **0.7.0** | `0.6.0` | workspace 継承 |
| alopex-sql | crates.io **0.7.0** | `0.6.0` | **独立指定** |
| alopex-dataframe | crates.io **0.7.0** | `0.6.0` | **独立指定** |
| alopex-embedded | crates.io **0.7.0** | `0.6.0` | workspace 継承 |
| alopex-server | crates.io **0.7.0** | `0.6.0` | workspace 継承 |
| alopex-cli | crates.io **0.7.0** | `0.6.0` | workspace 継承 |
| alopex-cluster | crates.io **0.7.0** | `0.6.0` | workspace 継承 |
| alopex-tools | crates.io **未公開** | `0.6.0` | workspace 継承。役割=競合DB比較ベンチ+レポート出力だが未実装(実装漏れ)。→ issue #45 で集約・実装。公開方針は同 issue で確定(内部ベンチなら publish=false 有力) |
| alopex (=alopex-py) | PyPI **0.7.0** | `0.7.0` | **独立指定** |

**★バージョンはクレートごとに独立管理。「ワークスペース統一」は誤り★**:
- workspace 継承 (`version.workspace = true`): core / cluster / embedded / server / cli / tools
- **独立指定** (Cargo.toml に `version = "..."`): **alopex-sql / alopex-dataframe / alopex-py**
- 公開クレートで独自にバージョン進捗するものがある (例: dataframe は 0.2.0 → 0.6.0 に飛んだ)。「全部を同一版で揃える」前提は禁止。**どのクレートがどの版でどの機能を持つべきかを本表で個別管理する**。

**実在する不整合 (要是正)**:
- **crates.io は全 Rust クレート 0.7.0 公開済みなのに、リポジトリの Cargo.toml は 0.6.0 (workspace 継承勢・sql・dataframe) のまま。** alopex-py のみ 0.7.0 で一致。→ **作業ツリーの版定義が公開済み版に未追随**。次リリース (v0.7.2) 前に、まず Cargo.toml の版を実公開版に合わせて整合させる必要がある (下記債務 D1)。
- 過去の割り付け表に記した「C1: crates.io が v0.7.0 未公開」は**誤り**だった (crates.io は公開済み)。C1 は撤回する。

**#3 部分状態集約器の実装漏れは v0.7.0 でも継続** (集約器 `Accumulator` は `update`/`finalize` のみ)。これが本 spec (v0.7.2) の是正対象。alopex-cluster は v0.7.0 で「metadata contracts + simulation」まで (remote execution/Raft/分散 txn は未実装＝B-4 残債務)。

### 1.2 クレート責務

Cargo.toml の description に基づく公式責務。

| クレート | 責務 | 分散における役割 |
|---|---|---|
| **alopex-core** | ストレージエンジン（LSM/columnar/vector index）、**実行プリミティブ**（hash_join, 集約プリミティブ, spill） | 単一ノードの物理演算。分散集約の**部分状態のマージ演算**もここ |
| **alopex-sql** | SQL パーサ・プランナ・エグゼキュータ（core を呼ぶ） | 論理/分散プランの生成、集約器の trait 定義、coordinator/gather ロジック |
| **alopex-cluster** (未公開) | 分散クラスタ協調（Chirps 基盤の上） | Range Descriptor、シャード配置、キー→Range 解決、クエリルーティング、リモート実行 |
| alopex-embedded / server / py / cli | 上位インターフェース | 分散クエリの入口（透過的にルーティング） |
| (外部) **Chirps** | 合意(Raft)・通信(QUIC)・メンバーシップ(SWIM)・(v0.6)Multi-Raft/TSO | 基盤。alopex-cluster が利用 |

## 2. 実装漏れ債務の割り付け (最優先)

[gap-audit](../design/distributed-implementation-gap-audit.md) の10項目を、担当クレートと是正バージョンへ配置する。

> バージョンはワークスペース統一版（§1.1）。**債務は v0.7.x パッチ系列で完済する（v0.8.0 に繰り越さない）。** v0.7.0 でやるべきだった実装漏れは「v0.7 の未完」であり、v0.7 系列内で埋める。**v0.8.0 の本来予定（分散クエリ本実装 = B-4）は温存し、債務で汚染しない。**

| # | 機能 | 担当クレート | 是正バージョン | 破壊的変更 | 受入基準 (DoD) |
|---|---|---|---|---|---|
| 3 | 集約器 `state()`/`merge()` 追加 | alopex-sql (trait), alopex-core (マージ演算) | **ws v0.7.2** | あり(trait) | 全8集約器が state/merge 実装、AVG=(sum,count)化、単一プロセス内 partial→final が単一パスと同結果 |
| 4 | DISTINCT 集約 (SUM/AVG/MIN/MAX/GROUP_CONCAT) | alopex-sql | **ws v0.7.2** | なし | 各集約の DISTINCT が型受理され正しい値を返す。#3 と同時 |
| 5 | 汎用スカラー関数 + 関数レジストリ基盤 (#6a/#6b を内包) | alopex-sql, alopex-core (#6b 計測) | **ws v0.7.3** | なし(追加のみ) | レジストリ導入、v0.5.3 カタログの数値/三角/文字列/正規表現/条件/型関数が動作。**同一リリース内で段階実装**: レジストリ → 数値/文字列/条件/型 → ハッシュ/UUID/エンコード (旧#6a) → システム関数+PRAGMA (旧#6b) |
| 9 | 分散プラン (Exchange/Repartition/ScatterGather) | alopex-sql | **ws v0.9.0** | あり(LogicalPlan) | DistributedPlanner が論理→ScatterGather 変換。#3 完了が前提 |
| 10a | cluster metadata contracts + ルーティング simulation | alopex-cluster | **ws v0.7.0** | — | ✅ **リリース済**（3151行、`simulated_harness.rs`） |
| 10b | cluster 本実装 (remote execution / Raft / 分散 txn) | alopex-cluster | **DB v0.8 (本来予定・B-4)** | なし(未公開) | Chirps Mesh 越しのリモート実行。**v0.8.0 の元計画** |
| D1 | **Cargo.toml 版を実公開版 (0.7.0) に追随** | 全クレート | **v0.7.2 の前段** | — | crates.io 0.7.0 公開済みなのに Cargo.toml が 0.6.0 の不整合を是正。workspace 継承版・独立版 (sql/dataframe) を 0.7.0 起点に揃えてから v0.7.2 へ bump |

**注記（債務を v0.8.0 に繰り越さない原則）**:
- **v0.7.0 でやるべきだった機能（#3/#4/#5）は、すべて v0.7.x パッチ系列で完済する。** これらは「v0.7 の実装漏れ」であり、新バージョンの予定を消費させない。
- **公開バージョンは「公開に見合う区切り」で切る（内部の実装段階と 1:1 対応させない）。** #5 と旧 #6a/#6b は**すべて v0.5.3 カタログの後方互換なスカラー関数追加**であり機能的に同質。これを 3 つの公開リリース (v0.7.3/v0.7.4/v0.7.5) に分割する根拠は「レジストリを先に入れる」という**内部の実装順序**でしかなく、公開リリースを分ける理由にはならない。crates.io は yank のみで取り消し不可、publish は 7 クレート + PyPI の全自動 CI が走るオーバーヘッドを伴う。したがって **#5/#6a/#6b は v0.7.3 の単一公開リリースに統合**し、内部は「レジストリ → 数値/文字列/条件/型 → ハッシュ/UUID/エンコード → システム関数+PRAGMA」と段階実装する（各段階の実装順序制約＝レジストリ先行は spec の tasks 内で担保）。
- **v0.8.0 は本来「Metadata Raft + 分散クエリ本実装（B-4/#10b）」の予定**（[alopex-milestones.md](./alopex-milestones.md) DB v0.8 行）。この予定は動かさない。債務是正を混ぜない。
- v0.7.1（作業中）= 依存/セキュリティ。**v0.7.2 以降のパッチで機能債務を順に完済**する。
- #3 は trait へのメソッド追加＝破壊的変更だが、0.x のパッチ内で許容（外部安定 API 契約が確立する前）。
- #9（分散プラン）は #3 完了が前提のため v0.9.0（既存ロードマップの Distributed Query Planner）に据え置き。これは債務ではなく元々の計画。
- **D1（Cargo.toml 版の追随）は v0.7.2 の前段で必須**。crates.io は全 Rust クレート 0.7.0 公開済みなのに Cargo.toml が 0.6.0 という作業ツリーの不整合を、v0.7.2 bump 前に是正する。
- #5（#6a/#6b を内包）は系統A（単一ノード・Chirps 非依存）。#3 と独立に並行可能。**関数レジストリを先に入れてから残りの関数群を載せる**（レジストリ無しで関数を足すと巨大 match が再び肥大）という順序制約は、公開バージョンではなく **v0.7.3 spec の tasks 内の Phase 順序**で担保する。
- #5 の spec（requirements/design/tasks）は着手前に起こすことを DoD の前提とする。ハッシュ/UUID/エンコード・システム関数/PRAGMA も同 spec のスコープに含める。

## 3. 系統別・バージョン別の全体割り付け

漏れ債務と既存ロードマップを統合した、クレート横断のタイムライン。空欄は「そのバージョンでは着手しない」を意味する（明示的スコープ外）。

> バージョンはワークスペース統一版（ws）。

### 系統A: SQL言語・ライブラリ関数（単一ノード・Chirps 非依存）

| ws版 | 機能 | 担当 | 状態 |
|---|---|---|---|
| v0.5.0 | GROUP BY / HAVING / 集約8種 | alopex-sql | ✅ リリース済 |
| v0.6.0 | JOIN 5種 / Subquery | alopex-sql (+core プリミティブ) | ✅ リリース済 |
| v0.7.0 | cluster metadata + ルーティング simulation | alopex-cluster ほか | ✅ リリース済 (PyPI/tag) |
| **v0.7.1** | 依存近代化・セキュリティ修正 (pyo3/object_store/rustls) | 全クレート | 🔧 **作業中 (rc/v0.7.1)** |
| **v0.7.2** | **#3 部分状態集約器 + #4 DISTINCT 集約** | alopex-sql + alopex-core | 🔴 債務・最優先 |
| **v0.7.3** | **#5 汎用スカラー関数 + レジストリ基盤 (v0.5.3 カタログ全体: 数値/三角/文字列/正規表現/条件/型 + ハッシュ/UUID/エンコード + システム関数/PRAGMA)** | alopex-sql (+ alopex-core 計測) | 🔴 債務 |
| **v0.8.0** | **Metadata Raft + 分散クエリ本実装 (本来予定・温存)** | alopex-cluster + alopex-sql | ⏳ 元計画 |
| v0.8.x | 日付・時刻関数 (v0.5.4 カタログ) 等の新規 | alopex-sql | ⏳ 新規 |
| v1.0.0 | Query Optimizer (コストベース) | alopex-sql | ⏳ 新規 |

> **v0.7.0 の実装漏れ（#3-#6）は v0.7.x パッチ系列で完済する。v0.8.0 に繰り越さない。** v0.7.1 は依存/セキュリティ（RUSTSEC-2026-0176/0177/0104/0099/0098、pyo3 0.24→0.29 / rustls 0.21→0.23）で埋まっているため、機能債務は v0.7.2 以降に配置。**スカラー関数群（#5/#6a/#6b）は同質の後方互換追加のため v0.7.3 の単一公開リリースに統合**し、内部を段階実装する。**v0.8.0 は本来の「分散クエリ本実装」予定を温存**する。

### 系統B: クラスタ整合性（Chirps 基盤依存）

| ws版 | 機能 | 担当クレート | Chirps 依存 | 状態 |
|---|---|---|---|---|
| v0.7.0 (B-3) | cluster metadata contracts・ルーティング simulation | alopex-cluster | なし(模擬) | ✅ リリース済 |
| v0.7.2 (B-1) | 単一プロセス内 partial→final 並列 (AggregateMode) | alopex-sql | なし | #3 と同時（債務・v0.7.x で完済） |
| v0.9.0 (B-2) | #9 分散プラン表現・DistributedPlanner | alopex-sql | なし | 🔴 #3 が前提 |
| DB v0.8 (B-4) | #10b ノード跨ぎ本実装 (remote execution/IPC/RPC/failover) | alopex-cluster + alopex-sql | **Chirps Multi-Raft/TSO v0.6** | ⏳ 元計画・温存 |
| DB v0.10+ (B-5) | 汎用 shuffle / 多 Final / 分散 JOIN | alopex-cluster + alopex-sql | Chirps 成熟 | ⏳ |

> B-3 は v0.7.0 で **metadata + simulation まで完了済み**。B-1（部分状態集約器の並列化）は債務#3と同時で **v0.7.2 完済**。B-4（remote execution 本実装）は DB v0.8 の**本来予定を温存**。

### 基盤: Chirps（別リポジトリ・alopex-cluster が利用）

| Chirps版 | 機能 | 状態 |
|---|---|---|
| 現行 | Raft(単一グループ) / QUIC / SWIM | ✅ 実装済 |
| v0.6 | Multi-Raft 管理 / TSO / Gossip HLC | ⏳ 予定(B-4 の前提) |

## 4. 依存グラフ (着手順の制約)

```
債務完済 (v0.7.x パッチ系列):
  v0.7.0 ✅ ─► v0.7.1 🔧(依存/セキュリティ) ─► [v0.7.2 #3/#4 +B-1] ─► [v0.7.3 #5(+#6a/#6b 内包): レジストリ→数値/文字列/条件/型→ハッシュ→システム関数]
                                                                                                          │
本来予定 (温存・繰り越さない):                                                                            ▼
  v0.8.0 (Metadata Raft + 分散クエリ本実装 = B-4/#10b) ─► v0.9.0 (#9 分散プラン B-2) ─► v0.10+ (B-5)
                          ▲
       Chirps v0.6 (Multi-Raft/TSO) ┘

独立・即時:  C1 (crates.io を v0.7.0 に追随公開)
```

**着手順の絶対制約**:
- **債務は v0.7.x で完済し、v0.8.0 に繰り越さない。** v0.8.0 の予定（分散クエリ本実装）は動かさない。
- **v0.7.1（依存近代化・セキュリティ）を先に完結させる。** 現在 rc/v0.7.1 で作業中。ここに機能を混ぜない。
- **#3（v0.7.2）が系統B（B-1/B-2）の前提。** これを飛ばして #9 に進んではならない。
- **#5（レジストリ）を #6a/#6b より先に**（順序制約は v0.7.3 spec の tasks 内 Phase 順序で担保。公開バージョンは分けない）。
- **B-4（v0.8.0 本来予定）は Chirps v0.6 が出るまで着手不可。** それまでに v0.7.x 債務を完済しておく。
- #6a/#6b は **spec 化が着手の前提**（現在 spec 無し）。

## 5. 「今すぐやること」の限定 (実装漏れ防止の核心)

再発防止のため、着手対象を段階的に限定する。**「全部いっぺんに」は禁止。同時に、債務を v0.8.0 に繰り越すことも禁止（v0.7.x で完済）。**

- **今: v0.7.1（作業中）** — 依存近代化・セキュリティ修正のみ。機能追加は入れない。rustls の Codex レビュー結果を待って rc/v0.7.1 統合 → 最終検証。
- **次: v0.7.2** — **#3 部分状態集約器 + #4 DISTINCT 集約 + B-1 単一プロセス並列のみ**。
- **その後: v0.7.3（#5、#6a/#6b 内包）** で v0.5.3 カタログのスカラー関数群を**単一公開リリース**として完済する。内部は「レジストリ → 数値/文字列/条件/型 → ハッシュ/UUID/エンコード → システム関数/PRAGMA」と段階実装するが、公開は 1 回（同質の後方互換追加を無駄に分割せず、publish/yank 不可のオーバーヘッドを避ける）。
- **v0.8.0 は温存**: 本来予定の「Metadata Raft + 分散クエリ本実装」。債務を混ぜない。
- **並行で C1**（crates.io を v0.7.0 に追随公開）— 独立に即時実施可能。
- **各パッチの着手前ゲート**: spec（requirements/design/tasks）を起こし、**ロードマップの約束を tasks が全網羅しているか照合する**（#3 の merge が過去に脱落した原因の是正）。

## 6. 運用ルール (実装漏れの構造的再発防止)

gap-audit §6 の教訓を割り付け運用に反映する。

1. **spec 承認時に「対応ロードマップ項目の全要件を tasks が網羅」を照合する。** ロードマップ→spec で縮小が起きたら承認しない。
2. **バージョン完了の定義に「割り付け表の当該行の DoD 達成」を含める。** 番号を進める条件を DoD に紐付ける。
3. **crate description と実装実態の整合を release 前に確認する。** "Distributed cluster coordination" のような名目先行を残さない。
4. **この割り付け表を単一の真実とする。** 新機能は必ずこの表に「クレート×バージョン×DoD」で追記してから着手する。

---

### 参照
- 漏れの棚卸し: `docs-public/design/distributed-implementation-gap-audit.md`
- 分散設計: `docs-public/design/distributed-query-execution-design.md`
- 既存ロードマップ: `docs-public/roadmap/alopex-sql-milestone.md`, `docs-public/roadmap/alopex-milestones.md`
- クレート責務: 各 `alopex/crates/*/Cargo.toml` の description
