# クレート × バージョン × 機能 割り付け表 (Feature Allocation Matrix)

> Status: **実装・公開状況の記録** / 2026-07-18 (v0.7.4公開後に更新)
> 目的: 実装漏れ債務と今後の機能を、担当クレートと着手バージョンに **1つずつ明示配置** する。
> 「全部いっぺんに」を禁じ、各機能に責任クレートと期日を持たせることで実装漏れの再発を防ぐ。
> 関連: [distributed-implementation-gap-audit.md](../design/distributed-implementation-gap-audit.md)（漏れの棚卸し）,
> [distributed-query-execution-design.md](../design/distributed-query-execution-design.md)（分散設計）

## 0. 原則

1. **1機能は1クレート・1バージョンに配置する。** 複数バージョンにまたがる場合は分割して別項目にする。
2. **「全部」を1バージョンに入れない。** 割り付けの無い機能は着手しない（＝スコープ外と明示）。
2.5. **「公開バージョン」と「実装 spec」は別の軸。** 公開バージョンは yank 不可・publish オーバーヘッドがあるため「公開に見合う区切り」で切る（同質な後方互換追加を無駄に分割しない）。一方、1バージョン分の実装範囲が広い場合は、公開は1回のまま**実装 spec を複数に分割**して段階実装する（例: v0.7.4 = 公開1回・spec 3分割）。内部の実装段階と公開リリースを 1:1 対応させない。
3. **各機能に受入基準（DoD）を持たせる。** 「実装した」だけでなく「何が満たされたら完了か」を定義する。
4. **依存の逆流を禁じる。** 下位（core）→上位（sql→embedded/server）の一方向。分散基盤は Chirps に依存。

## 1. クレート責務とリリース実態 (割り付けの前提)

### 1.1 実リリース状況 (2026-07-18、crates.io/PyPI/git を観測で確定)

**v0.7.0・v0.7.1 は crates.io・PyPI 両方で公開済み。** その後、v0.7.2（rpath/Nim vendoring）、v0.7.3（集約器/DISTINCT）、v0.7.4（スカラー関数群）まで公開済みである。v0.7.0のcluster-aware foundationとDataFrame P3の実装範囲、およびv0.7.xパッチで解消した債務を、将来の分散実装と混同しない。

| クレート | 実公開版 (crates.io/PyPI) | Cargo.toml 版定義 | 版定義の種別 |
|---|---|---|---|
| alopex-core | crates.io **0.7.4** | `0.7.4` | workspace 継承 |
| alopex-sql | crates.io **0.7.4** | `0.7.4` | **独立指定** |
| alopex-dataframe | crates.io **0.7.4** | `0.7.4` | **独立指定** |
| alopex-embedded | crates.io **0.7.4** | `0.7.4` | workspace 継承 |
| alopex-server | crates.io **0.7.4** | `0.7.4` | workspace 継承 |
| alopex-cli | crates.io **0.7.4** | `0.7.4` | workspace 継承 |
| alopex-cluster | crates.io **0.7.4** | `0.7.4` | workspace 継承 |
| alopex-tools | crates.io **未公開** | `0.0.0` | 独立ワークスペース (issue #45 是正済み)。crates.io 公開版 alopex-embedded/alopex-sql に依存し、リリース確認コンテナの `verify-release-embedded` バイナリ等を提供。publish=false (内部ツール) |
| alopex (=alopex-py) | PyPI **0.7.4** | `0.7.4` | **独立指定** |

**★バージョンはクレートごとに独立管理。「ワークスペース統一」は誤り★**:
- workspace 継承 (`version.workspace = true`): core / cluster / embedded / server / cli
- **独立指定** (Cargo.toml に `version = "..."`): **alopex-sql / alopex-dataframe / alopex-py**
- 公開クレートで独自にバージョン進捗するものがある (例: dataframe は 0.2.0 → 0.6.0 に飛んだ)。「全部を同一版で揃える」前提は禁止。**どのクレートがどの版でどの機能を持つべきかを本表で個別管理する**。

**過去の不整合 (v0.7.1 で是正済み)**:
- crates.io は全 Rust クレート 0.7.0 公開済みなのに、リポジトリの Cargo.toml が 0.6.0 のままだった不整合 (債務 D1) は v0.7.1 で解消済み。全クレート Cargo.toml が実公開版 0.7.1 と一致している。
- 過去の割り付け表に記した「C1: crates.io が v0.7.0 未公開」は**誤り**だった (crates.io は公開済み)。C1 は撤回済み。

**#3 部分状態集約器の実装漏れは v0.7.0/v0.7.1 に残っていたが、v0.7.3で是正済み**。alopex-cluster は v0.7.0 で「metadata contracts + simulation」までを提供し、remote execution/Raft/分散txnは未実装のままv0.8以降のB-4に残る。

### 1.2 クレート責務

Cargo.toml の description に基づく公式責務。

| クレート | 責務 | 分散における役割 |
|---|---|---|
| **alopex-core** | ストレージエンジン（LSM/columnar/vector index）、**実行プリミティブ**（hash_join, 集約プリミティブ, spill） | 単一ノードの物理演算。分散集約の**部分状態のマージ演算**もここ |
| **alopex-sql** | SQL パーサ・プランナ・エグゼキュータ（core を呼ぶ） | 論理/分散プランの生成、集約器の trait 定義、coordinator/gather ロジック |
| **alopex-cluster** (公開済み) | v0.7 cluster-aware foundation（Chirps 基盤の上） | cluster metadata、status、membership lifecycle、routing simulation。リモート実行は未実装 |
| alopex-embedded / server / py / cli | 上位インターフェース | 分散クエリの入口（透過的にルーティング） |
| (外部) **Chirps** | 合意(Raft)・通信(QUIC)・メンバーシップ(SWIM)・(v0.6)Multi-Raft/TSO | 基盤。alopex-cluster が利用 |

## 2. 実装漏れ債務の割り付け (最優先)

[gap-audit](../design/distributed-implementation-gap-audit.md) の10項目を、担当クレートと是正バージョンへ配置する。

> バージョンはワークスペース統一版（§1.1）。**債務は v0.7.x パッチ系列で完済する（v0.8.0 に繰り越さない）。** v0.7.0 でやるべきだった実装漏れは「v0.7 の未完」であり、v0.7 系列内で埋める。**v0.8.0 の本来予定（分散クエリ本実装 = B-4）は温存し、債務で汚染しない。**

| # | 機能 | 担当クレート | 是正バージョン | 破壊的変更 | 受入基準 (DoD) |
|---|---|---|---|---|---|
| 3 | 集約器 `state()`/`merge()` 追加 | alopex-sql (trait), alopex-core (マージ演算) | **ws v0.7.3** | あり(trait) | 全8集約器が state/merge 実装、AVG=(sum,count)化、単一プロセス内 partial→final が単一パスと同結果 |
| 4 | DISTINCT 集約 (SUM/AVG/MIN/MAX/GROUP_CONCAT) | alopex-sql | **ws v0.7.3** | なし | 各集約の DISTINCT が型受理され正しい値を返す。#3 と同時 |
| 5 | 汎用スカラー関数 + 関数レジストリ基盤 (#6a/#6b を内包) | alopex-sql, alopex-core (#6b 計測) | **ws v0.7.4** | なし(追加のみ) | ✅ **完済・公開済**。レジストリ導入、v0.5.3 カタログの数値/三角/文字列/正規表現/条件/型関数、v0.5.1 ハッシュ/UUID/エンコード、v0.5.2 システム関数/PRAGMA を実装。**公開は v0.7.4 の1回**、実装 spec は3分割 (A) `registry-scalars` → (B) `hash-encode` / (C) `system-pragma`。比較ベンチは **#45とは独立に**既存 `alopex-sql` Criterion ベンチを拡張して実施し、デモ/検証スクリプトと公開情報を更新した。 |
| 9 | 分散プラン (Exchange/Repartition/ScatterGather) | alopex-sql | **ws v0.9.0** | あり(LogicalPlan) | DistributedPlanner が論理→ScatterGather 変換。#3 完了が前提 |
| 10a | cluster metadata contracts + ルーティング simulation | alopex-cluster | **ws v0.7.0** | — | ✅ **リリース済**（3151行、`simulated_harness.rs`） |
| 10b | cluster 本実装 (remote execution / Raft / 分散 txn) | alopex-cluster | **DB v0.8 (本来予定・B-4)** | なし(未公開) | Chirps Mesh 越しのリモート実行。**v0.8.0 の元計画** |
| D1 | **Cargo.toml 版を実公開版 (0.7.0) に追随** | 全クレート | **v0.7.1** | — | ✅ **是正済**。crates.io 0.7.0 公開済みなのに Cargo.toml が 0.6.0 の不整合を v0.7.1 で是正 |
| D2 | **rpath 伝播バグ + Nim ツールチェーン非依存化 (vendoring)** | alopex-sql (build.rs), alopex-cli/server/py (rpath 消費側 build.rs) | **ws v0.7.2** | なし(ビルド設定のみ) | (a) `alopex-cli`/`alopex-server`/`alopex-py` が `LD_LIBRARY_PATH` なしで起動できる (RUNPATH 実機確認済み ✅)。(b) `alopex-sql` の crates.io 公開版に対象別 vendored バイナリを同梱し、Nim ツールチェーン無しで利用できることを公開版検証済み ✅。新機能を含まない緊急修正 |

**注記（債務を v0.8.0 に繰り越さない原則）**:
- **v0.7.0 でやるべきだった機能（#3/#4/#5）は、すべて v0.7.x パッチ系列で完済する。** これらは「v0.7 の実装漏れ」であり、新バージョンの予定を消費させない。
- **2つの軸を分ける: 「公開バージョン」と「実装 spec」は別物。**
  - **公開バージョン軸**: #5 と旧 #6a/#6b は**すべて v0.5.x カタログの後方互換なスカラー関数追加**であり機能的に同質。これを 3 つの公開リリース (旧 v0.7.4/v0.7.4/v0.7.5) に分割する根拠は「レジストリを先に入れる」という**内部の実装順序**でしかなく、公開リリースを分ける理由にはならない。crates.io は yank のみで取り消し不可、publish は 7 クレート + PyPI の全自動 CI が走るオーバーヘッドを伴う。したがって **公開は v0.7.4 の 1 回に統合**する。
  - **実装 spec 軸**: ただし 3 カタログ (v0.5.3 + v0.5.1 + v0.5.2) を 1 spec に畳むと範囲が広すぎて実装・レビュー・検証が破綻する。よって **spec は 3 分割**する: (A) `alopex-sql-v0-7-4-registry-scalars` = レジストリ基盤 + v0.5.3、(B) `alopex-sql-v0-7-4-hash-encode` = v0.5.1 ハッシュ/UUID/エンコード、(C) `alopex-sql-v0-7-4-system-pragma` = v0.5.2 システム関数 + PRAGMA。各 spec は独立に requirements/design/tasks/承認/実装を回す。**A が基盤で B/C の前提**（レジストリ先行）。**公開 (crates.io/PyPI publish) は C 完了時の v0.7.4 タグ 1 回のみ**で、A/B は公開せず後続 spec の土台として main に積む。
- **v0.8.0 は本来「Metadata Raft + 分散クエリ本実装（B-4/#10b）」の予定**（[alopex-milestones.md](./alopex-milestones.md) DB v0.8 行）。この予定は動かさない。債務是正を混ぜない。
- **v0.7.1（依存/セキュリティ）は✅完了・公開済み。** リリース後の実機検証で D2 (rpath 伝播バグ + Nim vendoring) が判明し、v0.7.2 として緊急割り込み。**v0.7.3 以降のパッチで機能債務を順に完済**する。
- #3 は trait へのメソッド追加＝破壊的変更だが、0.x のパッチ内で許容（外部安定 API 契約が確立する前）。
- #9（分散プラン）は #3 完了が前提のため v0.9.0（既存ロードマップの Distributed Query Planner）に据え置き。これは債務ではなく元々の計画。
- **D1（Cargo.toml 版の追随）は v0.7.1 で是正済み。D2（rpath 伝播バグ + Nim vendoring）は v0.7.2 で是正、v0.7.3 の前段として必須。**
- #5（#6a/#6b を内包）は系統A（単一ノード・Chirps 非依存）。#3 と独立に並行可能。**関数レジストリを先に入れてから残りの関数群を載せる**（レジストリ無しで関数を足すと巨大 match が再び肥大）という順序制約は、公開バージョンではなく **3 spec の順序 (A registry-scalars → B hash-encode / C system-pragma) と、各 spec の tasks 内 Phase 順序**で担保する。
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
| v0.7.1 | 依存近代化・セキュリティ修正 (pyo3/object_store/rustls) + D1 (Cargo.toml 版整合) | 全クレート | ✅ リリース済 |
| **v0.7.2** | **D2: rpath 伝播バグ修正 + Nim vendoring (緊急パッチ、新機能なし)** | alopex-sql, alopex-cli/server/py | ✅ リリース済み |
| **v0.7.3** | **#3 部分状態集約器 + #4 DISTINCT 集約** | alopex-sql + alopex-core | ✅ リリース済み |
| **v0.7.4** | **#5 汎用スカラー関数 + レジストリ基盤 (v0.5.3 カタログ全体: 数値/三角/文字列/正規表現/条件/型 + ハッシュ/UUID/エンコード + システム関数/PRAGMA)** | alopex-sql (+ alopex-core 計測) | ✅ **完済・公開済** |
| **v0.8.0** | **Metadata Raft + 分散クエリ本実装 (本来予定・温存)** | alopex-cluster + alopex-sql | ⏳ 元計画 |
| v0.8.x | 日付・時刻関数 (v0.5.4 カタログ) 等の新規 | alopex-sql | ⏳ 新規 |
| v1.0.0 | Query Optimizer (コストベース) | alopex-sql | ⏳ 新規 |

> **v0.7.0 の実装漏れ（#3-#6）は v0.7.x パッチ系列で完済する。v0.8.0 に繰り越さない。** v0.7.1 は依存/セキュリティ（RUSTSEC-2026-0176/0177/0104/0099/0098、pyo3 0.24→0.29 / rustls 0.21→0.23）で埋まっている。**v0.7.1 リリース後の実機検証で判明した D2 (rpath 伝播バグ + Nim vendoring) は v0.7.2 として緊急割り込みで是正**し、機能債務は v0.7.3 以降に配置。**スカラー関数群（#5/#6a/#6b）は同質の後方互換追加のため公開は v0.7.4 の 1 回に統合**し、範囲が広いため**実装 spec は 3 分割**（registry-scalars → hash-encode / system-pragma）する。**v0.8.0 は本来の「分散クエリ本実装」予定を温存**する。

### 系統B: クラスタ整合性（Chirps 基盤依存）

| ws版 | 機能 | 担当クレート | Chirps 依存 | 状態 |
|---|---|---|---|---|
| v0.7.0 (B-3) | cluster metadata contracts・ルーティング simulation | alopex-cluster | なし(模擬) | ✅ リリース済 |
| v0.7.3 (B-1) | 単一プロセス内 partial→final 並列 (AggregateMode) | alopex-sql | なし | #3 と同時（債務・v0.7.x で完済） |
| v0.9.0 (B-2) | #9 分散プラン表現・DistributedPlanner | alopex-sql | なし | 🔴 #3 が前提 |
| DB v0.8 (B-4) | #10b ノード跨ぎ本実装 (remote execution/IPC/RPC/failover) | alopex-cluster + alopex-sql | **Chirps Multi-Raft/TSO v0.6** | ⏳ 元計画・温存 |
| DB v0.10+ (B-5) | 汎用 shuffle / 多 Final / 分散 JOIN | alopex-cluster + alopex-sql | Chirps 成熟 | ⏳ |

> B-3 は v0.7.0 で **metadata + simulation まで完了済み**。B-1（部分状態集約器の並列化）は債務#3と同時で **v0.7.3 完済**。B-4（remote execution 本実装）は DB v0.8 の**本来予定を温存**。

### 基盤: Chirps（別リポジトリ・alopex-cluster が利用）

| Chirps版 | 機能 | 状態 |
|---|---|---|
| 現行 | Raft(単一グループ) / QUIC / SWIM | ✅ 実装済 |
| v0.6 | Multi-Raft 管理 / TSO / Gossip HLC | ⏳ 予定(B-4 の前提) |

## 4. 依存グラフ (着手順の制約)

```
債務完済 (v0.7.x パッチ系列):
  v0.7.0 ✅ ─► v0.7.1 ✅(依存/セキュリティ + D1) ─► v0.7.2 ✅(D2: rpath伝播+Nim vendoring 緊急パッチ) ─► v0.7.3 ✅(#3/#4 +B-1) ─► [v0.7.4 ✅ #5(+#6a/#6b 内包): レジストリ→数値/文字列/条件/型→ハッシュ→システム関数]
                                                                                                                                                    │
本来予定 (温存・繰り越さない):                                                                                                                      ▼
  v0.8.0 (Metadata Raft + 分散クエリ本実装 = B-4/#10b) ─► v0.9.0 (#9 分散プラン B-2) ─► v0.10+ (B-5)
                          ▲
       Chirps v0.6 (Multi-Raft/TSO) ┘
```

**着手順の絶対制約**:
- **債務は v0.7.x で完済し、v0.8.0 に繰り越さない。** v0.8.0 の予定（分散クエリ本実装）は動かさない。
- **v0.7.2（D2: rpath 伝播バグ + Nim vendoring）を先に完結させる。** 新機能を含まない緊急修正のみ。ここに機能を混ぜない。
- **#3（v0.7.3）が系統B（B-1/B-2）の前提。** これを飛ばして #9 に進んではならない。
- **#5（レジストリ）を #6a/#6b より先に**（順序制約は 3 spec の順序 A→B/C と各 tasks 内 Phase で担保。公開バージョンは分けず v0.7.4 の 1 回）。
- **B-4（v0.8.0 本来予定）は Chirps v0.6 が出るまで着手不可。** それまでに v0.7.x 債務を完済しておく。
- #6a/#6b は v0.7.4のspec分割（hash-encode / system-pragma）として実装・公開済み。

## 5. 完了済み債務と今後の境界 (実装漏れ防止の核心)

再発防止のため、着手対象を段階的に限定する。**「全部いっぺんに」は禁止。同時に、債務を v0.8.0 に繰り越すことも禁止（v0.7.x で完済）。**

- **完了: v0.7.2** — D2 (rpath 伝播バグ修正 + Nim vendoring)。
- **完了: v0.7.3** — **#3 部分状態集約器 + #4 DISTINCT 集約 + B-1 単一プロセス並列**。
- **完了: v0.7.4（#5、#6a/#6b 内包）** — v0.5.xカタログのスカラー関数群を単一公開リリースとして出荷。実装specは3分割したが、公開はv0.7.4の1回である。
- **v0.8.0 は温存**: 本来予定の「Metadata Raft + 分散クエリ本実装」。債務を混ぜない。
- **各パッチの着手前ゲート**: spec（requirements/design/tasks）を起こし、**ロードマップの約束を tasks が全網羅しているか照合する**（#3 の merge が過去に脱落した原因の是正）。

## 6. 運用ルール (実装漏れの構造的再発防止)

gap-audit §6 の教訓を割り付け運用に反映する。

1. **spec 承認時に「対応ロードマップ項目の全要件を tasks が網羅」を照合する。** ロードマップ→spec で縮小が起きたら承認しない。
2. **バージョン完了の定義に「割り付け表の当該行の DoD 達成」を含める。** 番号を進める条件を DoD に紐付ける。
3. **crate description と実装実態の整合を release 前に確認する。** "Distributed cluster coordination" のような名目先行を残さない。
4. **この割り付け表を単一の真実とする。** 新機能は必ずこの表に「クレート×バージョン×DoD」で追記してから着手する。
5. **CI green は「配布物が動く」ことの証明にならない。** v0.7.1 は CI 上のソースビルド・開発環境(Nim ツールチェーン常在、環境変数手動設定)では全チェック green だったが、crates.io/PyPI から公開版のみを取得する経路では起動不能・ビルド不能という2つの重大バグ(D2)を抱えたまま公開された。FFI/非標準ビルド依存を持つクレートは、リリース前に「公開レジストリからのみ取得して動かす」検証(`scripts/release/verify-release/`)を通す。
6. **依存の大規模アップグレードは体系的に洗い出してから着手する。** 1つのビルドエラーを直しては次のエラーに当たる、という行き当たりばったりの進め方は連鎖的な破壊的変更(tonic→axum→tower→prost)を見落とす。着手前に対象パッケージの公式リポジトリで正確な依存要求を確認する。
7. **既存の技術的負債(重複依存等)を発見したら、その場で解消する。** 「今回のスコープ外」として先送りしない。特にディスク膨張のように過去に実際の障害を起こしたクラスの問題(v0.7.1 の reqwest 重複)は、発見した時点で根本修正する。

---

### 参照
- 漏れの棚卸し: `docs-public/design/distributed-implementation-gap-audit.md`
- 分散設計: `docs-public/design/distributed-query-execution-design.md`
- 既存ロードマップ: `docs-public/roadmap/alopex-sql-milestone.md`, `docs-public/roadmap/alopex-milestones.md`
- クレート責務: 各 `alopex/crates/*/Cargo.toml` の description
