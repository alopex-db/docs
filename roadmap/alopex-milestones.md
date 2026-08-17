# Alopex / Chirps マイルストーン対応表

バージョン間の依存関係と機能マッピング。

## クレート間バージョン対応

> **Current policy (2026-08-18)**: Alopex の全公開 Rust crate と Python
> package は、Alopex DB と同じバージョンを同じ `vX.Y.Z` release lane で
> 出荷する。`alopex-sql` / Nim parser に独立した feature version や release
> lane はない。parser contract version は FFI 互換性を検査するメタデータで
> あり、Alopex の release version を置き換えない。現在の公開版は v0.8.6。
> 実装・公開順は **v0.8.7 → v0.8.8 → v0.8.9 → v0.8.10 → v0.8.11**。
> **v0.9.0 はこの列がすべて公開されるまで凍結**し、`release/v0.9.0` を
> release candidate として扱わない。実行状況の正本は GitHub milestones
> [v0.8.7](https://github.com/alopex-db/alopex/milestone/7)〜
> [v0.9.0](https://github.com/alopex-db/alopex/milestone/12)。

> **Historical note (2026-08-03)**: 当時、Alopex DB v0.8.1〜v0.8.3 はリリース済みで、`CREATE CONTINUOUS AGGREGATE` と parser contract `0.4.0` を v0.8.4 の prerequisite としていた。この prerequisite はその後 v0.8.4 で出荷済み。経緯は [Skulk v0.5 SQL パーサー準備状況](../reports/skulk-v0.5-sql-parser-readiness.md) を参照。
> **Note (2026-07-18)**: **Alopex DB v0.7.0 はリリース済み**。v0.7のクラスタ機能は single-node compatible な cluster-aware foundation（status、join/leave lifecycle、routing diagnostics、simulation）までで、ノード跨ぎの実行・Raft・分散トランザクションは未実装。これらは v0.8 以降の計画である。DataFrame P3（`str`/`dt`/`list`、`explode`/`implode`）も v0.7.0 で出荷済み。
> **Note (2026-06-27)**: alopex-sql の SQL パーサーを **Nim 実装に置き換える方針を決定**（C ABI FFI で統合、Rust 手書きパーサーは廃止）。あわせて JOIN/Subquery を Planner/Executor まで実装する（対応 DB v0.6）。技術選定は steering `tech.md` / `technical-decisions.md`、実装 spec は `.spec-workflow/specs/nim-sql-parser-migration/` を参照。詳細な機能対応は `alopex-sql-milestone.md` を参照。
> **Note (2026-01-14)**: **Alopex DB v0.4.0 リリース完了**。GitHub Release + crates.io 公開済み。
> **Note (2026-01-13)**: alopex-sql v0.4.0 Async/Stream 基盤、alopex-server v0.4 実装完了。
> **Note (2025-12-18)**: CD ワークフロー修正により alopex-sql v0.3.0 が crates.io に公開済み（旧 v0.1.3 Vector SQL 相当）。

| Alopex DB | alopex-core | alopex-sql | alopex-embedded | Chirps | 主な機能 |
|-----------|-------------|------------|-----------------|--------|----------|
| v0.1 | v0.1 | - | v0.1 | - | KV + Txn + WAL |
| v0.1.1 | v0.1.1 | - | v0.1 | - | **Unified Data File Format** |
| v0.2 | v0.1.1 | - | v0.2 | - | Vector (Flat) |
| v0.2.1 | v0.1.1 | - | v0.2.1 | - | **インメモリモード** |
| **v0.3** | **v0.3.0** | **v0.3.0** | **v0.3.0** | - | **SQL Frontend (Vector SQL)** ✅ crates.io 公開済 |
| **v0.4.0** | **v0.4.0** | **v0.4.0** | **v0.4.0** | - | **Embedded Integration + HNSW + Async/Stream + Server** ✅ **リリース済** |
| v0.5 | v0.5 | v0.5 | v0.5 | - | Durability + GROUP BY |
| v0.6 | v0.6 | v0.6 | v0.6 | - | Embedded/Server 実用化 + Nim SQL パーサー移行 + JOIN/Subquery + DataFrame/Python 強化 |
| **v0.7.0** | **v0.7** | **v0.7.4** | **v0.7** | **v0.3** | **Cluster-aware foundation + routing simulation** ✅ リリース済（single-node compatible、分散実行なし） |
| **v0.8.0** | **v0.8.0** | **v0.8.0** | **v0.8.0** | v0.5.1 | Cluster-aware / streaming / Python surfaces ✅ **リリース済** |
| **v0.8.1** | **v0.8.1** | **v0.8.1** | **v0.8.1** | v0.5.1 | Parser contract `0.2.0` + Ubuntu/Windows release gate ✅ **リリース済** |
| **v0.8.2** | **v0.8.2** | **v0.8.2** | **v0.8.2** | v0.5.1 | 不具合対応 + parser contract `0.3.0` ✅ **リリース済** |
| **v0.8.3** | **v0.8.3** | **v0.8.3** | **v0.8.3** | v0.5.1 | 不具合対応・安定化（Continuous Aggregate なし）✅ **リリース済** |
| **v0.8.4** | **v0.8.4** | **v0.8.4** | **v0.8.4** | v0.5.1 | Continuous Aggregate parser contract `0.4.0` ✅ **リリース済** |
| **v0.8.5** | **v0.8.5** | **v0.8.5** | **v0.8.5** | v0.5.2 | 公開 surface / release packaging hardening ✅ **リリース済** |
| **v0.8.6** | **v0.8.6** | **v0.8.6** | **v0.8.6** | v0.5.2 | 単一 node SQL correctness（alias / REAL / set operations / CASE / CTE / basic window）✅ **リリース済** |
| **v0.8.7〜v0.8.11** | **同一版** | **同一版** | **同一版** | v0.5.2 | 単一 node SQL compatibility closure 🚧 **順次実装・公開** |
| **v0.9.0** | **v0.9.0** | **v0.9.0** | **v0.9.0** | v0.7+ | Distributed query parity 🧊 **v0.8.11 公開まで凍結** |
| v1.0 | v1.0 | v1.0 | v1.0 | v0.8+ | Federation + Optimizer |

---

## Alopex DB SQL マイルストーン

> v0.8.6 以後は Alopex DB の統一 release train。表中の古い個別版は公開履歴・
> feature allocation の記録であり、独立した `alopex-sql` release lane ではない。

> **Note (2025-12-18)**: CD ワークフロー修正により v0.3.0 が crates.io に公開済み（旧 v0.1.3 Vector SQL 相当）。
> 旧 v0.1.0~v0.1.3 は v0.3.0 に統合、v0.1.4 以降は v0.4.0 以降に再番号付け。

| Version | Milestone | 依存 | 目標 | 対応 DB | 状態 |
|---------|-----------|------|------|---------|------|
| ~~v0.1.0~~ | Parser Complete | - | Lexer + AST + DDL/DML Parser | v0.3 | ✅ v0.3.0 に統合 |
| ~~v0.1.1~~ | Planner | alopex-core v0.1 | Catalog + LogicalPlan | v0.3 | ✅ v0.3.0 に統合 |
| ~~v0.1.1-storage~~ | Storage Engine | alopex-core v0.1 | RowCodec + KeyEncoder + TxnBridge | v0.3 | ✅ v0.3.0 に統合 |
| ~~v0.1.2~~ | Executor | alopex-core v0.1 | DDL/DML 実行 | v0.3 | ✅ v0.3.0 に統合 |
| ~~v0.1.3~~ | Vector SQL | alopex-core v0.1 | vector_similarity, Top-K | v0.3 | ✅ v0.3.0 に統合 |
| **v0.3.0** | **SQL Frontend (Vector SQL)** | alopex-core v0.3.0 | Parser + Planner + Executor + Vector SQL | v0.3 | ✅ **crates.io 公開済** |
| ~~v0.4.0~~ | Embedded Integration | alopex-embedded v0.4 | execute_sql API | v0.4 | ✅ 完了 |
| **v0.4.0** | **Async/Stream 基盤** | alopex-sql v0.3 | runtime-agnostic async facade, tokio adapter, streaming SELECT | v0.4 | ✅ **完了** |
| v0.5.0 | GROUP BY / Aggregation | alopex-sql v0.4 | 集約クエリ、HNSW INDEX 構文 | v0.5 | ⏳ 予定 |
| v0.5.1 | 次世代検索インデックス基盤 | alopex-sql v0.5 | SHA-256/SimHash/UUIDv7 | v0.5 | ⏳ 予定 |
| v0.5.2 | キャッシュ・メモリ管理 | alopex-sql v0.5.1 | I/O計測、アダプティブキャッシュ | v0.5 | ⏳ 予定 |
| v0.6.0 | Nim パーサー移行 + JOIN Support | alopex-sql v0.5.2 | Nim 製パーサー(FFI) + INNER/LEFT/RIGHT/FULL/CROSS JOIN | v0.6 | ⏳ 予定 |
| v0.6.0-subquery | Subquery | alopex-sql v0.6 | スカラー/IN/EXISTS/FROM 派生/ANY,ALL サブクエリ | v0.6 | ⏳ 予定 |
| **v0.8.1** | **Parser / release gate reliability** | alopex-sql v0.8.0 | SQL-TS/PromQL contract `0.2.0`、Ubuntu/Windows full gate | v0.8.1 | ✅ **リリース済** |
| **v0.8.2** | **Bugfix release** | alopex-sql v0.8.1 | 不具合修正 + parser contract `0.3.0` | v0.8.2 | ✅ **リリース済** |
| **v0.8.3** | **Bugfix / stabilization release** | alopex-sql v0.8.2 | 安定化（Continuous Aggregate なし） | v0.8.3 | ✅ **リリース済** |
| **v0.8.4** | **Skulk v0.5 parser prerequisite** | Alopex v0.8.3 | `CREATE CONTINUOUS AGGREGATE`、wire contract `0.4.0`、target 別 parser assets、checksum manifest | Skulk v0.5 | ✅ **リリース済** |
| **v0.8.5** | **Release surface hardening** | Alopex v0.8.4 | packaging / verifier / public surface の安定化 | v0.8.5 | ✅ **リリース済** |
| **v0.8.6** | **Single-node SQL correctness** | Alopex v0.8.5 | alias、REAL、set operations、CASE、非再帰 CTE、basic window | v0.8.6 | ✅ **リリース済** |
| **v0.8.7** | **CTE / window correctness closure** | Alopex v0.8.6 | recursive CTE、CTE column list、peer/frame、LAG/LEAD、aggregate composition | v0.8.7 | 🚧 **実装中** |
| **v0.8.8** | **Portable relational grammar** | Alopex v0.8.7 | predicates、VALUES、window/aggregate/grouping/table expressions | v0.8.8 | ⏳ **待機** |
| **v0.8.9** | **Portable functions** | Alopex v0.8.8 | temporal/statistics/math/string/regex/bitwise/boolean aggregate、GENERATE_SERIES | v0.8.9 | ⏳ **待機** |
| **v0.8.10** | **Type / nested / search foundation** | Alopex v0.8.9 | DECIMAL、DATE/TIME/INTERVAL、JSON、nested types、FTS | v0.8.10 | ⏳ **待機** |
| **v0.8.11** | **Application / administration SQL** | Alopex v0.8.10 | transaction、bind、introspection、schema/DML/COPY/identity | v0.8.11 | ⏳ **待機** |
| **v0.9.0** | **Distributed query parity** | Chirps v0.7+ | v0.8 SQL surface の capability classification / deterministic rejection / parity | v0.9.0 | 🧊 **凍結** |
| v1.0.0 | Query Optimizer | - | コストベース最適化、統計情報 | v1.0 | ⏳ 予定 |
| v1.0+-wasm | WASM Parser (再評価) | Alopex v1.0+ | Read-Only SQL (wasm32) | v1.0+ | ⏳ 再評価 |

---

## Alopex DB ↔ alopex-sql 対応詳細

| DB バージョン | 必要な alopex-sql 機能 | alopex-sql バージョン |
|---------------|------------------------|----------------------|
| v0.3 | DDL/DML パース＆実行, Storage Engine, Vector SQL | **v0.3.0** (crates.io 公開済) |
| v0.4 | Embedded Integration, HNSW INDEX 構文 | **v0.4.0** (完了) |
| v0.5 | GROUP BY, 次世代インデックス, キャッシュ | v0.5.0 - v0.5.2 |
| v0.6 | JOIN (単一ノード) | v0.6.0 |
| v0.7 | cluster-aware foundation + routing diagnostics (single-node) | **v0.7.0 / v0.7.x** |
| v0.8.0 | Cluster-aware / streaming / Python surfaces | **v0.8.0** |
| v0.8.1 | Parser contract `0.2.0` + release gate reliability | **v0.8.1** |
| v0.8.2 | 不具合対応 + parser contract `0.3.0` | **v0.8.2（リリース済）** |
| v0.8.3 | 不具合対応・安定化（Continuous Aggregate なし） | **v0.8.3（リリース済）** |
| v0.8.4 | Continuous Aggregate parser contract `0.4.0` | **v0.8.4（リリース済）** |
| v0.8.5 | Release surface hardening | **v0.8.5（リリース済）** |
| v0.8.6 | Alias / REAL / set operations / CASE / CTE / basic window | **v0.8.6（リリース済）** |
| v0.8.7〜v0.8.11 | Single-node SQL compatibility closure | **Alopex DB と同一版** |
| v0.9.0 | Distributed query parity | **v0.9.0（凍結）** |
| v1.0 | Federation クエリ、オプティマイザ | **v1.0** |

---

## Chirps マイルストーン

| Version | Milestone | 依存 | 状態 |
|---------|-----------|------|------|
| v0.1-v0.3 | Node Identity、QUIC、Gossip | - | ✅ 完了 |
| v0.4 | Raft-ready Transport | Chirps v0.3 | ✅ 完了 |
| v0.5 | Raft Consensus API | Chirps v0.4 | ✅ 完了 |
| **v0.5.1** | **File Transfer API** | Chirps v0.5 | ⏳ 予定 |
| v0.6 | Multi-Raft + TSO + Observability | Chirps v0.5.1 | ⏳ 予定 |
| v0.7 | Pluggable Backend + Durable | Chirps v0.6 | ⏳ 予定 |
| v0.8 | Federation Profile | Chirps v0.7 | ⏳ 予定 |
| v0.9 | Multi-Cluster + HLC | Chirps v0.8 | ⏳ 予定 |
| v1.0 | Advanced Federation | Chirps v0.9 | ⏳ 予定 |

### Chirps File Transfer API (v0.5.1)

クラスタ間ファイル転送専用 API。**Multi-Raft のスナップショット転送**、SSTable/セグメントファイルの転送、フェデレーション同期に使用。

**依存関係修正 (2025-12-18)**:
- 旧: v0.7.1 (Chirps v0.7 依存)
- 新: v0.5.1 (Chirps v0.5 依存)
- 理由: Multi-Raft (v0.6) がスナップショット転送に File Transfer を必要とするため

| 機能 | 説明 |
|------|------|
| send_file / broadcast_file | 1対1/1対N ファイル転送 |
| sync_file | Push/Pull/双方向ファイル同期 |
| Chunked Transfer | 並列チャンク転送（デフォルト 4並列、1MB/chunk）|
| Integrity Verification | XXHash64（チャンク）+ SHA-256（ファイル全体）|
| Resume | セッション永続化によるレジューム対応 |
| Bandwidth Throttling | トークンバケット方式の帯域制御 |

---

## DB × Chirps 連動チェックリスト

### Raft Consensus API統合
- Chirps v0.5: `StateMachine`/`RaftStorage` trait、`RaftNode` 基本実装
- Chirps v0.5.1: File Transfer API（スナップショット転送の基盤）
- Chirps v0.6: `MultiRaftManager`、`WalRaftStorage`、スナップショット転送（File Transfer 使用）
- DB v0.8: `RangeStateMachine` が Chirps Raft API でメタデータ合意
- Skulk v0.9: `ShardStateMachine` が Chirps Raft API でシャードレプリケーション

### 単一クラスタ連携
- v0.7 (DB): Chirps v0.3 の membership API/イベントに接続
- v0.8 (DB): Chirps v0.6 の Raft Consensus API で動作
- v0.9 (DB): Chirps v0.7 の Durable profile で Changefeed
- v0.10 (DB): 回帰/負荷テストで双方の安定性証明

### フェデレーション連携
- v1.0 (DB): Chirps v0.8 の Federation profile で 2 クラスタ間フェデレーション
  - Chirps v0.5.1 の File Transfer API で SSTable/セグメントファイル同期
- v1.1 (DB): Chirps v0.9 のマルチクラスタ + HLC で Mesh
- v1.2 (DB): Chirps v1.0 のフェイルオーバー通知で自動フェイルオーバー

---

## Skulk × Core/Chirps 連動

- Skulk v0.1: alopex-core v0.2 の WAL/MemTable trait で TSM 基盤
- Skulk v0.8: Chirps v0.3 の membership API でクラスタノード認識
- Skulk v0.9: Chirps v0.6 の Raft Consensus API でシャードレプリケーション
- Skulk v1.0: Core/Chirps/Skulk 統合テストスイート完走
