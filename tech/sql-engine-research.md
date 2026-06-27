# Alopex SQL エンジン技術調査メモ

本ドキュメントは v0.3 Local SQL Frontend 実装に向けた技術調査結果をまとめたものである。

---

## 1. Rust における AST 設計ベストプラクティス

### 1.1 再帰型と Box

Rust では型サイズをコンパイル時に決定する必要があるため、再帰的なデータ構造には `Box` による間接参照が必須。

```rust
// ❌ コンパイル不可 - 無限サイズ
enum Expr {
    BinaryOp {
        left: Expr,   // Expr が Expr を含む → 無限再帰
        op: BinaryOp,
        right: Expr,
    },
}

// ✅ Box で解決
enum Expr {
    BinaryOp {
        left: Box<Expr>,
        op: BinaryOp,
        right: Box<Expr>,
    },
}
```

**適用が必要なケース**:

| 構文 | 問題 | 解決策 |
|------|------|--------|
| `a + (b * c)` | Expr → BinaryOp → Expr | `Box<Expr>` |
| `SELECT * FROM (SELECT ...)` | SelectStmt → TableRef → SelectStmt | `Box<SelectStmt>` |
| `WHERE EXISTS (SELECT ...)` | Expr → Subquery → SelectStmt | `Box<SelectStmt>` |
| `CASE WHEN ... THEN ... END` | Expr → CaseExpr → Expr | `Box<Expr>` |

### 1.2 Span（位置情報）の付与

エラーメッセージの品質向上のため、全 AST ノードに位置情報を付与する。

```rust
/// ソースコード上の位置情報
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Span {
    /// 開始バイトオフセット
    pub start: usize,
    /// 終了バイトオフセット
    pub end: usize,
}

/// 位置情報付きノード
#[derive(Debug, Clone)]
pub struct Spanned<T> {
    pub node: T,
    pub span: Span,
}

// 使用例
pub type Statement = Spanned<StatementKind>;
pub type Expr = Spanned<ExprKind>;
```

**参考**: [sqlparser-rs v0.53+](https://docs.rs/sqlparser/) では全 AST ノードに Span を追加中。

### 1.3 AST 走査パターン比較

| パターン | 用途 | 特徴 | 推奨シーン |
|----------|------|------|-----------|
| **match + enum** | 単純な走査 | 軽量、Rust らしい | 小規模 AST、単純な変換 |
| **Visitor trait** | 読み取り専用走査 | ステートフル、情報収集向け | 型チェック、解析 |
| **Fold trait** | AST 変換 | 新構造を生成、関数型スタイル | AST 最適化、正規化 |
| **VisitMut trait** | インプレース変更 | Fold より高速 | 大規模 AST 変換 |

**[SWC の推奨](https://rustdoc.swc.rs/swc_visit/)**:
> 「Fold は使いやすいが遅く、深い AST でスタックオーバーフローに弱い。ほとんどのケースでは十分高速なので Fold から始めるのが良い」

**Alopex SQL での方針**:
- v0.3 初期: `match` で開始（AST が小規模なため）
- 将来: 複雑化したら Visitor/Fold trait を導入

---

## 2. パーサー実装手法

### 2.1 手法比較

| 手法 | 特徴 | メリット | デメリット |
|------|------|----------|-----------|
| **手書き Recursive Descent** | 制御しやすい | 方言拡張が容易、デバッグしやすい | 冗長になりがち |
| **Pratt Parser** | 演算子優先順位処理 | 式パースが優雅 | 学習コスト |
| **Parser Combinator** | 宣言的 | 簡潔、テストしやすい | 大規模で複雑化 |
| **Parser Generator** | 文法ファイルから生成 | 文法と実装の分離 | エラー処理が難しい |

### 2.2 sqlparser-rs の設計

[Apache DataFusion sqlparser-rs](https://github.com/apache/datafusion-sqlparser-rs) は Rust で最も広く使われる SQL パーサー。

**設計哲学**:
- 式パーサー: **Pratt Parser**（演算子優先順位処理）
- 文パーサー: **手書き Recursive Descent**
- パーサージェネレータ不使用の理由:
  - コードがシンプルで簡潔
  - パーサージェネレータより高速
  - 方言拡張が容易

**特徴**:
- 構文解析のみ（意味解析は行わない）
- `CREATE TABLE(x int, x int)` のような意味的に不正な SQL も受け入れる
- 複数の SQL 方言をサポート（PostgreSQL, MySQL, SQLite, etc.）

**最新バージョン**: 0.59.0 (2025-09-24)

### 2.3 Databend の経験（2025年）

[Databend のブログ](https://www.databend.com/blog/category-engineering/2025-09-10-query-parser/) より:

> 「sqlparser-rs を使用していたが、大規模クエリでメモリ効率が問題になった。ゼロコピーパース（トークン/AST が元の入力文字列を参照）を採用した」

**ゼロコピーパースのメリット**:
- メモリ使用量削減
- 文字列コピーのオーバーヘッド削減
- Rust のライフタイムシステムで安全に実現可能

**Alopex SQL での検討**:
- v0.3 初期: 通常のパース（`String` 所有）で開始
- 将来: パフォーマンス要件に応じてゼロコピー化を検討

### 2.4 LakeSail の経験（2025年3月）

[LakeSail のブログ](https://lakesail.com/blog/sql-parser-in-one-week/) より:

> 「高忠実度 AST（SQL 文法と完全に一致）を作成し、AST 定義から SQL ドキュメントを自動生成できるようにした」

**高忠実度 AST のメリット**:
- AST → SQL の往復変換（ラウンドトリップ）が正確
- ドキュメント自動生成が可能
- フォーマッタ実装が容易

---

## 3. Parser Combinator ライブラリ

### 3.1 nom

[nom](https://github.com/rust-bakery/nom) は Rust で最も人気のある Parser Combinator。

**特徴**:
- ゼロコピー設計
- マクロベースとジェネリクスベースの両方の API
- ストリーミング対応

**SQL パース例**:
```rust
use nom::{
    branch::alt,
    bytes::complete::tag_no_case,
    IResult,
};

fn parse_keyword(input: &str) -> IResult<&str, &str> {
    alt((
        tag_no_case("SELECT"),
        tag_no_case("FROM"),
        tag_no_case("WHERE"),
    ))(input)
}
```

### 3.2 combine

[combine](https://docs.rs/combine/) は型安全性を重視した Parser Combinator。

**特徴**:
- 型安全なエラーメッセージ
- バックトラッキング制御が柔軟
- 非同期パース対応

### 3.3 左再帰の問題

Parser Combinator は左再帰文法を直接扱えない。

```
// 左再帰（無限ループ）
expr := expr '+' term | term
```

**解決策**:
1. 文法を右再帰に変換
2. Pratt Parser を使用（推奨）
3. 反復子（`many`, `fold`）で対処

---

## 4. Alopex SQL への推奨アーキテクチャ

### 4.1 AST 構造

```rust
// --- 位置情報 ---
#[derive(Debug, Clone, Copy)]
pub struct Span {
    pub start: usize,
    pub end: usize,
}

// --- 文 (Statement) ---
#[derive(Debug, Clone)]
pub struct Statement {
    pub kind: StatementKind,
    pub span: Span,
}

#[derive(Debug, Clone)]
pub enum StatementKind {
    Select(SelectStmt),
    Insert(InsertStmt),
    Update(UpdateStmt),
    Delete(DeleteStmt),
    CreateTable(CreateTableStmt),
    DropTable(DropTableStmt),
    CreateIndex(CreateIndexStmt),
    DropIndex(DropIndexStmt),
}

// --- 式 (Expression) ---
#[derive(Debug, Clone)]
pub struct Expr {
    pub kind: ExprKind,
    pub span: Span,
}

#[derive(Debug, Clone)]
pub enum ExprKind {
    // リテラル
    Literal(Literal),

    // 識別子
    Column(ColumnRef),

    // 二項演算（再帰には Box）
    BinaryOp {
        left: Box<Expr>,
        op: BinaryOp,
        right: Box<Expr>,
    },

    // 単項演算
    UnaryOp {
        op: UnaryOp,
        expr: Box<Expr>,
    },

    // 関数呼び出し
    FunctionCall {
        name: String,
        args: Vec<Expr>,
    },

    // Alopex 拡張: ベクトルリテラル
    VectorLiteral(Vec<f32>),

    // 将来拡張: サブクエリ（Box で準備）
    // Subquery(Box<SelectStmt>),
}

// --- データ型 ---
#[derive(Debug, Clone)]
pub enum DataType {
    Integer,
    BigInt,
    Float,
    Double,
    Text,
    Blob,
    Boolean,
    Timestamp,
    // Alopex 拡張
    Vector { dim: usize, metric: Metric },
}

#[derive(Debug, Clone, Copy)]
pub enum Metric {
    Cosine,
    L2,
    InnerProduct,
}
```

### 4.2 パーサー構成

```
alopex-sql/src/
├── parser/
│   ├── mod.rs          # Parser 構造体、エントリポイント
│   ├── lexer.rs        # Lexer（トークン化）
│   ├── token.rs        # Token 型定義
│   ├── ast.rs          # AST 型定義
│   ├── expr.rs         # 式パーサー（Pratt Parser）
│   ├── stmt.rs         # 文パーサー（Recursive Descent）
│   └── error.rs        # ParseError 型
├── catalog/
│   ├── mod.rs          # Catalog trait
│   └── memory.rs       # InMemoryCatalog
├── planner/
│   ├── mod.rs          # Planner
│   └── logical.rs      # LogicalPlan
├── executor/
│   ├── mod.rs          # Executor
│   └── eval.rs         # 式評価
└── lib.rs              # 公開 API
```

### 4.3 実装戦略

| フェーズ | 内容 | 依存ライブラリ |
|----------|------|---------------|
| v0.3.1 | Lexer/AST | なし（手書き） |
| v0.3.2-4 | Parser | なし（Pratt + Recursive Descent） |
| v0.3.5 | Catalog/Planner | alopex-core |
| v0.3.6 | Executor | alopex-core |
| v0.3.7 | Vector 拡張 | alopex-core (vector) |
| v0.3.8 | embedded 統合 | alopex-embedded |

**sqlparser-rs 利用の検討**:
- メリット: 実績あり、多機能
- デメリット: Vector 拡張のカスタマイズが必要、依存が増える
- **判断**: v0.3 では自前実装（学習目的＋完全な制御）、将来的に再検討

---

## 5. 参考資料

### 5.1 ライブラリ・ツール

- [sqlparser-rs (Apache DataFusion)](https://github.com/apache/datafusion-sqlparser-rs) - Rust SQL パーサーのデファクト
- [nom](https://github.com/rust-bakery/nom) - Parser Combinator
- [combine](https://docs.rs/combine/) - 型安全な Parser Combinator
- [parsel](https://docs.rs/parsel) - Derive ベースのパーサー
- [SWC Visit](https://rustdoc.swc.rs/swc_visit/) - Visitor/Fold パターンの実装例

### 5.2 記事・ブログ

- [Databend: Why We Built Our Own SQL Parser (2025)](https://www.databend.com/blog/category-engineering/2025-09-10-query-parser/)
- [LakeSail: Writing a Rust SQL Parser in One Week (2025)](https://lakesail.com/blog/sql-parser-in-one-week/)
- [Cloudflare: Building fast interpreters in Rust](https://blog.cloudflare.com/building-fast-interpreters-in-rust/)
- [Parsing in Rust with nom (LogRocket)](https://blog.logrocket.com/parsing-in-rust-with-nom/)
- [Create Your Own Programming Language with Rust](https://createlang.rs/01_calculator/ast.html)

### 5.3 設計パターン

- [Rust Design Patterns: Visitor](https://rust-unofficial.github.io/patterns/patterns/behavioural/visitor.html)
- [Rust Design Patterns: Fold](https://rust-unofficial.github.io/patterns/patterns/creational/fold.html)
- [The Visitor Pattern Reinvented (2025)](https://medium.com/@bugsybits/the-visitor-pattern-reinvented-enums-and-pattern-matching-in-rust-978a02023b0e)
- [In Search of the Perfect Fold](https://thunderseethe.dev/posts/in-search-of-the-perfect-fold/)

---

## 6. 参考 OSS プロジェクト ソースパス

本プロジェクトの `reference/` ディレクトリには各種データベースの OSS ソースコードが配置されている。
以下は alopex-sql 実装において参考にすべきソースパスである。

### 6.1 CnosDB (Rust) - 最重要参考

Rust で実装された時系列データベース。alopex-sql と同じ言語のため、コードパターンを直接参考にできる。

#### SQL Parser / Planner
```
reference/cnosdb/query_server/query/src/sql/
├── parser.rs          # SQL パーサー実装
├── planner.rs         # 論理プラン生成
├── logical/           # 論理プラン定義
└── physical/          # 物理プラン定義
```

#### Storage Engine
```
reference/cnosdb/tskv/src/
├── kvcore.rs          # KV コア実装
├── wal/               # Write-Ahead Log
├── tsm/               # Time-Series Merge Tree
├── index/             # インデックス実装
└── memcache/          # メモリキャッシュ
```

**参考ポイント**:
- Rust での Parser Combinator / 手書きパーサーパターン
- KV 層との統合パターン
- WAL 実装

---

### 6.2 TiDB (Go) - 設計参考

NewSQL の先駆者。Row ↔ KV エンコーディングの設計が秀逸。

#### SQL Parser
```
reference/tidb/pkg/parser/
├── lexer.go           # 字句解析器
├── parser.y           # YACC 文法定義
├── parser.go          # 生成されたパーサー
└── ast/               # AST 定義
    ├── ddl.go         # CREATE/ALTER/DROP
    ├── dml.go         # SELECT/INSERT/UPDATE/DELETE
    ├── expressions.go # 式の AST
    └── functions.go   # 関数定義
```

#### Row ↔ KV Encoding（重要）
```
reference/tidb/pkg/tablecodec/
└── tablecodec.go      # テーブルデータの KV エンコーディング
                       # - EncodeRowKey: row_id → key
                       # - EncodeIndexKey: index_value → key
                       # - DecodeRecordKey: key → row_id
```

#### Key 設計
```
reference/tidb/pkg/kv/
├── key.go             # Key 型定義
├── txn.go             # トランザクション抽象
└── memdb/             # メモリ DB 実装
```

**参考ポイント**:
- Key Encoding Scheme（Big-Endian、prefix-based）
- Row ↔ KV 変換ロジック
- Index Key の構造

---

### 6.3 CockroachDB (Go) - Storage 参考

分散 SQL の代表格。MVCC 実装と Row Encoding が参考になる。

#### SQL Parser
```
reference/cockroach/pkg/sql/parser/
├── sql.y              # YACC 文法（巨大）
├── lexer.go           # 字句解析器
├── scan.go            # スキャナー
└── parse.go           # パーサーエントリ
```

#### Row Encoding（重要）
```
reference/cockroach/pkg/sql/rowenc/
├── index_encoding.go  # インデックスエンコーディング
├── column_type_encoding.go  # 列型エンコーディング
├── vector_index.go    # ベクトルインデックス！（参考必須）
└── rowenc.go          # 行エンコーディング
```

#### Storage Engine
```
reference/cockroach/pkg/storage/
├── mvcc.go            # MVCC 実装
├── pebble.go          # Pebble 統合
├── engine_key.go      # エンジンキー構造
└── batch.go           # バッチ操作
```

**参考ポイント**:
- Vector Index の KV 表現（`vector_index.go`）
- MVCC タイムスタンプ管理
- Pebble (RocksDB fork) との統合

---

### 6.4 YugabyteDB (C++) - Vector Index 参考

PostgreSQL 互換の分散 DB。DocDB 層でのベクトルインデックス実装が参考になる。

#### Document DB Layer
```
reference/yugabyte-db/src/yb/docdb/
├── docdb.cc           # Document DB コア
├── doc_key.cc         # ドキュメントキー
├── doc_vector_index.cc # ベクトルインデックス実装！
└── primitive_value.cc # プリミティブ値エンコーディング
```

**参考ポイント**:
- HNSW/IVF インデックスの永続化
- ベクトル検索の KV 表現

---

### 6.5 QuestDB (Java) - Parser 参考

時系列 DB。手書きの高速パーサー実装が参考になる。

#### SQL Engine
```
reference/questdb/core/src/main/java/io/questdb/griffin/
├── SqlParser.java     # 手書きパーサー
├── SqlLexer.java      # 字句解析器
├── SqlCompiler.java   # コンパイラー
└── model/             # AST/モデル定義
```

**参考ポイント**:
- 高速な手書きパーサー設計
- 式パーサー（Pratt Parser 風）

---

### 6.6 FoundationDB (C++) - 設計哲学参考

分散 KV ストアの基盤。レイヤードアーキテクチャの設計哲学が参考になる。

```
reference/foundationdb/
├── fdbserver/         # サーバー実装
├── fdbclient/         # クライアントライブラリ
└── bindings/          # 言語バインディング
```

**参考ポイント**:
- レイヤードアーキテクチャ設計
- トランザクション分離レベル

---

### 6.7 alopex-sql 実装における推奨参照順序

#### Phase 1: Parser/AST (v0.1.0)
1. **CnosDB** `parser.rs` - Rust 実装パターン
2. **QuestDB** `SqlParser.java` - 手書きパーサー設計
3. **TiDB** `ast/` - AST 構造設計

#### Phase 2: Storage Engine Layer (v0.1.1-storage)
1. **TiDB** `tablecodec.go` - Row ↔ KV エンコーディング（最重要）
2. **CockroachDB** `rowenc/` - 列型エンコーディング
3. **CnosDB** `kvcore.rs` - Rust KV 統合

#### Phase 3: Vector Extension (v0.1.3)
1. **CockroachDB** `vector_index.go` - ベクトルインデックス KV 表現（最重要）
2. **YugabyteDB** `doc_vector_index.cc` - HNSW 永続化

#### Phase 4: Transaction Bridge (v0.1.1-storage)
1. **CockroachDB** `mvcc.go` - MVCC 実装
2. **TiDB** `txn.go` - トランザクション抽象

---

## 7. 更新履歴

| 日付 | 内容 |
|------|------|
| 2025-11-29 | 初版作成 |
| 2025-11-29 | 参考 OSS プロジェクト ソースパス（セクション 6）追加 |
| 2025-11-29 | 分散DBにおける検索インデックス設計（セクション 8）追加 |
| 2025-12-02 | sqlparser-rs コード調査結果（セクション 9）追加 |
| 2026-06-26 | Rust 以外の軽量言語によるパーサー実装調査（セクション 10）追加 |
| 2026-06-27 | Nim / Roc の開発状況とマイルストーン（セクション 10.2）追加 |

---

## 8. 分散DBにおける検索インデックス設計

### アイディアノート（要点と全体像）

### 8.1 基本思想：索引の三軸分離（整合性・完全一致・類似度）

分散環境で高速・高精度の検索インデックスを構築するためには、
以下の3つを**別々の責任範囲として保持する**のが最も堅牢である。

1. **更新順序（時系列）**

   * クラスタ全体で単一の論理時刻
   * TiKV/PD の TSO（Timestamp Oracle）方式が理想
   * UUIDv7 のようなタイムスタンプ付きIDにも落とせる

2. **完全一致（同一性保証）**

   * SHA-256 のような暗号学的ハッシュ
   * 冪等性・重複抑止・改ざん検知・再インデックス確認に使う

3. **類似性（変更の近さ・意味的距離）**

   * SimHash / MinHash / LSH
   * あるいは embedding によるベクトル距離
   * 「どの過去バージョンに最も近いか？」の判定に有効

この3つが揃うと、
**「新しい」「正しい」「似ている」**という三階層で検索・管理ができる。

---

### 8.2 提案するメタデータ構造（分散インデックスの基盤）

```
resource_id      : 論理リソースID
version_id       : TSO（クラスタ論理時刻）または UUIDv7 互換ID
content_sha256   : 完全一致判定用（冪等性）
content_simhash  : 類似度判定（近さ、差分把握）
embedding_vec_id : ベクトル検索用（semantic search）
raw_json         : 実データ
meta             : 作成者ノード、更新理由、履歴情報など
```

この構造は、**分散RDBが必要とする要件をすべて満たしている**。

* 時系列：`version_id`
* 正確性：`content_sha256`
* 類似性：`simhash`
* 意味検索：`embedding`
* シャーディング：`resource_id`
* 再構築可能性：`raw_json`
* トレーサビリティ：`meta`

---

### 8.3 TiKV/TSO の採用理由（分散インデックスの核）

TiKV 方式（TSO）は分散トランザクションにおける
**"どちらが新しいかを全ノードで同一に判断できる論理時間"** を提供する。

採用のメリット：

* インデックス更新の順序がクラスタ全体で完全に決まる
* Snapshot Isolation の境界として利用できる
* 遅延 index の再構築が容易
* base table と index の整合性が自然に揃う
* 冪等な更新適用が可能
* 分散環境での書き込み競合が劇的に整理される

つまり **分散インデックスにおける"絶対時刻レイヤー"** として最適。

---

### 8.4 この構造で設計できるインデックス群

#### (1) **Primary Index（主キーインデックス）**

`(resource_id, version_id)`
→ 行の最新状態・更新履歴の管理

#### (2) **完全一致インデックス（SHA-256）**

`(resource_id, sha256)`
→ 冪等性、重複更新の判別、整合性確認

#### (3) **近似インデックス（SimHash/MinHash）**

`simhash` から Hamming 距離で近いバージョン検索
→ 「内容が近い」「微小更新」「差分適用の最適化」に効く

#### (4) **ベクトルインデックス（embedding）**

ベクトルストアとの連携
→ 意味検索・キーワード近似・類義語対応

#### (5) **時系列インデックス（TSO/UUIDv7）**

トランザクションの可視性境界
→ Snapshot read, point-in-time read

#### (6) **差分インデックス**

`sha256` と `simhash` を組み合わせて差分の適用範囲を最適化
→ インデックス再構築が高速化

#### (7) **ハイブリッド検索インデックス**

構造化（B-tree/KV）＋ 類似度検索 ＋ ベクトル検索
→ 分散DBで「意味検索 × 構造化検索」が可能

---

### 8.5 インデックス更新フロー（alopex/chirps 用）

1. **更新要求を受ける**
2. chirps-TSO から `version_id` を発行
3. JSON を正規化
4. `sha256`・`simhash`・embedding を計算
5. `(resource_id, version_id, sha256, simhash, embedding_vec_id, raw_json)` を保存
6. インデックス（B-tree/LSM/vector index）を更新
7. `version_id` を「適用済み index 境界」として記録

このフローにより：

* 順序一貫
* 冪等性あり
* 高速差分
* 意味検索対応

という近代分散DBの条件を満たす。

---

### 8.6 分散検索エンジンとしての強み

この構造は、以下を「単一のデータモデル」で扱える：

* **完全一致検索**
* **構造化検索**
* **時間順検索**
* **差分ベースの近似検索**
* **semantic vector search**

これは Google Spanner / TiKV / CockroachDB にもまだ無い統合モデルであり、
alopex/chirps が優位に立てる部分。

---

### 8.7 さらに得られる副次的メリット

* インデックス再構築が非常に容易
  → version_id の範囲で missing index を検出
* ノード障害後の自己修復が低コスト
  → raw_json × version_id × sha256
* 変更ログがそのまま「完全なイベントソース」になる
* RDB/検索エンジン/ベクトルDB の 3 層を横断可能

---

### 8.8 結論：これは「次世代分散インデックス」の設計図である

resource/sha256/simhash/embedding/version_id の構造は、
TSO（TiKV方式）と組み合わさることで：

**分散RDBの主インデックス
＋ 構造化サーチ
＋ 類似検索
＋ ベクトル検索
＋ スナップショット読み取り
＋ 冪等な差分処理**

を全て統合した **新しい分散インデックスモデル** になる。

これは現行の DB がまだ実装していない領域であり、
alopex/chirps の武器になり得る。

---

## 9. sqlparser-rs コード調査

本セクションは `reference/datafusion-sqlparser-rs` のコードを調査し、Rust における SQL パーサー実装の具体的なパターンを抽出したものである。

### 9.1 アーキテクチャ概要

sqlparser-rs は Apache DataFusion プロジェクトの一部として開発されている、Rust で最も広く使われる SQL パーサーである。

**モジュール構成**:
```
src/
├── lib.rs              # 公開 API エントリポイント
├── tokenizer.rs        # 字句解析器（Lexer）
├── keywords.rs         # SQL キーワード定義
├── parser/
│   ├── mod.rs          # パーサー本体（~18,000行）
│   └── alter.rs        # ALTER 文専用パーサー
├── ast/
│   ├── mod.rs          # AST 型定義とエクスポート
│   ├── query.rs        # SELECT/Query 関連の AST
│   ├── ddl.rs          # CREATE/ALTER/DROP の AST
│   ├── dml.rs          # INSERT/UPDATE/DELETE の AST
│   ├── dcl.rs          # GRANT/REVOKE の AST
│   ├── data_type.rs    # データ型定義
│   ├── operator.rs     # 演算子定義
│   ├── value.rs        # リテラル値定義
│   ├── visitor.rs      # Visitor パターン実装
│   ├── spans.rs        # Spanned trait 実装
│   └── helpers/        # ビルダーパターンなどのヘルパー
├── dialect/
│   ├── mod.rs          # Dialect trait と共通実装
│   ├── generic.rs      # GenericDialect
│   ├── postgresql.rs   # PostgreSqlDialect
│   ├── mysql.rs        # MySqlDialect
│   └── ...             # その他の方言
└── derive/
    └── src/lib.rs      # Visit/VisitMut derive マクロ
```

### 9.2 Tokenizer（字句解析器）の実装

#### Token 定義

```rust
/// SQL Token enumeration
pub enum Token {
    EOF,                              // 終端マーカー
    Word(Word),                       // キーワードまたは識別子
    Number(String, bool),             // 数値リテラル（long フラグ付き）
    SingleQuotedString(String),       // 'string'
    DoubleQuotedString(String),       // "string"
    DollarQuotedString(DollarQuotedString), // $$string$$ (PostgreSQL)

    // 演算子
    Comma, Eq, Neq, Lt, Gt, LtEq, GtEq,
    Plus, Minus, Mul, Div, Mod,
    LParen, RParen, LBracket, RBracket, LBrace, RBrace,
    Period, Colon, DoubleColon, SemiColon,

    // PostgreSQL 固有演算子
    Arrow,          // ->
    LongArrow,      // ->>
    HashArrow,      // #>
    AtArrow,        // @>
    // ... 多数の方言固有トークン
}
```

#### Word 構造体

```rust
/// キーワードまたはクォート付き識別子
pub struct Word {
    /// クォートなしの値
    pub value: String,
    /// クォートスタイル（"、`、[、None）
    pub quote_style: Option<char>,
    /// マッチしたキーワード（クォートなしの場合）
    pub keyword: Keyword,
}
```

#### 位置情報（Span）の設計

```rust
/// ソース内の位置
pub struct Location {
    pub line: u64,    // 1-based
    pub column: u64,  // 1-based
}

/// 範囲（開始〜終了）
pub struct Span {
    pub start: Location,
    pub end: Location,
}

impl Span {
    /// 空の Span（位置不明）
    pub const fn empty() -> Span {
        Span {
            start: Location { line: 0, column: 0 },
            end: Location { line: 0, column: 0 },
        }
    }

    /// 2つの Span の和集合（最小開始〜最大終了）
    pub fn union(&self, other: &Span) -> Span {
        match (self, other) {
            (&Span::EMPTY, _) => *other,  // 空は無視
            (_, &Span::EMPTY) => *self,
            _ => Span {
                start: cmp::min(self.start, other.start),
                end: cmp::max(self.end, other.end),
            },
        }
    }
}

/// 位置情報付きトークン
pub struct TokenWithSpan {
    pub token: Token,
    pub span: Span,
}
```

### 9.3 Parser（構文解析器）の実装

#### Parser 構造体

```rust
pub struct Parser<'a> {
    /// トークン列
    tokens: Vec<TokenWithSpan>,
    /// 現在位置（次に処理するトークンのインデックス）
    index: usize,
    /// パーサー状態（Normal, ConnectBy, ColumnDefinition）
    state: ParserState,
    /// SQL 方言
    dialect: &'a dyn Dialect,
    /// パーサーオプション
    options: ParserOptions,
    /// 再帰深度カウンター（スタックオーバーフロー防止）
    recursion_counter: RecursionCounter,
}
```

#### 基本的な使用パターン

```rust
// 基本的な使い方
let dialect = GenericDialect {};
let statements = Parser::parse_sql(&dialect, "SELECT * FROM foo")?;

// カスタマイズ
let statements = Parser::new(&dialect)
    .with_recursion_limit(100)          // 再帰制限
    .with_options(ParserOptions {
        trailing_commas: true,           // 末尾カンマ許可
        unescape: true,                  // エスケープ処理
        require_semicolon_stmt_delimiter: true,
    })
    .try_with_sql(sql)?
    .parse_statements()?;
```

#### 文パーサー（Recursive Descent）

```rust
/// 単一の文をパース
pub fn parse_statement(&mut self) -> Result<Statement, ParserError> {
    let _guard = self.recursion_counter.try_decrease()?;

    // 方言による上書きを許可
    if let Some(statement) = self.dialect.parse_statement(self) {
        return statement;
    }

    let next_token = self.next_token();
    match &next_token.token {
        Token::Word(w) => match w.keyword {
            Keyword::SELECT | Keyword::WITH | Keyword::VALUES | Keyword::FROM => {
                self.prev_token();
                self.parse_query().map(Statement::Query)
            }
            Keyword::CREATE => self.parse_create(),
            Keyword::INSERT => self.parse_insert(next_token),
            Keyword::UPDATE => self.parse_update(next_token),
            Keyword::DELETE => self.parse_delete(next_token),
            // ... 他のキーワード
            _ => self.expected("an SQL statement", next_token),
        },
        Token::LParen => {
            self.prev_token();
            self.parse_query().map(Statement::Query)
        }
        _ => self.expected("an SQL statement", next_token),
    }
}
```

### 9.4 Pratt Parser（式パーサー）の実装

sqlparser-rs は**演算子優先順位パーサー（Pratt Parser）**を式の解析に使用している。

#### 優先順位の定義

```rust
/// 演算子の優先順位
pub enum Precedence {
    Period,       // 100: . (メンバアクセス)
    DoubleColon,  // 50:  :: (PostgreSQL キャスト)
    AtTz,         // 41:  AT TIME ZONE
    MulDivModOp,  // 40:  *, /, %
    PlusMinus,    // 30:  +, -
    Xor,          // 24:  XOR
    Ampersand,    // 23:  &
    Caret,        // 22:  ^
    Pipe,         // 21:  |
    Between,      // 20:  BETWEEN, =, !=, <, >, <=, >=
    Eq,           // 20:  比較演算子
    Like,         // 19:  LIKE, ILIKE
    Is,           // 17:  IS NULL, IS NOT NULL
    PgOther,      // 16:  PostgreSQL 固有演算子
    UnaryNot,     // 15:  NOT
    And,          // 10:  AND
    Or,           // 5:   OR
}

impl Dialect {
    /// 優先順位を数値に変換
    fn prec_value(&self, prec: Precedence) -> u8 {
        match prec {
            Precedence::Period => 100,
            Precedence::DoubleColon => 50,
            // ...
            Precedence::Or => 5,
        }
    }

    /// 不明な演算子の優先順位
    fn prec_unknown(&self) -> u8 { 0 }
}
```

#### Pratt Parser のコアアルゴリズム

```rust
/// 式をパース（エントリポイント）
pub fn parse_expr(&mut self) -> Result<Expr, ParserError> {
    self.parse_subexpr(self.dialect.prec_unknown())
}

/// 優先順位が変わるまでトークンをパース
pub fn parse_subexpr(&mut self, precedence: u8) -> Result<Expr, ParserError> {
    let _guard = self.recursion_counter.try_decrease()?;

    // 1. prefix（前置式）をパース
    let mut expr = self.parse_prefix()?;

    // 2. compound（複合式）を処理
    expr = self.parse_compound_expr(expr, vec![])?;

    // 3. infix（中置式）をループで処理
    loop {
        let next_precedence = self.get_next_precedence()?;

        // 現在の優先順位以下なら終了
        if precedence >= next_precedence {
            break;
        }

        // ピリオドは compound で処理済みなのでスキップ
        if Token::Period == self.peek_token_ref().token {
            break;
        }

        // infix をパース
        expr = self.parse_infix(expr, next_precedence)?;
    }
    Ok(expr)
}
```

#### prefix パーサー（前置式）

```rust
pub fn parse_prefix(&mut self) -> Result<Expr, ParserError> {
    // 方言による上書きを許可
    if let Some(prefix) = self.dialect.parse_prefix(self) {
        return prefix;
    }

    let next_token = self.next_token();
    match next_token.token {
        Token::Word(w) => {
            match w.keyword {
                Keyword::TRUE | Keyword::FALSE => {
                    Ok(Expr::Value(self.parse_value()?))
                }
                Keyword::NULL => {
                    Ok(Expr::Value(self.parse_value()?))
                }
                Keyword::CASE => Ok(self.parse_case_expr()?),
                Keyword::CAST => Ok(self.parse_cast_expr(CastKind::Cast)?),
                Keyword::NOT => {
                    Ok(Expr::UnaryOp {
                        op: UnaryOperator::Not,
                        expr: Box::new(
                            self.parse_subexpr(self.dialect.prec_value(Precedence::UnaryNot))?
                        ),
                    })
                }
                // ... 他のキーワード
                _ => self.parse_expr_prefix_by_unreserved_word(&w, span),
            }
        }
        Token::Minus => {
            Ok(Expr::UnaryOp {
                op: UnaryOperator::Minus,
                expr: Box::new(
                    self.parse_subexpr(self.dialect.prec_value(Precedence::PlusMinus))?
                ),
            })
        }
        Token::LParen => {
            // サブクエリまたは括弧付き式
            // ...
        }
        // ...
    }
}
```

#### infix パーサー（中置式）

```rust
pub fn parse_infix(&mut self, expr: Expr, precedence: u8) -> Result<Expr, ParserError> {
    // 方言による上書きを許可
    if let Some(infix) = self.dialect.parse_infix(self, &expr, precedence) {
        return infix;
    }

    let tok = self.next_token();
    match &tok.token {
        Token::Plus | Token::Minus | Token::Mul | Token::Div | Token::Mod => {
            let op = match &tok.token {
                Token::Plus => BinaryOperator::Plus,
                Token::Minus => BinaryOperator::Minus,
                Token::Mul => BinaryOperator::Multiply,
                Token::Div => BinaryOperator::Divide,
                Token::Mod => BinaryOperator::Modulo,
                _ => unreachable!(),
            };
            Ok(Expr::BinaryOp {
                left: Box::new(expr),
                op,
                right: Box::new(self.parse_subexpr(precedence)?),
            })
        }
        Token::Eq | Token::Neq | Token::Lt | Token::Gt | ... => {
            // 比較演算子
        }
        Token::Word(w) => match w.keyword {
            Keyword::AND => {
                Ok(Expr::BinaryOp {
                    left: Box::new(expr),
                    op: BinaryOperator::And,
                    right: Box::new(self.parse_subexpr(precedence)?),
                })
            }
            Keyword::BETWEEN => {
                // BETWEEN ... AND ... の特殊処理
                self.parse_between(expr, false)
            }
            Keyword::LIKE | Keyword::ILIKE => {
                // LIKE パターンマッチング
            }
            // ...
        }
        _ => {
            parser_err!(format!("No infix parser for token {:?}", tok.token), tok.span)
        }
    }
}
```

### 9.5 Dialect（SQL 方言）システム

#### Dialect trait

```rust
pub trait Dialect: Debug + Any {
    /// 方言の TypeId を返す
    fn dialect(&self) -> TypeId { self.type_id() }

    /// クォート付き識別子の開始文字判定
    fn is_delimited_identifier_start(&self, ch: char) -> bool {
        ch == '"' || ch == '`'
    }

    /// 識別子の開始文字判定
    fn is_identifier_start(&self, ch: char) -> bool;

    /// 識別子の構成文字判定
    fn is_identifier_part(&self, ch: char) -> bool;

    /// バックスラッシュエスケープのサポート
    fn supports_string_literal_backslash_escape(&self) -> bool { false }

    /// FILTER (WHERE ...) のサポート
    fn supports_filter_during_aggregation(&self) -> bool { false }

    /// 末尾カンマのサポート
    fn supports_trailing_commas(&self) -> bool { false }

    /// 文パーサーの上書き
    fn parse_statement(&self, _parser: &mut Parser) -> Option<Result<Statement, ParserError>> {
        None
    }

    /// 前置式パーサーの上書き
    fn parse_prefix(&self, _parser: &mut Parser) -> Option<Result<Expr, ParserError>> {
        None
    }

    /// 中置式パーサーの上書き
    fn parse_infix(
        &self,
        _parser: &mut Parser,
        _expr: &Expr,
        _precedence: u8,
    ) -> Option<Result<Expr, ParserError>> {
        None
    }

    /// 次のトークンの優先順位を取得
    fn get_next_precedence(&self, _parser: &Parser) -> Option<Result<u8, ParserError>> {
        None
    }

    /// 優先順位の数値変換
    fn prec_value(&self, prec: Precedence) -> u8 { ... }

    /// 不明な優先順位
    fn prec_unknown(&self) -> u8 { 0 }
}
```

#### 方言固有の実装例（PostgreSQL）

```rust
impl Dialect for PostgreSqlDialect {
    fn is_identifier_start(&self, ch: char) -> bool {
        ch.is_alphabetic() || ch == '_'
    }

    fn is_identifier_part(&self, ch: char) -> bool {
        ch.is_alphanumeric() || ch == '$' || ch == '_'
    }

    fn supports_filter_during_aggregation(&self) -> bool {
        true  // PostgreSQL は FILTER をサポート
    }

    fn supports_unicode_string_literal(&self) -> bool {
        true  // U&'...' 構文をサポート
    }
}
```

#### 方言チェックマクロ

```rust
/// 方言判定マクロ
macro_rules! dialect_of {
    ($parsed_dialect:ident is $($dialect_type:ty)|+) => {
        ($($parsed_dialect.dialect.is::<$dialect_type>())||+)
    };
}

// 使用例
if dialect_of!(self is PostgreSqlDialect | GenericDialect) {
    // PostgreSQL または Generic 方言固有の処理
}
```

### 9.6 Visitor パターンの実装

#### Visit trait と derive マクロ

```rust
/// 読み取り専用の走査
pub trait Visit {
    fn visit<V: Visitor>(&self, visitor: &mut V) -> ControlFlow<V::Break>;
}

/// 変更可能な走査
pub trait VisitMut {
    fn visit<V: VisitorMut>(&mut self, visitor: &mut V) -> ControlFlow<V::Break>;
}

// derive マクロで自動生成
#[cfg_attr(feature = "visitor", derive(Visit, VisitMut))]
#[cfg_attr(feature = "visitor", visit(with = "visit_query"))]
pub struct Query {
    pub with: Option<With>,
    pub body: Box<SetExpr>,
    // ...
}
```

#### Visitor trait

```rust
pub trait Visitor {
    /// 早期終了時の戻り値型
    type Break;

    /// Query ノードの前処理
    fn pre_visit_query(&mut self, _query: &Query) -> ControlFlow<Self::Break> {
        ControlFlow::Continue(())
    }

    /// Query ノードの後処理
    fn post_visit_query(&mut self, _query: &Query) -> ControlFlow<Self::Break> {
        ControlFlow::Continue(())
    }

    /// Expr ノードの前処理
    fn pre_visit_expr(&mut self, _expr: &Expr) -> ControlFlow<Self::Break> {
        ControlFlow::Continue(())
    }

    /// Expr ノードの後処理
    fn post_visit_expr(&mut self, _expr: &Expr) -> ControlFlow<Self::Break> {
        ControlFlow::Continue(())
    }

    /// リレーション（テーブル）の前処理
    fn pre_visit_relation(&mut self, _relation: &ObjectName) -> ControlFlow<Self::Break> {
        ControlFlow::Continue(())
    }

    /// Statement ノードの前処理
    fn pre_visit_statement(&mut self, _statement: &Statement) -> ControlFlow<Self::Break> {
        ControlFlow::Continue(())
    }
    // ...
}
```

#### Visitor の使用例

```rust
#[derive(Default)]
struct TableCollector {
    tables: Vec<String>,
}

impl Visitor for TableCollector {
    type Break = ();

    fn pre_visit_relation(&mut self, relation: &ObjectName) -> ControlFlow<Self::Break> {
        self.tables.push(relation.to_string());
        ControlFlow::Continue(())
    }
}

// 使用
let sql = "SELECT * FROM foo JOIN bar ON foo.id = bar.id";
let statements = Parser::parse_sql(&GenericDialect{}, sql)?;
let mut collector = TableCollector::default();
statements.visit(&mut collector);
assert_eq!(collector.tables, vec!["foo", "bar"]);
```

### 9.7 Spanned trait（位置情報取得）

```rust
/// AST ノードの位置情報を取得する trait
pub trait Spanned {
    /// このノードの Span を返す
    fn span(&self) -> Span;
}

impl Spanned for Query {
    fn span(&self) -> Span {
        let Query {
            with, body, order_by, limit_clause, fetch, ...
        } = self;

        // 子ノードの Span の和集合を計算
        union_spans(
            with.iter().map(|i| i.span())
                .chain(core::iter::once(body.span()))
                .chain(order_by.as_ref().map(|i| i.span()))
                .chain(limit_clause.as_ref().map(|i| i.span()))
                .chain(fetch.as_ref().map(|i| i.span())),
        )
    }
}

/// Span の和集合を計算するヘルパー
fn union_spans<I: Iterator<Item = Span>>(iter: I) -> Span {
    Span::union_iter(iter)
}
```

### 9.8 エラーハンドリング

```rust
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ParserError {
    TokenizerError(String),
    ParserError(String),
    RecursionLimitExceeded,
}

/// エラー生成マクロ
macro_rules! parser_err {
    ($MSG:expr, $loc:expr) => {
        Err(ParserError::ParserError(format!("{}{}", $MSG, $loc)))
    };
}

impl Parser<'_> {
    /// 期待するトークンがなかった場合のエラー
    pub fn expected<T>(
        &self,
        expected: &str,
        found: TokenWithSpan,
    ) -> Result<T, ParserError> {
        parser_err!(
            format!("Expected {expected}, found: {}", found.token),
            found.span
        )
    }
}
```

### 9.9 再帰深度制限

```rust
/// スタックオーバーフロー防止のための再帰カウンター
pub(crate) struct RecursionCounter {
    remaining_depth: Rc<Cell<usize>>,
}

impl RecursionCounter {
    pub fn new(remaining_depth: usize) -> Self {
        Self {
            remaining_depth: Rc::new(remaining_depth.into()),
        }
    }

    /// 深度を1減らす（0になったらエラー）
    pub fn try_decrease(&self) -> Result<DepthGuard, ParserError> {
        let old_value = self.remaining_depth.get();
        if old_value == 0 {
            Err(ParserError::RecursionLimitExceeded)
        } else {
            self.remaining_depth.set(old_value - 1);
            Ok(DepthGuard::new(Rc::clone(&self.remaining_depth)))
        }
    }
}

/// Drop 時に深度を復元する RAII ガード
pub struct DepthGuard {
    remaining_depth: Rc<Cell<usize>>,
}

impl Drop for DepthGuard {
    fn drop(&mut self) {
        let old_value = self.remaining_depth.get();
        self.remaining_depth.set(old_value + 1);
    }
}

// デフォルト深度
const DEFAULT_REMAINING_DEPTH: usize = 50;
```

### 9.10 Alopex SQL への適用ポイント

sqlparser-rs の調査から、Alopex SQL 実装に活かせるポイントを以下にまとめる。

#### 採用すべき設計パターン

| パターン | sqlparser-rs の実装 | Alopex SQL への適用 |
|----------|---------------------|---------------------|
| **Pratt Parser** | 式の優先順位処理に使用 | 同様に採用（式パーサー） |
| **Recursive Descent** | 文のパースに使用 | 同様に採用（文パーサー） |
| **Dialect trait** | 方言固有の動作を抽象化 | AlopexDialect を作成 |
| **Span/Spanned** | 位置情報の管理 | 同様に採用（エラーメッセージ改善） |
| **Visitor パターン** | AST 走査の抽象化 | 必要に応じて導入 |
| **RecursionCounter** | スタックオーバーフロー防止 | 同様に採用 |
| **derive マクロ** | Visit/VisitMut の自動生成 | 規模が大きくなったら検討 |

#### Alopex SQL 固有の拡張ポイント

```rust
// 1. ベクトル型の追加
pub enum DataType {
    // 標準型
    Integer, BigInt, Float, Double, Text, Blob, Boolean, Timestamp,
    // Alopex 拡張
    Vector { dim: usize, metric: Metric },
}

// 2. ベクトルリテラルの追加
pub enum ExprKind {
    // 標準式
    Literal(Literal),
    BinaryOp { left: Box<Expr>, op: BinaryOp, right: Box<Expr> },
    // Alopex 拡張
    VectorLiteral(Vec<f32>),
    VectorSearch {
        column: Box<Expr>,
        query_vector: Vec<f32>,
        limit: usize,
        metric: Metric,
    },
}

// 3. Alopex 方言の定義
pub struct AlopexDialect;

impl Dialect for AlopexDialect {
    fn parse_prefix(&self, parser: &mut Parser) -> Option<Result<Expr, ParserError>> {
        // [1.0, 2.0, 3.0] 形式のベクトルリテラルをパース
        if parser.peek_token().token == Token::LBracket {
            return Some(parser.parse_vector_literal());
        }
        None
    }

    // その他の Alopex 固有機能
}
```

#### 実装の優先順位

1. **Phase 1**: Tokenizer + 基本 AST（sqlparser-rs のパターンを参考に手書き）
2. **Phase 2**: Pratt Parser による式パーサー
3. **Phase 3**: Recursive Descent による文パーサー
4. **Phase 4**: Span/Spanned によるエラーメッセージ改善
5. **Phase 5**: ベクトル拡張（VectorLiteral, VectorSearch）
6. **Phase 6**: Visitor パターン（AST 走査が複雑化したら）

### 9.11 参考ソースパス

```
reference/datafusion-sqlparser-rs/
├── src/lib.rs                    # 公開 API（使い方の例）
├── src/tokenizer.rs              # Lexer 実装の参考
├── src/parser/mod.rs:1250-1280   # Pratt Parser のコア実装
├── src/parser/mod.rs:530-670     # 文パーサーのパターン
├── src/ast/mod.rs                # AST 構造の設計
├── src/ast/visitor.rs            # Visitor パターン
├── src/ast/spans.rs              # Spanned trait 実装
├── src/dialect/mod.rs:800-830    # Precedence 定義
├── src/dialect/mod.rs:1210-1235  # Precedence enum
└── derive/src/lib.rs             # Visit derive マクロ
```

---

## 10. Rust 以外の軽量言語によるパーサー実装調査

### 10.0 背景: Rust による SQL パーサー実装の限界

Alopex SQL パーサーは Rust で手書き実装されているが、**開発が事実上停滞している**。根本原因は Rust の型システムにある。

**Rust でのパーサー実装が困難な理由**:

1. **コンパイル時型解決の壁**: Rust はすべての型をコンパイル時に解決する。再帰的な AST 型は `Box<T>` で間接参照を強制され、ネストが深まるほど型定義が爆発的に複雑化する
2. **現在の alopex-sql の状況**: ExprKind 10 variants / StatementKind 8 variants / Token 24 variants / Keyword 69 variants（合計約 180 variants）の簡易 SQL で既にビルドが困難
3. **スケーラビリティの限界**: SQLite 相当の構文（JOIN, サブクエリ, Window 関数, CTE 等）ですら Rust での実装は極めて困難。PostgreSQL / MySQL 相当の完全な SQL 方言は、現時点の Rust ではコンパイル自体が現実的でない
4. **sqlparser-rs の実態**: デファクトである sqlparser-rs は parser/mod.rs だけで約 18,000 行に膨張しており、コンパイル時間・保守性の両面で限界に達しつつある

**具体的な技術的制約**:
- 再帰的 enum に対する `Box<T>` の必須化（12 箇所で使用中、今後加速的に増加）
- `#[allow(clippy::large_enum_variant)]` による lint 抑制の常態化
- 再帰深度制限（RecursionCounter、デフォルト 50）によるスタックオーバーフロー回避
- ライフタイム注釈の伝播（`Parser<'a>` → すべてのメソッドに `'a` が波及）
- match 式の網羅性チェックにより、variant 追加のたびに全 match を修正する必要

これらの制約は SQL のサブセットでは管理可能だが、**文法規模が線形に増加すると型の複雑度が指数的に増加する**。Rust は SQL パーサーのような大規模再帰型データ構造を扱う用途に構造的に不向きである。

この問題を解決するため、**Nim** と **Roc** を代替言語の候補として調査した。

### 10.1 対象言語の概要

| 項目 | **Zig** | **Nim** | **Roc** |
|---|---|---|---|
| パラダイム | 手続き型・システム言語 | マルチパラダイム（手続き+メタ） | 純粋関数型 |
| 型システム | 静的型付け、ジェネリクス | 静的型付け、ジェネリクス、ADT | Hindley-Milner 型推論、ADT |
| メタプログラミング | `comptime`（コンパイル時実行） | マクロ・テンプレート（AST 操作） | なし（シンプルさ優先） |
| コンパイル先 | LLVM → ネイティブ | C/C++/JS にトランスパイル | LLVM → ネイティブ |
| C 互換 | `@cImport` で直接呼出し | FFI で C/ObjC/JS と連携 | プラットフォーム抽象化 |
| GC | なし（手動アロケータ） | あり（選択可能、ARC 含む） | Perceus 参照カウント（将来） |
| 安定性 | **1.0 予定（2026）** | **2.x 安定版あり** | **pre-1.0 alpha** |
| ビルド速度 | 極めて高速 | 高速（C 経由） | 高速を目標（Zig でコンパイラ書き直し中） |
| WASM 対応 | ◎ | ○（JS バックエンド） | △（未成熟） |

### 10.2 言語の開発状況とマイルストーン（2026年6月時点）

#### Nim

**現在の安定版**: Nim 2.2.10（2026年4月24日リリース）

| リリース | 日付 | 備考 |
|---|---|---|
| Nim 2.2.0 | 2024-10-02 | 2.2 系初版。ORC がデフォルト GC |
| Nim 2.2.2 | 2025-02-05 | |
| Nim 2.2.4 | 2025-04-22 | |
| Nim 2.2.6 | 2025-10-31 | |
| Nim 2.2.8 | 2026-02-23 | |
| Nim 2.2.10 | 2026-04-24 | **最新安定版** |

**リリースサイクル**: 約 2〜3 ヶ月ごとにパッチリリース。安定した開発ペースを維持。

**Nim 3.0（Nimony）— 次世代コンパイラ**:

Nim 3.0 は「Nimony」と呼ばれるコンパイラの完全書き直しプロジェクトであり、2025年11月に v0.2 早期プレビューがリリースされた。

| 目標 | 内容 |
|---|---|
| インクリメンタル再コンパイル | 大規模コードベースでのコンパイル速度改善（主要動機） |
| メモリ消費 5 倍削減 | NIF フォーマット + トークンストリーム処理 |
| 前方宣言の廃止 | 型・関数の前方宣言が不要に |
| 型チェック付きジェネリクス | コンパイル時の型チェック強化 |
| 循環モジュール依存 | 明示的な循環依存サポート |

**バックエンド計画**: NIFC → C（ほぼ本番品質）、NIFC → LLVM（計画中、WASM 対応）、NIFC → ネイティブ（最も野心的）

**コミュニティ**: GitHub 18,066 stars。NimConf 2026 は 2026年6月20日にオンライン開催。

**Alopex との関連**:
- `std/parsesql` は Nim 2.0 で標準ライブラリから nimble パッケージに移動（`nimble install parsesql` が必要）
- `--gc:orc` は Nim 2.2 で `--mm:orc` に名称変更（非推奨警告）
- ORC メモリ管理は安定しており、組み込み環境でも使用可能
- 2.2 系は安定版として本番利用可能。3.0 への移行は互換性が保たれる見込み

#### Roc

**現在のバージョン**: alpha4-rolling（2025年8月26日リリース）

| リリース | 日付 | 備考 |
|---|---|---|
| alpha1 | 2025-01-29 | 初の alpha リリース |
| alpha2-rolling | 2025-01-29 | **大規模構文変更**（camelCase → snake_case、Task 廃止、`!` 構文） |
| alpha3-rolling | 2025-02-26 | |
| alpha4-rolling | 2025-08-26 | **最新版**。ビルド速度改善、新 builtins |

**公式見解**: 「Roc is not ready for a 0.1 release yet」— 1.0 のタイムラインは未発表。

**alpha2 での破壊的変更（2025年1月）**:

| 変更 | Before | After |
|---|---|---|
| 関数呼び出し | `func arg` | `func(arg)` |
| 命名規則 | `camelCase` | `snake_case` |
| エラーハンドリング | `Task` 型 | `!` サフィックス + `?` 演算子 |
| 文字列補間 | `$(expr)` | `${expr}` |
| 論理演算子 | `&&` / `||` | `and` / `or` |
| タグ構築 | `Ok val` | `Ok(val)` |

移行ツール `roc format --migrate` が提供されているが、`Task` → `!` の置換は手動対応が必要。

**Zig コンパイラ書き直し**:

Roc コンパイラの LLVM コード生成部分が Rust（約 18,000 行）から Zig（約 1,700 行）に書き直された。

| 項目 | 状態 |
|---|---|
| 規模 | 18,000 行 Rust → 1,700 行 Zig（10 倍の削減） |
| アーキテクチャ | Mono IR → Canonical IR（プレ単相化）に変更 |
| 未実装機能 | match 式、ラムダ、複雑な union、参照カウント、デバッグ情報 |
| 優先課題 | builtins 実装の完了（Issue #9596） |

**プラットフォームエコシステム**:

| パッケージ | バージョン | Stars | 備考 |
|---|---|---|---|
| basic-cli | v0.20.0 (2025-08) | 116 | ファイル、HTTP、TCP、CLI 引数 |
| basic-webserver | v0.13.1 (2026-01) | 105 | Rust (hyper + tokio) バックエンド |

**既知の制約**: Linux で `--linker=legacy` が必須（surgical linker の issue）。

**コミュニティ**: GitHub 5,700 stars、387 forks、43,653 commits。Zulip チャットが活発。コードベースの 92.9% が Zig。

**Alopex との関連**:
- alpha 段階のため API 変更が頻繁（試験実装時に 24 箇所の snake_case 移行が必要だった）
- basic-cli の URL ハッシュがバージョンごとに変わるため Dockerfile のメンテナンスコストが高い
- 言語設計は先進的（ADT、型推論、純粋関数型）だが、本番利用には時期尚早
- 1.0 リリースのブロッカー: Zig コンパイラの builtins 完了、ABI 安定化、ドキュメント整備

### 10.3 パーサー実装エコシステム

| | **Zig** | **Nim** | **Roc** |
|---|---|---|---|
| 主要ライブラリ | [cZPeg](https://github.com/spadix0/cZPeg), [parzig](https://github.com/DeSc1998/parzig), Mecha | [npeg](https://github.com/zevv/npeg) (PEG), nimly (lex/yacc) | [roc-parser](https://github.com/lukewilliamboswell/roc-parser) (コンビネータ) |
| アプローチ | comptime PEG / コンビネータ | マクロで PEG → Nim 関数に展開 | 関数型パーサーコンビネータ |
| コンパイル時生成 | ◎（comptime で再帰下降を生成） | ◎（マクロで PEG をコンパイル時展開） | ×（ランタイムのみ） |
| SQL パーサー実例 | [SQL-Parser (SQLite in Zig)](https://github.com/Enriquefft/SQL-Parser), [zigrocks-sql](https://notes.eatonphil.com/zigrocks-sql.html) | npeg で DSL 定義可能 | なし |

### 10.4 パーサー実装例

#### 10.4.1 Zig — comptime PEG パーサー（cZPeg）

[cZPeg](https://github.com/spadix0/cZPeg) は PEG 文法からコンパイル時に再帰下降パーサーを生成する。ランタイムオーバーヘッドがゼロ。

```zig
const peg = @import("czpeg");

// コンパイル時に PEG 文法から再帰下降パーサーを生成
const grammar = peg.Grammar(
    struct {
        // 四則演算の文法定義
        pub const expr = product.seq(.{
            peg.oneOf(.{ .lit("+"), .lit("-") }),
            product,
        }).repeat();
        pub const product = atom.seq(.{
            peg.oneOf(.{ .lit("*"), .lit("/") }),
            atom,
        }).repeat();
        pub const atom = peg.oneOf(.{
            number,
            .lit("(").seq(.{expr}).seq(.{.lit(")")}),
        });
        pub const number = peg.range('0', '9').repeat1();
    },
);

// comptime で生成されたパーサーをランタイムで使用
const result = grammar.parse("3+4*5");
```

**特徴**:
- 文法定義が struct のフィールドとして表現され、`comptime` で評価される
- 生成されるパーサーはネイティブコードに直接コンパイルされ、ランタイムオーバーヘッドなし
- C ABI 互換のため、Rust から FFI 経由で呼び出し可能

**SQL パーサー実例**: [Enriquefft/SQL-Parser](https://github.com/Enriquefft/SQL-Parser) が SQLite 互換パーサーを Zig で実装。[zigrocks-sql](https://notes.eatonphil.com/zigrocks-sql.html) は Zig + RocksDB で SQL データベースを構築した実例。

#### 10.4.2 Nim — npeg マクロ PEG パーサー

[npeg](https://github.com/zevv/npeg) はマクロで PEG 文法を Nim 関数にコンパイル時展開する。文法定義と Nim コードを自由に混在できる。

```nim
import npeg

# PEG 文法をマクロで定義 → コンパイル時に Nim 関数に展開
let parser = peg("input"):
  # SQL-like な SELECT 文の簡易パーサー
  input      <- select_stmt * !1
  select_stmt <- i"SELECT" * ws * columns * ws * i"FROM" * ws * >table_name
  columns    <- column * *(',' * ws * column)
  column     <- >+Alpha
  table_name <- +Alpha
  ws         <- +' '

# パース実行（Nim コード内でキャプチャを自由に操作可能）
let r = parser.match("SELECT name, age FROM users")
echo r.captures  # @["name", "age", "users"]
```

**特徴**:
- PEG 文法が Nim の DSL としてそのまま記述できる
- `>` プレフィックスでキャプチャ、`:` でコードブロック埋め込み
- コンパイル時にマクロ展開されるため実行時のパース文法解釈コストなし
- Python に近い構文で学習コストが低い

**参考**: Nim 自身のコンパイラパーサーも手書き実装 ([nim-lang/Nim/compiler/parser.nim](https://github.com/nim-lang/Nim/blob/devel/compiler/parser.nim))。EBNF に忠実な設計。

#### 10.4.3 Roc — 関数型パーサーコンビネータ

[roc-parser](https://github.com/lukewilliamboswell/roc-parser) は ADT + パターンマッチを活かした純関数型コンビネータ。

```roc
# ADT でトークンを定義
Token : [Select, From, Ident Str, Comma, Star]

# コンビネータでパーサーを組み立て
keyword : Str, Token -> Parser Utf8 Token
keyword = |text, tag|
    const(tag) |> skip(string(text))

token : Parser Utf8 Token
token = one_of([
    keyword("SELECT", Select),
    keyword("FROM", From),
    string("*") |> map(|_| Star),
    string(",") |> map(|_| Comma),
    many1(alpha) |> map(|chars| Ident(Str.from_utf8(chars))),
])

# パース結果は型安全な ADT
expect parse_str(many(token), "SELECT name FROM users")
    == Ok([Select, Ident("name"), From, Ident("users")])
```

**特徴**:
- すべてが不変値の関数合成。副作用なし
- ADT + パターンマッチで構文木の定義が自然
- HM 型推論により型注釈なしでも型安全
- pre-1.0 alpha 段階のため、API が未確定

### 10.5 言語パーサー実装の適性評価

| 観点 | **Nim** | **Roc** | **Zig** | **Rust（現行）** |
|---|---|---|---|---|
| AST 定義の表現力 | ○ object variant | ◎ ADT + パターンマッチ | △ struct/union で手動 | **△ enum + Box 必須、スケールしない** |
| 文法定義の簡潔さ | ◎ npeg マクロ (PEG 直書き) | ○ コンビネータ合成 | ○ comptime DSL | **× 手書きで冗長、variant 追加コスト大** |
| 文法規模のスケーラビリティ | ◎ PEG 文法は規模に依存しない | ◎ 関数合成で線形に拡張 | ○ | **× 型の複雑度が指数的に増加** |
| パフォーマンス | ○ C 出力で高速 | ○ LLVM 最適化 | ◎ ゼロオーバーヘッド | ◎ ゼロコスト抽象 |
| エラー処理 | ○ exceptions/Result | ◎ Result 型（例外なし） | ○ error union | ○ Result + ? |
| Rust FFI / 統合 | ○ C 経由で可能 | ○ Platform/Host モデルで C ABI export | ◎ C ABI 互換 | - (ネイティブ) |
| エコシステム成熟度 | ◎ 安定版あり | △ alpha、API 未確定 | ○ 1.0 間近 | ◎ 最も充実（ただしパーサーには不向き） |
| ビルド時間 | ◎ 高速 | ○ | ◎ 極めて高速 | **× 大規模 AST でコンパイル時間爆発** |
| 学習コスト | 低 | 中（関数型の素養要） | 中 | 高 |

> **注記**: Rust の評価は「言語全般」ではなく「大規模 SQL パーサー実装」に限定した評価である。Rust はストレージエンジン、ネットワーク層、並行処理など他の領域では引き続き最適解であり、Alopex プロジェクト全体の基盤言語としての位置づけは変わらない。パーサー層のみを別言語で実装し、C ABI / FFI で統合する戦略を検討する。

### 10.6 Alopex SQL パーサーへの適用可能性

現行の Rust 手書き実装を補完・代替する候補として **Nim** と **Roc** を評価する。

#### 候補 A: Nim — 文法 DSL ファーストのパーサー実装

```
Nim (npeg PEG 文法 → C コンパイル)
  ↓ C ライブラリとして出力 (.a / .so)
Rust Host (alopex-sql)
  ↓ extern "C" FFI で呼び出し
alopex-core / alopex-embedded
```

| 項目 | 評価 |
|---|---|
| **文法記述** | ◎ — npeg で PEG 文法を DSL として直書き。最も簡潔 |
| **Rust 連携** | ○ — C にトランスパイルされるため `extern "C"` FFI で統合可能 |
| **AST 表現** | ○ — object variant で ADT を表現可能 |
| **成熟度** | ◎ — Nim 2.x 安定版。npeg も十分な実績あり |
| **学習コスト** | 低 — Python 風構文。文法定義に集中できる |
| **リスク** | エコシステム規模が小さい。ビルドパイプラインに Nim ツールチェーンが必要 |

**適用場面**:
- SQL 文法のプロトタイピングと検証（PEG 文法を素早く試行錯誤）
- 文法定義を Nim で記述し、生成された C コードを Rust から利用するハイブリッド構成
- Alopex SQL 方言の文法仕様を npeg DSL として executable specification 化

#### 候補 B: Roc — 型安全な純関数パーサー + Rust Host

Roc は「Platform / Host」モデルにより、**Rust をホストとして Roc 関数を C ABI 経由で呼び出す**設計を持つ。[basic-webserver](https://github.com/roc-lang/basic-webserver) が Rust (hyper + tokio) → Roc の実例。

```
Roc Application (パーサーロジック: 純粋関数)
  ↓ C ABI 互換オブジェクトとして export (roc_app_main 等)
Rust Platform Host (alopex-sql)
  ↓ extern "C" リンク
alopex-core / alopex-embedded
```

| 項目 | 評価 |
|---|---|
| **AST 表現** | ◎ — ADT + パターンマッチが第一級。AST 定義が最も自然 |
| **型安全性** | ◎ — HM 型推論、例外なし、純粋関数。パーサーのテスタビリティが極めて高い |
| **Rust 連携** | ○ — Platform/Host モデルで C ABI export。Rust から `extern "C"` で呼び出し可能 |
| **パフォーマンス** | ○ — LLVM 最適化。Perceus 参照カウントで GC なし |
| **成熟度** | △ — pre-1.0 alpha。ABI 未安定。コンパイラを Zig で書き直し中 |
| **学習コスト** | 中 — 関数型プログラミングの素養が必要 |
| **リスク** | alpha 段階で API 変更の可能性大。Roc コンパイラ自体の安定性 |

**適用場面**:
- パーサーロジックを純粋関数として Roc で記述し、Rust Host から呼び出すクリーンな分離
- AST 定義・パターンマッチ・型推論を活かした型駆動パーサー開発
- 将来的な Roc 1.0 安定版リリース後の本格採用を見据えた先行評価

#### 候補比較

| 観点 | **Nim** | **Roc** |
|---|---|---|
| 即座に使えるか | ◎ 安定版あり | △ alpha 段階 |
| 文法記述の簡潔さ | ◎ PEG 直書き | ○ コンビネータ合成 |
| 型安全性 | ○ | ◎ HM 型推論 + ADT |
| テスタビリティ | ○ | ◎ 純粋関数（副作用なし） |
| Rust 統合の容易さ | ○ C 出力 → FFI | ○ C ABI export → FFI |
| 将来性 | ○ 安定だが成長は緩やか | ◎ 設計思想が先進的、成長が早い |

#### 推奨ロードマップ

Rust での SQL パーサー開発は停滞しており、**言語移行は「検討事項」ではなく「必要条件」**である。

| フェーズ | アクション | 言語 | 目標 |
|---|---|---|---|
| **Phase 1: 文法仕様化** | Nim npeg で Alopex SQL 方言の完全な PEG 文法を記述。executable specification として動作検証 | Nim | 文法の正確性を言語非依存に確立 |
| **Phase 2: PoC 実装** | Nim パーサーを C ライブラリとして出力し、Rust (alopex-sql) から FFI 呼び出しする PoC を構築 | Nim + Rust | Nim → Rust 統合パスの検証 |
| **Phase 2b: Roc 評価** | Roc で式パーサーを PoC 実装し、Rust Host からの C ABI 呼び出しを検証。Nim との比較材料とする | Roc + Rust | Roc の実用性評価 |
| **Phase 3: 本格移行** | Phase 2 の結果に基づき Nim または Roc でパーサー全体を再実装。Rust 側は FFI ブリッジ + Planner/Executor に専念 | Nim or Roc | SQLite 相当以上の SQL 文法サポート |
| **Phase 4: 拡張** | JOIN, サブクエリ, Window 関数, CTE など高度な SQL 構文を追加。Rust では不可能だった文法拡張を実現 | Nim or Roc | PostgreSQL 互換を視野に入れた拡張 |

#### アーキテクチャ目標

```
┌──────────────────────────────────────┐
│  SQL Parser (Nim or Roc)             │  ← 文法定義・字句解析・構文解析
│  出力: AST (C ABI 互換構造体)         │
└────────────┬─────────────────────────┘
             │ extern "C" FFI
             ▼
┌──────────────────────────────────────┐
│  alopex-sql (Rust)                   │  ← Planner / Executor / Catalog
│  AST を受け取り LogicalPlan に変換    │
│  ストレージ層 (alopex-core) と統合    │
└──────────────────────────────────────┘
```

この分離により、**パーサー層は文法の複雑度に対してスケール可能**になり、**Rust 層はストレージ・実行エンジンの強みを活かす**構成となる。

### 10.7 参考資料

#### ライブラリ・ツール

- [cZPeg - Compile-Time PEG for Zig](https://github.com/spadix0/cZPeg)
- [parzig - Compile time parser generator for Zig](https://github.com/DeSc1998/parzig)
- [npeg - PEGs for Nim](https://github.com/zevv/npeg)
- [nimly - Lexer/Parser generator for Nim](https://nimble.directory/pkg/nimly)
- [roc-parser - Parser Combinator for Roc](https://github.com/lukewilliamboswell/roc-parser)

#### 記事・ブログ

- [Zig, Parser Combinators, and Why They're Awesome (Hexops)](https://devlog.hexops.org/2021/zig-parser-combinators-and-why-theyre-awesome/)
- [Zig Parser - Mitchell Hashimoto](https://mitchellh.com/zig/parser)
- [Writing a SQL database in Zig and RocksDB (Phil Eaton)](https://notes.eatonphil.com/zigrocks-sql.html)
- [Parsing inputs in Nim (Miran)](https://narimiran.github.io/2021/01/11/nim-parsing.html)
- [Nim Metaprogramming - Macro Tutorial](https://dlesnoff.github.io/nimProgramming-blog/blogPosts/macroTutorial.html)
- [Roc Parser Example](https://www.roc-lang.org/examples/Parser/README)
- [Roc Pattern Matching](https://www.roc-lang.org/examples/PatternMatching/README)

#### Roc / Rust 連携

- [Roc Platforms and Apps](https://www.roc-lang.org/platforms) — Platform/Host モデルの公式解説
- [basic-webserver (Rust Host 実例)](https://github.com/roc-lang/basic-webserver) — Rust (hyper + tokio) から Roc 関数を呼び出す実装
- [Roc with Richard Feldman - Rust in Production Podcast](https://corrode.dev/podcast/s05e04-roc/) — Roc と Rust の関係性についてのインタビュー
- [Why Roc Is Moving Away From Rust to Zig](https://medium.com/rustaceans/why-roc-is-moving-away-from-rust-to-zig-8b2259ff1c13) — コンパイラ実装言語の移行理由（Host は引き続き Rust 可）
- [Roc FAQ](https://www.roc-lang.org/faq) — FFI ポリシー、Platform による FFI 制御の設計思想

#### 言語比較

- [Zig vs Nim Benchmarks](https://programming-language-benchmarks.vercel.app/zig-vs-nim)
- [Slant - Nim vs Zig (2025)](https://www.slant.co/versus/395/35558/~nim_vs_zig)
- [Roc Language - Fast](https://www.roc-lang.org/fast)
