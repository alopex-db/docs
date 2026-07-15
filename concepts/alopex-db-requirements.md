# Alopex DB 要求仕様書

**バージョン**: 1.0
**最終更新日**: 2025-11-21
**ステータス**: Draft

---

## 1. エグゼクティブサマリー

### 1.1 プロジェクト概要

Alopex DBは、**「極限環境で生き抜くホッキョクギツネ（Alopex）」の特性を象徴**とし、あらゆるレベルの開発者に**耐障害性・適応性・高速性**を提供する新世代データベースである。

**コアバリュー**: Silent. Adaptive. Unbreakable.

- **Silent（静か）**: 低レイテンシ、軽量、予測可能なパフォーマンス
- **Adaptive（適応性）**: 組み込みから分散クラスタまでシームレスにスケール
- **Unbreakable（壊れない）**: ACID保証、Raftによる複製でデータ損失ゼロ

### 1.2 市場ニーズ

**現状の課題**:
1. **RAG時代の到来**: LLM連携アプリケーションにおけるベクトル検索需要の急増
2. **複雑なスタック**: SQLite + Faiss、Postgres + pgvector など、複数製品の組み合わせが必要
3. **スケーラビリティの壁**: 組み込みDBから分散DBへの移行コストが高い
4. **エッジコンピューティング**: モバイル・ブラウザでのローカルAI処理需要

**Alopex DBの解決策**:
- 単一エンジンでSQL + ベクトル検索を統合
- 組み込み → シングルノード → 分散クラスタへのシームレスな移行
- WASM対応によるブラウザ内データベース機能

---

## 2. ステークホルダー要求

### 2.1 対象ユーザー

#### プライマリユーザー
1. **スタートアップ・個人開発者**
   - 小規模から始めて段階的にスケール
   - 低い初期投資、シンプルな運用

2. **RAG/LLMアプリケーション開発者**
   - ベクトル検索とメタデータフィルタリングの統合
   - トランザクション保証されたドキュメント管理

3. **エッジ/モバイル開発者**
   - オフライン動作可能な組み込みDB
   - WASMによるブラウザ内AI処理

#### セカンダリユーザー
4. **エンタープライズ開発者**
   - 高可用性クラスタ
   - マルチリージョン展開

5. **データエンジニア**
   - OLTP + ベクトル検索の統合基盤
   - 既存PostgreSQL/MySQLからの移行

### 2.2 主要要求

#### 機能要求（FR）

**FR-001: マルチモード展開**
- 単一エンジンで4つのモードをサポート
  - Embedded: ライブラリとして組み込み
  - Single-Node: 単一サーバーモード
  - Distributed: 分散クラスタモード
  - WASM: ブラウザ/エッジ環境（読み取り専用）
- **統一データファイル形式** (`.alopex`):
  - 全モードで同一のバイナリ形式を使用
  - モード間でデータファイルのコピー移行が可能
  - WASMは読み取り専用、他モードは読み書き両対応

**FR-002: SQL対応**
- 基本的なSQL構文サポート（SELECT, INSERT, UPDATE, DELETE）
- DDL: CREATE TABLE, CREATE INDEX, ALTER TABLE
- トランザクション: BEGIN, COMMIT, ROLLBACK
- 制約: PRIMARY KEY, FOREIGN KEY, UNIQUE, NOT NULL

**FR-003: ベクトル検索**
- ⚠️ v0.1では対象外（v0.2以降で段階的に実装）
- v0.2: ベクトル型のネイティブサポート `VECTOR(N)`、類似度検索（Flat Search: cosine / L2 / inner product）
- v0.4: HNSW (Hierarchical Navigable Small World) 導入
- ハイブリッド検索: SQLフィルタ + ベクトル検索（v0.2以降）

**FR-004: トランザクション管理**
- ACID保証
- 分離レベル: Snapshot Isolation（MVCC + 楽観的並行性制御）
  - v0.1: 単一ノードでの Snapshot Isolation
  - v0.7+: 分散環境で Serializable を検討
- 並行性制御: 楽観的並行性制御（OCC）
- デッドロック検出と自動リトライ

**FR-005: 分散機能**
- Rangeベースのシャーディング
- Raftベースのレプリケーション
- 自動リバランシング
- マルチリージョン対応

**FR-006: WASM対応**
- ⚠️ v0.1〜v0.5 では対象外（v0.6で導入）
- v0.6: wasm32-unknown-unknown ターゲット、Pre-built SSTable ローダー（Read-Only）
- v0.6: IndexedDB キャッシュ層（durability不要）、JavaScript/TypeScript バインディング（npm）
- v0.6: SQL SELECT と Vector Search (Flat) のみ、Write操作は意図的にエラー
- Web Workers対応（v0.6以降）

#### 非機能要求（NFR）

**NFR-001: パフォーマンス**
- 読み取りレイテンシ: <10ms (P99, ローカル)
- 書き込みスループット: >10,000 ops/sec (単一ノード)
- ベクトル検索: <100ms (P99, 100万ベクトル、HNSW使用時)

**NFR-002: 可用性**
- Uptime: 99.9% (3ノードクラスタ)
- RTO (Recovery Time Objective): <5分
- RPO (Recovery Point Objective): 0 (データ損失なし)

**NFR-003: スケーラビリティ**
- 組み込みモード: 最大100GB
- シングルノード: 最大1TB
- 分散モード: 数十TB以上（ノード数に応じて）

**NFR-004: 互換性**
- OS: Linux, macOS, Windows
- アーキテクチャ: x86_64, ARM64
- WASM: ブラウザ（Chrome, Firefox, Safari, Edge）、Deno、Node.js

**NFR-005: セキュリティ**
- TLS/QUICによる暗号化通信
- ロールベースアクセス制御（RBAC）
- 監査ログ

**NFR-006: 保守性**
- Rust 100%実装（安全性、保守性）
- 包括的なテストカバレッジ（>80%）
- ドキュメント完備

---

## 3. システム要求

### 3.1 機能要求詳細

#### 3.1.1 ストレージエンジン

**要求ID**: SR-STORAGE-001
**概要**: LSMツリーベースのストレージエンジン

**詳細要求**:
- Write-Ahead Log (WAL) による永続性保証
- Memtable + SSTable構造
- Bloom Filter による読み取り最適化
- Compaction戦略（Level-based）
- スナップショット分離

**検証基準**:
- [ ] WAL書き込み後の即時クラッシュでもデータ損失なし
- [ ] 1億キー挿入後も読み取り性能が10ms以内
- [ ] Compaction実行中も読み取り性能劣化が20%以内

---

#### 3.1.2 SQL処理

**要求ID**: SR-SQL-001
**概要**: SQL解析・実行エンジン

**詳細要求**:
- Parser: `sqlparser-rs` ベース
- Planner: ルールベース最適化
- Executor: Volcano-styleイテレータモデル
- サポートする演算子:
  - Scan (Sequential, Index)
  - Filter
  - Project
  - Join (Nested Loop, Hash Join)
  - Aggregate (GROUP BY, COUNT, SUM, AVG, MAX, MIN)
  - Sort (ORDER BY)
  - Limit/Offset

**検証基準**:
- [ ] TPC-C互換のスキーマ定義が可能
- [ ] JOIN含むクエリが正しく実行される
- [ ] トランザクション内でのROLLBACKが正常動作

---

#### 3.1.3 ベクトル検索

**要求ID**: SR-VECTOR-001
**概要**: ネイティブベクトル検索機能

**詳細要求**:
```sql
-- ベクトル型定義
CREATE TABLE documents (
  id INT PRIMARY KEY,
  content TEXT,
  embedding VECTOR(768)  -- 次元数指定
);

-- ベクトル挿入
INSERT INTO documents (id, content, embedding)
VALUES (1, 'Hello', '[0.1, 0.2, ..., 0.9]');

-- 類似度検索（コサイン類似度、上位10件）
SELECT id, content,
       cosine_similarity(embedding, '[0.5, 0.3, ...]') AS score
FROM documents
ORDER BY score DESC
LIMIT 10;

-- ハイブリッド検索
SELECT id, content,
       cosine_similarity(embedding, '[...]') AS score
FROM documents
WHERE content LIKE '%Rust%'
ORDER BY score DESC
LIMIT 10;
```

**検証基準**:
- [ ] 100万ベクトル（768次元）の挿入が完了
- [ ] Flat Search でP99 < 500ms
- [ ] HNSW導入後、P99 < 100ms
- [ ] ハイブリッド検索が正しく動作

---

#### 3.1.4 分散クラスタ

**要求ID**: SR-CLUSTER-001
**概要**: Rangeベースの分散アーキテクチャ

**詳細要求**:
- Range分割: キー範囲によるシャーディング
- Replication Factor: 3（デフォルト）
- Raft Consensus: 各Rangeごとに独立したRaftグループ
- Gossip/Control Plane: **alopex-chirps を使用（ブラックボックス不可）**
  - QUIC/TLS 伝送、優先度付きストリーム（Raft メッセージを保護）
  - SWIM 互換の ping/ack/ping-req、alive/suspect/dead 判定とイベントフック
  - 永続 node_id（再起動後も同一 ID）、seed join でのクラスタ形成
  - API: `send_to`, `broadcast`, `subscribe` に加え、ノード一覧/状態 API を提供
- 自動リバランシング: ノード追加時のRange再配置

**検証基準**:
- [ ] 3ノードクラスタで1ノード障害時も継続動作
- [ ] ノード追加時に自動的にRangeが再配置
- [ ] 分散トランザクションが正しくコミット/ロールバック
- [ ] chirps メンバーシップイベントが DB 側のルーティング/リーダー選出に即時反映
- [ ] Raft AppendEntries/RequestVote が chirps 優先ストリーム経由でドロップなく往復

---

#### 3.1.5 クラスタ間フェデレーション

**要求ID**: SR-FEDERATION-001
**概要**: 複数の独立したAlopexクラスタを連携させるフェデレーション機能

**設計方針**:
- **Cluster Autonomy**: 各クラスタは独立して動作し、フェデレーション障害時も単独運用可能
- **Eventual Consistency**: クラスタ間は非同期レプリケーション（強整合性は単一クラスタ内のみ）
- **Explicit Configuration**: フェデレーション関係は明示的に設定（自動検出なし）

**詳細要求**:

**FR-FED-001: クラスタ間接続**
- フェデレーションリンクの確立・維持
- 相互TLS認証によるクラスタ間信頼関係
- QUIC/TLS経由の専用フェデレーションチャネル（Chirps拡張）
- クラスタ間のレイテンシ・可用性モニタリング

**FR-FED-002: 非同期レプリケーション**
- Changefeed/WALベースの変更伝播
- コンフリクト解決戦略（Last-Write-Wins / CRDT）
- レプリケーションラグの可視化と閾値アラート
- 選択的レプリケーション（テーブル/Range単位）

**FR-FED-003: グローバルルーティング**
- クライアントからの透過的なクロスクラスタクエリ
- Locality-aware routing（最寄りクラスタ優先）
- フェイルオーバールーティング（プライマリクラスタ障害時）

**FR-FED-004: フェデレーショントポロジ**
- Hub-Spoke: 中央ハブクラスタと複数スポーク
- Mesh: 全クラスタ間の対等接続
- Hierarchical: 地域→グローバルの階層構造

**ユースケース**:
1. **ジオレプリケーション**: 東京クラスタとUS-Eastクラスタ間のデータ同期
2. **DR（災害復旧）**: プライマリクラスタ障害時のスタンバイクラスタへの切り替え
3. **データローカリティ**: GDPR準拠のため地域別データ保持
4. **読み取りスケール**: 読み取り専用レプリカクラスタの配置

**検証基準**:
- [ ] 2クラスタ間のフェデレーションリンク確立・維持
- [ ] 非同期レプリケーションでのデータ伝播（ラグ <10秒、通常時）
- [ ] プライマリクラスタ障害時のフェイルオーバー（RTO <5分）
- [ ] コンフリクト解決が設定通りに動作
- [ ] クロスクラスタクエリが正しく結果を返す

**マイルストーン**: v1.0（Multi-region Alopex）で導入

---

#### 3.1.6 WASM対応（Read-Only Viewer Mode）

**要求ID**: SR-WASM-001
**概要**: WebAssembly環境での**読み取り専用**データベースビューア

**設計方針**:
- **Primary Use Case**: サーバー側で生成されたDBスナップショットファイルの閲覧
- **Scope Limitation**: Write/ETL機能は除外（INSERT/UPDATE/DELETE不可）
- **Target Format**: Pre-built SSTableファイル（WAL/Compaction不要）

**詳細要求**:
- ターゲット: `wasm32-unknown-unknown`
- バインディング: `wasm-bindgen`
- ストレージバックエンド:
  - IndexedDB（キャッシュ用途のみ、durability保証不要）
  - OPFS（将来的な大容量キャッシュ用）
- 非同期ランタイム: `wasm-bindgen-futures`
- バイナリサイズ: <1MB（gzip圧縮後、Write処理除外により軽量化）

**JavaScript API例**:
```javascript
import { AlopexViewer } from 'alopex-wasm';

// サーバー生成のDBスナップショットをロード
const viewer = await AlopexViewer.loadSnapshot('https://example.com/db-snapshot.alopex');

// 読み取り専用SQL実行
const rows = await viewer.query('SELECT * FROM users WHERE age > 20');
console.log(rows);

// ベクトル検索（Flat Search）
const results = await viewer.vectorSearch({
  table: 'documents',
  vector: [0.1, 0.2, ...],
  similarity: 'cosine',
  limit: 10,
  filter: "category = 'tech'"
});

// ❌ Write操作は不可（設計上の制限）
// await viewer.execute('INSERT INTO users ...'); // Error: Read-only mode
```

**検証基準**:
- [ ] Pre-built SSTableをURL/IndexedDBから読み込み可能
- [ ] Chrome, Firefox, Safari で動作確認
- [ ] SQL SELECT、Vector Search が正常動作
- [ ] IndexedDBにキャッシュ可能（durability保証不要）
- [ ] Web Worker内で動作
- [ ] ❌ Write操作は意図的にエラー（Read-only制限）

**非機能要求**:
- 初回ロード: <2秒（中規模DBスナップショット、~10MB想定）
- クエリレイテンシ: <50ms（キャッシュヒット時）
- メモリ使用量: <100MB（ブラウザ環境制約）

---

### 3.2 システム制約

#### 3.2.1 技術制約

**TC-001: プログラミング言語**
- Rust 100%実装
- 最小サポートバージョン: Rust 1.75+

**TC-002: 依存クレート**
- 非同期ランタイム: Tokio (Native), wasm-bindgen-futures (WASM)
- QUIC: quinn
- SQL Parser: sqlparser-rs
- エラーハンドリング: thiserror, anyhow

**TC-003: 外部依存**
- 分散クラスタ通信: alopex-chirps (独立リポジトリ、QUIC/TLS + SWIM メンバーシップ + 優先ストリームを DB から直接利用)
- Raft実装: **raft-rs を採用**（TiKV実績、Production-ready）
  - Metadata管理: 単一Raftグループ
  - Data Plane: Multi-Raft（Rangeごと）
  - 将来的に dragonboat-rs も検討（v1.0以降）

#### 3.2.2 運用制約

**OC-001: デプロイメント**
- コンテナ対応: Dockerfile提供
- パッケージマネージャ: apt, yum, Homebrew対応（将来）
- npm: WASM版の配布

**OC-002: 監視**
- Prometheusメトリクスエンドポイント
- 構造化ログ（JSON形式）
- OpenTelemetryトレーシング対応（将来）

---

## 4. ユースケース

### 4.1 UC-001: RAGアプリケーション開発

**アクター**: RAG開発者

**前提条件**:
- LLMのエンベディングモデルが利用可能
- ドキュメントコーパスが存在

**フロー**:
1. ドキュメントをAlopex DBに挿入（テキスト + ベクトル）
2. ユーザークエリをベクトル化
3. Alopex DBでハイブリッド検索（メタデータフィルタ + ベクトル類似度）
4. 検索結果をLLMのコンテキストとして利用

**期待結果**:
- 単一トランザクションでテキストとベクトルの整合性保証
- 100ms以内でTop-K検索完了

---

### 4.2 UC-002: モバイルアプリのオフライン対応

**アクター**: モバイルアプリ開発者

**前提条件**:
- Rust製モバイルアプリまたはReact Native/Flutter with FFI

**フロー**:
1. Alopex DBを組み込みモードで統合
2. アプリ起動時にローカルDBをオープン
3. オフライン状態でもローカルDBに読み書き
4. オンライン復帰時にサーバーと同期

**期待結果**:
- オフラインでも全機能が動作
- ローカルAI（ベクトル検索）が高速動作

---

### 4.3 UC-003: ブラウザ内RAGチャットボット

**アクター**: Webアプリケーション開発者

**前提条件**:
- モダンブラウザ（Chrome 100+, Firefox 100+）
- WebAssemblyサポート

**フロー**:
1. ページロード時にAlopex WASM版を初期化
2. ドキュメントをIndexedDBに保存
3. ユーザー入力に対してベクトル検索
4. ブラウザ内で完結するプライベートチャット

**期待結果**:
- サーバー不要でプライバシー保護
- 初回ロード<3秒、検索<200ms

---

### 4.4 UC-004: マイクロサービスのデータストア

**アクター**: バックエンドエンジニア

**前提条件**:
- Kubernetes環境

**フロー**:
1. Alopex DBをシングルノードモードでデプロイ
2. マイクロサービスからHTTP/gRPC APIで接続
3. トランザクション保証されたビジネスロジック実行

**期待結果**:
- Postgresと同等のACID保証
- 追加でベクトル検索機能が利用可能

---

### 4.5 UC-005: 分散クラスタでの高可用性

**アクター**: SREエンジニア

**前提条件**:
- 3ノード以上のクラスタ

**フロー**:
1. Alopex DBを分散モードでデプロイ
2. 1ノード障害を検知
3. 自動的にRaftリーダー選出と復旧
4. クライアントは障害を意識せず継続動作

**期待結果**:
- RTO < 5分
- データ損失なし（RPO = 0）

---

## 5. データ要求

### 5.1 データモデル

**テーブル構造**:
```sql
CREATE TABLE example (
  id INT PRIMARY KEY,
  name TEXT NOT NULL,
  age INT,
  metadata JSON,
  embedding VECTOR(768)
);

CREATE INDEX idx_name ON example(name);
CREATE INDEX idx_embedding ON example USING HNSW(embedding);
```

**サポートするデータ型**:
- 数値: INT, BIGINT, FLOAT, DOUBLE
- 文字列: TEXT, VARCHAR(N)
- バイナリ: BLOB
- JSON: JSON
- ベクトル: VECTOR(N)

### 5.2 データボリューム

| モード | 最大データサイズ | 最大テーブル数 | 最大行数 |
|--------|----------------|--------------|---------|
| Embedded | 100GB | 1,000 | 1億 |
| Single-Node | 1TB | 10,000 | 10億 |
| Distributed | 数十TB+ | 100,000+ | 1兆+ |
| WASM | 数GB（IndexedDB制限） | 100 | 1,000万 |

---

## 6. インターフェース要求

### 6.1 プログラミングインターフェース

#### 6.1.1 Embedded API (Rust)

```rust
use alopex_embedded::{Database, Transaction};

let db = Database::open("path/to/db")?;
let txn = db.begin_transaction()?;

txn.execute("INSERT INTO users VALUES (?, ?)", &[1, "Alice"])?;
let rows = txn.query("SELECT * FROM users WHERE id = ?", &[1])?;

txn.commit()?;
```

#### 6.1.2 HTTP API (Single-Node / Distributed)

```bash
# SQL実行
curl -X POST http://localhost:8080/api/v1/sql \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT * FROM users"}'

# ベクトル検索
curl -X POST http://localhost:8080/api/v1/vector/search \
  -H "Content-Type: application/json" \
  -d '{
    "table": "documents",
    "vector": [0.1, 0.2, ...],
    "similarity": "cosine",
    "limit": 10
  }'
```

#### 6.1.3 JavaScript API (WASM)

前述の例を参照。

### 6.2 外部システム連携

**EX-001: Prometheus監視**
- エンドポイント: `/metrics`
- メトリクス例:
  - `alopex_query_duration_seconds`
  - `alopex_transaction_total`
  - `alopex_storage_bytes_total`

**EX-002: ログ出力**
- フォーマット: JSON構造化ログ
- ログレベル: ERROR, WARN, INFO, DEBUG, TRACE
- 出力先: stdout（コンテナ環境）

---

## 7. 品質要求

### 7.1 信頼性

**REL-001: 障害許容**
- 単一ノード障害時も動作継続（3ノードクラスタ）
- 自動フェイルオーバー: <30秒

**REL-002: データ整合性**
- ACID保証
- Raftによる強整合性レプリケーション

### 7.2 保守性

**MAIN-001: テスト**
- 単体テスト: >80% カバレッジ
- 統合テスト: 主要ユースケース網羅
- Chaos Engineering: 障害注入テスト

**MAIN-002: ドキュメント**
- ユーザーガイド
- API リファレンス
- アーキテクチャ設計書

### 7.3 移植性

**PORT-001: マルチプラットフォーム**
- Linux (x86_64, ARM64)
- macOS (Intel, Apple Silicon)
- Windows (x86_64)
- WASM (ブラウザ、Deno、Node.js)

---

## 8. リリース要求

### 8.1 マイルストーン

**v0.1 - Embedded Alopex** (2025 Q2)
- 組み込みKV/SQL/ベクトル
- 統一データファイル形式 (`.alopex`) の実装
- 単一ファイルDB

**v0.2 - Single Node Server** (2025 Q3)
- HTTP/gRPC API
- HNSW導入

**v0.2.5 - WASM Edition (Beta)** (2025 Q3)
- WASM バイナリ
- npm パッケージ公開

**v0.3 - Distributed Alopex (MVP)** (2025 Q4)
- 分散クラスタ
- Range + Raft

**v1.0 - Multi-region Alopex** (2026 Q1)
- マルチリージョン
- 完全な運用機能

---

## 9. 承認

| 役割 | 氏名 | 承認日 | 署名 |
|-----|------|--------|------|
| プロダクトオーナー | - | - | - |
| 技術リード | - | - | - |
| アーキテクト | - | - | - |

---

## 10. 変更履歴

| バージョン | 日付 | 変更者 | 変更内容 |
|----------|------|--------|---------|
| 1.0 | 2025-11-21 | Claude | 初版作成 |

---

## 付録A: 用語集

- **LSM-Tree**: Log-Structured Merge-Tree
- **HNSW**: Hierarchical Navigable Small World
- **Raft**: 分散コンセンサスアルゴリズム
- **ACID**: Atomicity, Consistency, Isolation, Durability
- **RAG**: Retrieval-Augmented Generation
- **WASM**: WebAssembly
- **OPFS**: Origin Private File System

## 付録B: 参考文献

1. CockroachDB Architecture: https://www.cockroachlabs.com/docs/
2. Raft Consensus Algorithm: https://raft.github.io/
3. HNSW Paper: "Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs"
4. PostgreSQL Documentation: https://www.postgresql.org/docs/
