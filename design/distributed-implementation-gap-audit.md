# 分散クエリ実装漏れ 棚卸し (Implementation Gap Audit)

> Status: **監査結果 (事実整理)** / 2026-07-14
> 対象: リリース済み alopex-sql v0.5.0 / v0.6.0（crates.io 公開版）
> 目的: 分散DBとして約束された機構が、実装漏れのままリリースが進んでいる状況を整理する
> 関連: [distributed-query-execution-design.md](./distributed-query-execution-design.md)（漏れを埋める設計）

## 0. 背景 — なぜこの棚卸しが必要か

alopex-sql は crates.io に **v0.5.0（2026-01-28）**、**v0.6.0（2026-07-08）** をリリース済み。両バージョンとも spec の tasks は「全て完了 `[x]`」となっている。

しかし alopex-db は**分散データベース**を標榜する。そして分散クエリの正しさに必須の機構（部分状態を持つ集約器＝`state()`/`merge()`）が、**ロードマップでは約束されていたにもかかわらず、実際のリリースからは脱落したまま「完了」扱いで進んでいる**。

本文書は「約束（ロードマップ・spec）」と「実態（リリース済みコード）」を突き合わせ、実装漏れを台帳化する。これは新機能の提案ではなく、**既にリリースされたものに対する債務の可視化**である。

## 1. リリース事実 (crates.io)

crates.io API で確認（2026-07-14）。

| バージョン | 公開日 | 状態 |
|---|---|---|
| 0.6.0 | 2026-07-08 | 最新・yank なし |
| 0.5.0 | 2026-01-28 | yank なし |
| 0.4.x | 2026-01 | — |
| 0.3.x | 2025-12〜 | — |

v0.5.0（集約）も v0.6.0（JOIN/Subquery）も**リリース済み**。実装漏れは未リリース機能の話ではなく、**世に出たコードの欠落**である。

## 2. 最重要の実装漏れ — 集約器の部分状態 (state/merge)

### 約束
ロードマップ `docs-public/roadmap/alopex-sql-milestone.md:636-650` の Accumulator trait は **`merge(&mut self, other: &Self)` を含む**設計として書かれていた。これは将来の分散/並列部分集約を想定した形状である。

### 実態
リリース済み v0.6.0（git tag `v0.6.0`）の `crates/alopex-sql/src/executor/query/aggregate.rs:87-94` の `Accumulator` trait は:
- `update(&mut self, Option<SqlValue>)` / `finalize(&self)` / `clone_box(&self)` の **3つのみ**。
- **`state()`（部分状態の出力）と `merge()`（部分状態の統合）が存在しない。**

### 脱落の経緯（事実）
v0.5.0 spec の tasks.md（`.spec-workflow/archive/specs/alopex-sql-v0-5-0/tasks.md` タスク2.2, 96行）の Accumulator trait は、**最初から `update/finalize/clone_box` のみ**で `merge` を含んでいなかった。すなわち、ロードマップ（約束）→ spec tasks（縮小）→ 実装（縮小のまま）→ リリース、という流れで **spec 化の段階で `merge` が落ち、その縮小版が「完了」として承認・リリースされた**。

### 影響
- **分散集約が原理的に不可能。** 部分状態を吐けない・統合できない集約器では、複数ノードの部分結果を正しく最終集約できない（§2.2 で AVG が (sum,count) 状態を運べないと分散不可）。
- 単一プロセス内の並列集約（partial→final）も不可能。
- これは分散DBの中核機能の欠落であり、**債務の中で最も重い**。

## 3. 実装漏れ台帳 (約束 vs 実態)

判定凡例: ✅実装済 / ⚠️部分的 / ❌未実装

| # | 機能 | 約束（根拠） | 実態（v0.6.0 コード根拠） | 判定 | 系統 |
|---|---|---|---|---|---|
| 1 | 集約関数8種 (count/sum/total/avg/min/max/group_concat/string_agg) | milestone:1133-1147 | `create_accumulator` match, aggregate.rs:467-484 | ✅ | A |
| 2 | GROUP BY / HAVING | v0.5.0 req 1・3 | `AggregateIterator`/`StreamingAggregateIterator`, HAVING 評価 aggregate.rs:495-,650-668 | ✅ | A |
| 3 | **集約器の部分状態 state()/merge()** | **milestone:639 で merge 明記** | trait に update/finalize/clone_box のみ, aggregate.rs:87-94 | **❌** | **B** |
| 4 | DISTINCT 集約 | v0.5.0 req 2 (COUNT DISTINCT), dialect NULL挙動 | COUNT のみ実装。SUM/AVG/MIN/MAX/GROUP_CONCAT は型段階で `UnsupportedFeature`, type_checker.rs:1290-,1385-,1417- | ⚠️ | A |
| 5 | 汎用スカラー関数 (ABS/UPPER/COALESCE/LENGTH…) | milestone v0.5.3:1169-1249 | ベクトル4種のみ受理、他は `UnsupportedFeature{version:"future"}`, type_checker.rs:1135-1142 | ❌ | A |
| 6 | ハッシュ/UUID/システム関数 (SHA256/UUIDV7/memory_stats…) | milestone v0.5.1/v0.5.2:704-766 | 未実装（同上エラー返し）。**専用 spec も無し** | ❌ | A |
| 7 | JOIN (INNER/LEFT/RIGHT/FULL/CROSS) | milestone:774-859, "単一ノード" milestones:68 | 5種実装、hash + nested-loop, join.rs:39-72 | ✅ | A |
| 8 | Subquery (scalar/IN/EXISTS/ANY/ALL/FROM派生) | milestone:918-1006 | 相関対応含め実装, subquery.rs | ✅ | A |
| 9 | 分散プラン (Exchange/Repartition/ScatterGather) | milestone v0.9.0+:1011-1054 | LogicalPlan に該当 variant 無し (grep 0件), logical_plan.rs:69-241 | ❌ | B |
| 10 | alopex-cluster (ノード管理・ルーティング) | crate desc "Distributed cluster coordination" | `add(l,r)` スタブのみ、実装ゼロ, alopex-cluster/src/lib.rs | ❌ | B |

## 4. 系統別の債務整理

実装漏れは二系統（[設計書 §2.5](./distributed-query-execution-design.md) 参照）に分けて捉える。

### 系統A（SQL言語・ライブラリ関数）の債務 — 「約束したが入っていない機能」
- **#5 汎用スカラー関数**: v0.5.3 で約束されたが、リリース版はベクトル4種のみ。SQL エンジンとして基本的な `UPPER`/`ABS`/`COALESCE` すら無い。
- **#6 ハッシュ/UUID/システム関数**: v0.5.1/v0.5.2 で約束されたが未実装。しかも**専用 spec すら存在しない**（ロードマップ記載のみ）。
- **#4 DISTINCT 集約**: COUNT 以外は型段階で拒否。約束（v0.5.0 req 2 の NULL 挙動表は全集約を対象）に対し縮小。

これらは単一ノードで閉じる話であり、Chirps 等の分散基盤に依存せず埋められる。**バージョン番号は v0.6 まで進んだが、v0.5.1〜v0.5.3 の関数群という「飛ばされた債務」が残っている。**

### 系統B（クラスタ整合性）の債務 — 「分散DBの根幹が名目のみ」
- **#3 部分状態集約器**: 最重要。約束（merge 付き trait）から脱落。これが無い限り #9 も成立しない。
- **#9 分散プラン**: LogicalPlan に分散演算子が無い。v0.9.0+ の約束だが、その前提となる #3 が欠けている。
- **#10 alopex-cluster**: description は "Distributed cluster coordination" だが中身は `cargo new` スタブ。**名目と実態の乖離が最も大きい。**

系統Bの本実装は Chirps Multi-Raft/TSO（v0.6 予定）に律速される（[設計書 §2.6](./distributed-query-execution-design.md)）が、**#3（部分状態集約器）は Chirps 非依存で今すぐ埋められる**。

## 5. 是正の優先順位 (提案)

債務の重さと依存関係から、是正順序を提案する（実装計画の詳細は[設計書 §6](./distributed-query-execution-design.md)）。

1. **最優先: #3 部分状態集約器 (state/merge の追加)。** Chirps 非依存。系統Bすべての前提。既存8集約器への `state()`/`merge()` 実装追加と、AVG の (sum,count) 状態化を伴う。**trait へのメソッド追加は破壊的変更**のため、次期メジャー相当（v0.7.0）での対応と後方互換方針（デフォルト実装 or 一斉更新）の決定が必要。
2. **#4 DISTINCT 集約の完成**（#3 と同時期。distinct 対応は部分状態設計と関係する）。
3. **#5 汎用スカラー関数**（系統A、独立に進行可能）。関数レジストリ基盤の導入とあわせる。
4. **#6 ハッシュ/UUID/システム関数**（系統A。まず spec 化が必要）。
5. **#9 分散プラン → #10 alopex-cluster 実体化**（系統B、#3 完了後、Chirps v0.6 と歩調）。

## 6. プロセス上の教訓 (再発防止)

事実から導かれる、実装漏れが「完了」として通った構造的原因:

- **ロードマップ（約束）と spec tasks（実装単位）の間で内容が縮小しても検知されなかった**（#3 の `merge` 脱落）。spec 化の際に「ロードマップの約束を満たしているか」の照合ゲートが無い。
- **バージョン番号の前進が機能完成を意味しない。** v0.5.1〜v0.5.3 の関数群を飛ばして v0.6.0（JOIN）へ進んでおり、番号だけ見ると埋まっているように見える。
- **crate description（"Distributed cluster coordination"）が実態（スタブ）を伴わない。** 名目と実装の乖離が公開情報として残っている。

→ spec 承認時に「対応するロードマップ項目の全要件を tasks が網羅しているか」を照合する運用を推奨。

---

### 参照ファイル一覧
- リリース確認: `https://crates.io/api/v1/crates/alopex-sql`
- 集約器: `alopex/crates/alopex-sql/src/executor/query/aggregate.rs`（tag v0.6.0）
- 型チェック: `alopex/crates/alopex-sql/src/planner/type_checker.rs`（tag v0.6.0）
- 論理プラン: `alopex/crates/alopex-sql/src/planner/logical_plan.rs`（tag v0.6.0）
- クラスタ: `alopex/crates/alopex-cluster/src/lib.rs`（tag v0.6.0）
- 約束: `docs-public/roadmap/alopex-sql-milestone.md`, `.spec-workflow/archive/specs/alopex-sql-v0-5-0/`, `.spec-workflow/specs/nim-sql-parser-migration/`
