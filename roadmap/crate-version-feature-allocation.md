# クレート × バージョン × 機能 割り付け表 (Feature Allocation Matrix)

> Status: **割り付け提案** / 2026-07-16 (v0.7.3 公開・検証完了を反映)
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

### 1.1 実リリース状況 (2026-07-14、crates.io/PyPI/git を観測で確定)

**v0.7.0・v0.7.1 は crates.io・PyPI 両方で公開済み。** 製品バージョンは v0.7 系に入っている。**v0.7.1 に、リリース後の実機検証 (crates.io 公開版のみを使う検証コンテナ) で 2 件の重大バグが判明した**: (a) `alopex-sql` の `build.rs` が出す rpath 指定 (`cargo:rustc-link-arg`) が依存クレートの build script からは最終バイナリへ伝播しない cargo の仕様により、`alopex-cli`/`alopex-server`/`alopex-py` の配布バイナリが `LD_LIBRARY_PATH` なしでは起動できない、(b) `alopex-sql` の Nim SQL パーサー共有ライブラリがビルド済みバイナリとして同梱されておらず、Nim ツールチェーンを持たない環境では `cargo install`/`cargo build` 自体が失敗する。**both は crates.io のバージョン不変性 (同一番号の再 publish 不可) のため v0.7.1 自体を差し替えられず、v0.7.2 を新機能なしの緊急修正版として割り込ませる。** これにより本来 v0.7.2 だった「#3 部分状態集約器」以降のパッチ番号を 1 つずつ繰り下げる (旧 v0.7.2→v0.7.3、旧 v0.7.3→v0.7.4)。

| クレート | 実公開版 (crates.io/PyPI) | Cargo.toml 版定義 | 版定義の種別 |
|---|---|---|---|
| alopex-core | crates.io **0.7.1** | `0.7.1` | workspace 継承 |
| alopex-sql | crates.io **0.7.1** | `0.7.1` | **独立指定** |
| alopex-dataframe | crates.io **0.7.1** | `0.7.1` | **独立指定** |
| alopex-embedded | crates.io **0.7.1** | `0.7.1` | workspace 継承 |
| alopex-server | crates.io **0.7.1** | `0.7.1` | workspace 継承 |
| alopex-cli | crates.io **0.7.1** | `0.7.1` | workspace 継承 |
| alopex-cluster | crates.io **0.7.1** | `0.7.1` | workspace 継承 |
| alopex-tools | crates.io **未公開** | `0.0.0` | 独立ワークスペース (issue #45 是正済み)。crates.io 公開版 alopex-embedded/alopex-sql に依存し、リリース確認コンテナの `verify-release-embedded` バイナリ等を提供。publish=false (内部ツール) |
| alopex (=alopex-py) | PyPI **0.7.1** | `0.7.1` | **独立指定** |

**★バージョンはクレートごとに独立管理。「ワークスペース統一」は誤り★**:
- workspace 継承 (`version.workspace = true`): core / cluster / embedded / server / cli
- **独立指定** (Cargo.toml に `version = "..."`): **alopex-sql / alopex-dataframe / alopex-py**
- 公開クレートで独自にバージョン進捗するものがある (例: dataframe は 0.2.0 → 0.6.0 に飛んだ)。「全部を同一版で揃える」前提は禁止。**どのクレートがどの版でどの機能を持つべきかを本表で個別管理する**。

**過去の不整合 (v0.7.1 で是正済み)**:
- crates.io は全 Rust クレート 0.7.0 公開済みなのに、リポジトリの Cargo.toml が 0.6.0 のままだった不整合 (債務 D1) は v0.7.1 で解消済み。全クレート Cargo.toml が実公開版 0.7.1 と一致している。
- 過去の割り付け表に記した「C1: crates.io が v0.7.0 未公開」は**誤り**だった (crates.io は公開済み)。C1 は撤回済み。

**#3 部分状態集約器の実装漏れは v0.7.0/v0.7.1 でも継続** (集約器 `Accumulator` は `update`/`finalize` のみ)。これが v0.7.3 spec の是正対象。alopex-cluster は v0.7.0 で「metadata contracts + simulation」まで (remote execution/Raft/分散 txn は未実装＝B-4 残債務)。

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
| 3 | 集約器 `state()`/`merge()` 追加 | alopex-sql (trait), alopex-core (マージ演算) | **ws v0.7.3** | あり(trait) | ✅ 公開・検証済み。全8集約器が state/merge 実装、AVG=(sum,count)化、単一プロセス内 partial→final が単一パスと同結果 |
| 4 | DISTINCT 集約 (SUM/AVG/MIN/MAX/GROUP_CONCAT) | alopex-sql | **ws v0.7.3** | なし | ✅ 公開・検証済み。各集約の DISTINCT が型受理され正しい値を返す。#3 と同時 |
| 5 | 汎用スカラー関数 + 関数レジストリ基盤 (#6a/#6b を内包) | alopex-sql, alopex-core (#6b 計測) | **ws v0.7.4** | なし(追加のみ) | レジストリ導入、v0.5.3 カタログの数値/三角/文字列/正規表現/条件/型関数が動作。**公開は v0.7.4 の1回**だが、範囲が広いため**実装 spec は3分割**: (A) `registry-scalars`=レジストリ基盤+v0.5.3、(B) `hash-encode`=v0.5.1 ハッシュ/UUID/エンコード、(C) `system-pragma`=v0.5.2 システム関数+PRAGMA。A→B/C の順 (A が基盤)。**C 完了時に v0.7.4 を1回公開**する。C は公開担当として、**issue #45 (alopex-tools 比較ベンチ) 完了を前提に新関数を SQL 比較ベンチ (Phase 1 埋め込み型) へ反映・検証**し、**デモ/検証スクリプト・チュートリアル等の公開情報を更新**する工程まで含む (#45 の publish 方針が確定したら v0.7.4 リリースの publish 対象がそれに追随) |
| 9 | 分散プラン (Exchange/Repartition/ScatterGather) | alopex-sql | **ws v0.9.0** | あり(LogicalPlan) | DistributedPlanner が論理→ScatterGather 変換。#3 完了が前提 |
| 10a | cluster metadata contracts + ルーティング simulation | alopex-cluster | **ws v0.7.0** | — | ✅ **リリース済**（3151行、`simulated_harness.rs`） |
| 10b | cluster 本実装 (remote execution / Raft / 分散 txn) | alopex-cluster | **DB v0.8 (本来予定・B-4)** | なし(未公開) | Chirps Mesh 越しのリモート実行。**v0.8.0 の元計画** |
| D1 | **Cargo.toml 版を実公開版 (0.7.0) に追随** | 全クレート | **v0.7.1** | — | ✅ **是正済**。crates.io 0.7.0 公開済みなのに Cargo.toml が 0.6.0 の不整合を v0.7.1 で是正 |
| D2 | **rpath 伝播バグ + Nim ツールチェーン非依存化 (vendoring)** | alopex-sql (build.rs), alopex-cli/server/py (rpath 消費側 build.rs) | **ws v0.7.2** | なし(ビルド設定のみ) | ✅ 公開・検証済み。(a) `alopex-cli`/`alopex-server`/`alopex-py` が `LD_LIBRARY_PATH` なしで起動できる。(b) `alopex-sql` の crates.io 公開版が Nim ツールチェーン無しで `cargo install` 可能。新機能を含まない緊急修正のみ |

**注記（債務を v0.8.0 に繰り越さない原則）**:
- **v0.7.0 でやるべきだった機能（#3/#4/#5）は、すべて v0.7.x パッチ系列で完済する。** これらは「v0.7 の実装漏れ」であり、新バージョンの予定を消費させない。
- **2つの軸を分ける: 「公開バージョン」と「実装 spec」は別物。**
  - **公開バージョン軸**: #5 と旧 #6a/#6b は**すべて v0.5.x カタログの後方互換なスカラー関数追加**であり機能的に同質。これを 3 つの公開リリース (旧 v0.7.4/v0.7.4/v0.7.5) に分割する根拠は「レジストリを先に入れる」という**内部の実装順序**でしかなく、公開リリースを分ける理由にはならない。crates.io は yank のみで取り消し不可、publish は 7 クレート + PyPI の全自動 CI が走るオーバーヘッドを伴う。したがって **公開は v0.7.4 の 1 回に統合**する。
  - **実装 spec 軸**: ただし 3 カタログ (v0.5.3 + v0.5.1 + v0.5.2) を 1 spec に畳むと範囲が広すぎて実装・レビュー・検証が破綻する。よって **spec は 3 分割**する: (A) `alopex-sql-v0-7-3-registry-scalars` = レジストリ基盤 + v0.5.3、(B) `alopex-sql-v0-7-3-hash-encode` = v0.5.1 ハッシュ/UUID/エンコード、(C) `alopex-sql-v0-7-3-system-pragma` = v0.5.2 システム関数 + PRAGMA。各 spec は独立に requirements/design/tasks/承認/実装を回す。**A が基盤で B/C の前提**（レジストリ先行）。**公開 (crates.io/PyPI publish) は C 完了時の v0.7.4 タグ 1 回のみ**で、A/B は公開せず後続 spec の土台として main に積む。
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
| **v0.7.2** | **D2: rpath 伝播バグ修正 + Nim vendoring (緊急パッチ、新機能なし)** | alopex-sql, alopex-cli/server/py | ✅ リリース済 |
| **v0.7.3** | **#3 部分状態集約器 + #4 DISTINCT 集約** | alopex-sql + alopex-core | ✅ 公開・検証済み |
| **v0.7.4** | **#5 汎用スカラー関数 + レジストリ基盤 (v0.5.3 カタログ全体: 数値/三角/文字列/正規表現/条件/型 + ハッシュ/UUID/エンコード + システム関数/PRAGMA)** | alopex-sql (+ alopex-core 計測) | 🔴 債務 |
| **v0.8.0** | **Metadata Raft + 分散クエリ本実装 (本来予定・温存)** | alopex-cluster + alopex-sql | ⏳ 元計画 |
| v0.8.x | 日付・時刻関数 (v0.5.4 カタログ) 等の新規 | alopex-sql | ⏳ 新規 |
| v1.0.0 | Query Optimizer (コストベース) | alopex-sql | ⏳ 新規 |

> **v0.7.0 の実装漏れ（#3-#6）は v0.7.x パッチ系列で完済する。v0.8.0 に繰り越さない。** v0.7.1 は依存/セキュリティ（RUSTSEC-2026-0176/0177/0104/0099/0098、pyo3 0.24→0.29 / rustls 0.21→0.23）で埋まっている。**v0.7.1 リリース後の実機検証で判明した D2 (rpath 伝播バグ + Nim vendoring) は v0.7.2 として緊急割り込みで是正**し、機能債務は v0.7.3 以降に配置。**スカラー関数群（#5/#6a/#6b）は同質の後方互換追加のため公開は v0.7.4 の 1 回に統合**し、範囲が広いため**実装 spec は 3 分割**（registry-scalars → hash-encode / system-pragma）する。**v0.8.0 は本来の「分散クエリ本実装」予定を温存**する。

### 系統B: クラスタ整合性（Chirps 基盤依存）

| ws版 | 機能 | 担当クレート | Chirps 依存 | 状態 |
|---|---|---|---|---|
| v0.7.0 (B-3) | cluster metadata contracts・ルーティング simulation | alopex-cluster | なし(模擬) | ✅ リリース済 |
| v0.7.3 (B-1) | 単一プロセス内 partial→final 並列 (AggregateMode) | alopex-sql | なし | ✅ 公開・検証済み |
| v0.9.0 (B-2) | #9 分散プラン表現・DistributedPlanner | alopex-sql | なし | 🔴 #3 が前提 |
| DB v0.8 (B-4) | #10b ノード跨ぎ本実装 (remote execution/IPC/RPC/failover) | alopex-cluster + alopex-sql | **Chirps Multi-Raft/TSO v0.6** | ⏳ 元計画・温存 |
| DB v0.10+ (B-5) | 汎用 shuffle / 多 Final / 分散 JOIN | alopex-cluster + alopex-sql | Chirps 成熟 | ⏳ |

> B-3 は v0.7.0 で **metadata + simulation まで完了済み**。B-1（部分状態集約器の並列化）は債務#3と同時で **v0.7.3 公開・検証済み**。B-4（remote execution 本実装）は DB v0.8 の**本来予定を温存**。

### 基盤: Chirps（別リポジトリ・alopex-cluster が利用）

| Chirps版 | 機能 | 状態 |
|---|---|---|
| 現行 | Raft(単一グループ) / QUIC / SWIM | ✅ 実装済 |
| v0.6 | Multi-Raft 管理 / TSO / Gossip HLC | ⏳ 予定(B-4 の前提) |

## 4. 依存グラフ (着手順の制約)

```
債務完済 (v0.7.x パッチ系列):
  v0.7.0 ✅ ─► v0.7.1 ✅(依存/セキュリティ + D1) ─► v0.7.2 ✅(D2: rpath伝播+Nim vendoring 緊急パッチ) ─► v0.7.3 ✅(#3/#4 +B-1) ─► [v0.7.4 #5(+#6a/#6b 内包): レジストリ→数値/文字列/条件/型→ハッシュ→システム関数]
                                                                                                                                                    │
本来予定 (温存・繰り越さない):                                                                                                                      ▼
  v0.8.0 (Metadata Raft + 分散クエリ本実装 = B-4/#10b) ─► v0.9.0 (#9 分散プラン B-2) ─► v0.10+ (B-5)
                          ▲
       Chirps v0.6 (Multi-Raft/TSO) ┘
```

**着手順の絶対制約**:
- **債務は v0.7.x で完済し、v0.8.0 に繰り越さない。** v0.8.0 の予定（分散クエリ本実装）は動かさない。
- **v0.7.2（D2: rpath 伝播バグ + Nim vendoring）は完結済み。** 新機能を含まない緊急修正として分離した。
- **#3（v0.7.3）は系統B（B-1/B-2）の前提として完了済み。** 次の分散プラン #9 はこの前提の上で進める。
- **#5（レジストリ）を #6a/#6b より先に**（順序制約は 3 spec の順序 A→B/C と各 tasks 内 Phase で担保。公開バージョンは分けず v0.7.4 の 1 回）。
- **B-4（v0.8.0 本来予定）は Chirps v0.6 が出るまで着手不可。** それまでに v0.7.x 債務を完済しておく。
- #6a/#6b は **spec 化が着手の前提**（現在 spec 無し）。

## 5. 「今すぐやること」の限定 (実装漏れ防止の核心)

再発防止のため、着手対象を段階的に限定する。**「全部いっぺんに」は禁止。同時に、債務を v0.8.0 に繰り越すことも禁止（v0.7.x で完済）。**

- **完了: v0.7.2** — D2 (rpath 伝播バグ修正 + Nim vendoring) の緊急パッチのみとして完結。
- **完了: v0.7.3** — **#3 部分状態集約器 + #4 DISTINCT 集約 + B-1 単一プロセス並列のみ**として公開・検証済み。
- **次: v0.7.4（#5、#6a/#6b 内包）** で v0.5.x カタログのスカラー関数群を**単一公開リリース**として完済する。**実装 spec は 3 分割** (A registry-scalars → B hash-encode / C system-pragma) し、各 spec を独立に承認・実装するが、**公開 (crates.io/PyPI publish) は C 完了時の v0.7.4 タグ 1 回**（同質の後方互換追加を無駄に分割せず、publish/yank 不可のオーバーヘッドを避ける）。
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
