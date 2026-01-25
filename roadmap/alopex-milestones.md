# Alopex / Chirps マイルストーン対応表

バージョン間の依存関係と機能マッピング。

## クレート間バージョン対応

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
| v0.6 | v0.6 | v0.6 | v0.6 | - | JOIN Support |
| v0.7 | v0.7 | v0.7-v0.8 | v0.7 | - | WASM Viewer + Subquery |
| v0.8 | v0.8 | v0.9 | v0.8 | v0.3 | Cluster-aware + 分散クエリ |
| v0.9 | v0.9 | v0.10 | v0.9 | v0.6 | Raft Metadata + Raft DDL |
| v0.10 | v0.10 | v0.11 | v0.10 | v0.7 | Multi-Raft + 分散 Txn |
| v1.0 | v1.0 | v0.12-v1.0 | v1.0 | v0.8 | Federation + Optimizer |

---

## alopex-sql マイルストーン

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
| v0.6.0 | JOIN Support | alopex-sql v0.5.2 | INNER/LEFT/RIGHT JOIN | v0.6 | ⏳ 予定 |
| v0.7.0 | WASM Parser | alopex-sql v0.6 | Read-Only SQL (wasm32) | v0.7 | ⏳ 予定 |
| v0.8.0 | Subquery | alopex-sql v0.7 | WHERE/FROM 句サブクエリ | v0.7 | ⏳ 予定 |
| v0.9.0 | Distributed Query Planner | Chirps v0.3 | シャード対応クエリ計画 | v0.8 | ⏳ 予定 |
| v0.9.0-index | TSO 統合分散インデックス | Chirps v0.6 (TSO) | Point-in-Time/整合性チェック | v0.8 | ⏳ 予定 |
| v0.10.0 | Raft-aware Executor | Chirps v0.6 | Raft 合意付き DDL/DML | v0.9 | ⏳ 予定 |
| v0.11.0 | Multi-Raft Query | Chirps v0.7 | 分散トランザクション | v0.10 | ⏳ 予定 |
| v0.12.0 | Federation Query | Chirps v0.8 | クロスクラスタクエリ | v1.0 | ⏳ 予定 |
| v0.12.0-index | クロスクラスタインデックス同期 | Chirps v0.8-v0.9 (HLC) | フェデレーションインデックス | v1.0 | ⏳ 予定 |
| v1.0.0 | Query Optimizer | - | コストベース最適化、統計情報 | v1.0 | ⏳ 予定 |

---

## Alopex DB ↔ alopex-sql 対応詳細

| DB バージョン | 必要な alopex-sql 機能 | alopex-sql バージョン |
|---------------|------------------------|----------------------|
| v0.3 | DDL/DML パース＆実行, Storage Engine, Vector SQL | **v0.3.0** (crates.io 公開済) |
| v0.4 | Embedded Integration, HNSW INDEX 構文 | **v0.4.0** (完了) |
| v0.5 | GROUP BY, 次世代インデックス, キャッシュ | v0.5.0 - v0.5.2 |
| v0.6 | JOIN (単一ノード) | v0.6.0 |
| v0.7 | WASM Read-Only パーサー, Subquery | v0.7.0 - v0.8.0 |
| v0.8 | 分散クエリ計画 (Scatter-Gather) | v0.9.0 |
| v0.9 | Raft 合意付き DDL | v0.10.0 |
| v0.10 | Multi-Raft クエリ | v0.11.0 |
| v1.0 | Federation クエリ、オプティマイザ | v0.12.0 - v1.0.0 |

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
