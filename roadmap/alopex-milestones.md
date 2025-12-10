# Alopex / Chirps マイルストーン対応表

バージョン間の依存関係と機能マッピング。

## クレート間バージョン対応

| Alopex DB | alopex-core | alopex-sql | alopex-embedded | Chirps | 主な機能 |
|-----------|-------------|------------|-----------------|--------|----------|
| v0.1 | v0.1 | - | v0.1 | - | KV + Txn + WAL |
| v0.1.1 | v0.1.1 | - | v0.1 | - | **Unified Data File Format** |
| v0.2 | v0.1.1 | - | v0.2 | - | Vector (Flat) |
| v0.2.1 | v0.1.1 | - | v0.2.1 | - | **インメモリモード** |
| **v0.3** | v0.1 | **v0.1** | v0.3 | - | **SQL Frontend** |
| v0.3.1 | v0.1.1 | - | v0.3 | - | **alopex-core バッファプール** |
| v0.4 | v0.2 | v0.2 | v0.4 | - | HNSW + Server + GROUP BY |
| v0.5 | v0.2 | v0.3 | v0.4 | - | Durability + JOIN |
| v0.6 | v0.3 | v0.4-v0.5 | v0.5 | - | WASM Viewer + Subquery |
| v0.7 | v0.3 | v0.6 | v0.5 | v0.3 | Cluster-aware + 分散クエリ |
| v0.8 | v0.4 | v0.7 | v0.6 | v0.6 | Raft Metadata + Raft DDL |
| v0.9 | v0.4 | v0.8 | v0.6 | v0.7 | Multi-Raft + 分散 Txn |
| v1.0 | v0.5 | v0.9-v1.0 | v0.7 | v0.8 | Federation + Optimizer |

---

## alopex-sql マイルストーン

| Version | Milestone | 依存 | 目標 | 対応 DB |
|---------|-----------|------|------|---------|
| v0.1.0 | Parser Complete | - | Lexer + AST + DDL/DML Parser | v0.3 |
| v0.1.1 | Planner | alopex-core v0.1 | Catalog + LogicalPlan | v0.3 |
| v0.1.1-storage | Storage Engine | alopex-core v0.1 | RowCodec + KeyEncoder + TxnBridge | v0.3 |
| v0.1.2 | Executor | alopex-core v0.1 | DDL/DML 実行 | v0.3 |
| v0.1.3 | Vector SQL | alopex-core v0.1 | vector_similarity, Top-K | v0.3 |
| v0.1.4 | Embedded Integration | alopex-embedded v0.2 | execute_sql API | v0.3 |
| v0.2.0 | GROUP BY / Aggregation | alopex-sql v0.1 | 集約クエリ、HNSW INDEX 構文 | v0.4 |
| v0.2.1 | 次世代検索インデックス基盤 | alopex-sql v0.2 | SHA-256/SimHash/UUIDv7 | v0.4 |
| v0.2.2 | キャッシュ・メモリ管理 | alopex-sql v0.2.1 | I/O計測、アダプティブキャッシュ | v0.4 |
| v0.3.0 | JOIN Support | alopex-sql v0.2.2 | INNER/LEFT/RIGHT JOIN | v0.5 |
| v0.4.0 | WASM Parser | alopex-sql v0.3 | Read-Only SQL (wasm32) | v0.6 |
| v0.5.0 | Subquery | alopex-sql v0.4 | WHERE/FROM 句サブクエリ | v0.6 |
| v0.6.0 | Distributed Query Planner | Chirps v0.3 | シャード対応クエリ計画 | v0.7 |
| v0.6.0-index | TSO 統合分散インデックス | Chirps v0.6 (TSO) | Point-in-Time/整合性チェック | v0.7 |
| v0.7.0 | Raft-aware Executor | Chirps v0.6 | Raft 合意付き DDL/DML | v0.8 |
| v0.8.0 | Multi-Raft Query | Chirps v0.7 | 分散トランザクション | v0.9 |
| v0.9.0 | Federation Query | Chirps v0.8 | クロスクラスタクエリ | v1.0 |
| v0.9.0-index | クロスクラスタインデックス同期 | Chirps v0.8-v0.9 (HLC) | フェデレーションインデックス | v1.0 |
| v1.0.0 | Query Optimizer | - | コストベース最適化、統計情報 | v1.0 |

---

## Alopex DB ↔ alopex-sql 対応詳細

| DB バージョン | 必要な alopex-sql 機能 | alopex-sql バージョン |
|---------------|------------------------|----------------------|
| v0.3 | DDL/DML パース＆実行, Storage Engine, Vector SQL | v0.1.0 - v0.1.4 |
| v0.4 | HNSW CREATE INDEX 構文, GROUP BY | v0.2.0 |
| v0.5 | JOIN (単一ノード) | v0.3.0 |
| v0.6 | WASM Read-Only パーサー, Subquery | v0.4.0 - v0.5.0 |
| v0.7 | 分散クエリ計画 (Scatter-Gather) | v0.6.0 |
| v0.8 | Raft 合意付き DDL | v0.7.0 |
| v0.9 | Multi-Raft クエリ | v0.8.0 |
| v1.0 | Federation クエリ、オプティマイザ | v0.9.0 - v1.0.0 |

---

## DB × Chirps 連動チェックリスト

### Raft Consensus API統合
- Chirps v0.5: `StateMachine`/`RaftStorage` trait、`RaftNode` 基本実装
- Chirps v0.6: `MultiRaftManager`、`WalRaftStorage`、スナップショット転送
- DB v0.8: `RangeStateMachine` が Chirps Raft API でメタデータ合意
- Skulk v0.9: `ShardStateMachine` が Chirps Raft API でシャードレプリケーション

### 単一クラスタ連携
- v0.7 (DB): Chirps v0.3 の membership API/イベントに接続
- v0.8 (DB): Chirps v0.6 の Raft Consensus API で動作
- v0.9 (DB): Chirps v0.7 の Durable profile で Changefeed
- v0.10 (DB): 回帰/負荷テストで双方の安定性証明

### フェデレーション連携
- v1.0 (DB): Chirps v0.8 の Federation profile で 2 クラスタ間フェデレーション
- v1.1 (DB): Chirps v0.9 のマルチクラスタ + HLC で Mesh
- v1.2 (DB): Chirps v1.0 のフェイルオーバー通知で自動フェイルオーバー

---

## Skulk × Core/Chirps 連動

- Skulk v0.1: alopex-core v0.2 の WAL/MemTable trait で TSM 基盤
- Skulk v0.8: Chirps v0.3 の membership API でクラスタノード認識
- Skulk v0.9: Chirps v0.6 の Raft Consensus API でシャードレプリケーション
- Skulk v1.0: Core/Chirps/Skulk 統合テストスイート完走
