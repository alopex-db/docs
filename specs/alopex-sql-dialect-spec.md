# Alopex SQL 方言仕様書

**バージョン**: 0.7.4-draft
**最終更新**: 2026-07-17
**ステータス**: v0.7.4 実装反映・公開前

---

## 1. 設計方針

### 1.1 準拠ベースと根拠

Alopex SQL は **SQLite をベースとし、PostgreSQL の一部構文を参考に**した独自方言である。

| 選択肢 | 採用 | 根拠 |
|--------|------|------|
| **SQLite** | ✅ 主要ベース | 埋め込み DB との親和性、シンプルな型システム、軽量実装 |
| **PostgreSQL** | 部分参考 | 型キャストの `::` 構文、VECTOR 型の拡張パターン |
| **独自拡張** | ✅ | ベクトル型・距離関数・HNSW インデックス |

**理由**:
- Alopex は埋め込み（embedded）DB であり、SQLite の「ゼロ設定・単一ファイル」哲学と合致
- PostgreSQL 完全互換は実装コストが高く、Alopex のユースケースに過剰
- ベクトル検索機能は既存 SQL 標準にないため、独自拡張が必須

### 1.2 サポートしない機能（v0.3 スコープ外）

以下の機能は v0.3 では**意図的にサポートしない**。将来バージョンで追加を検討する。

| 機能 | 理由 | 将来検討 |
|------|------|----------|
| **JOIN** | 複雑なプランナー/オプティマイザが必要 | v0.6+ |
| **サブクエリ** | AST/プランナーの複雑化、Box 再帰が必要 | v0.8+ |
| **CTE (WITH句)** | サブクエリ依存 | v0.9+ |
| **GROUP BY / HAVING** | 集約プランナーが必要 | v0.5 |
| **UNION / INTERSECT** | 複数結果セットのマージ | v0.6+ |
| **ウィンドウ関数** | 高度な集約処理 | v0.9+ |
| **トリガー / ビュー** | DDL 拡張 | v0.10+ |
| **外部キー制約** | 参照整合性チェック | v0.5 |
| **トランザクション分離レベル指定** | 現状は Snapshot Isolation 固定 | v0.6+ |
| **TS 拡張** (MATCH, TIME_BUCKET, RATE) | skulk 型を `alopex-query-common` 経由で使用 | v0.5.x |

### 1.3 Vector 拡張構文の設計根拠

既存の拡張との比較:

| 実装 | 構文例 | 評価 |
|------|--------|------|
| **pgvector** | `vec <-> query` (演算子) | PostgreSQL 固有、汎用性低 |
| **Pinecone SQL** | `VECTOR_SEARCH(...)` 関数 | 明示的だが冗長 |
| **Alopex (採用)** | `vector_distance(col, vec, 'metric')` | 関数形式、可読性・拡張性重視 |

**採用理由**:
- 関数形式は SQL 標準に近く、学習コストが低い
- メトリクスを文字列引数で指定し、将来の追加が容易
- WHERE 句・ORDER BY 句で自然に使用可能

---

## 2. パーサー実装アーキテクチャ

> 詳細な技術調査は `design/sql-engine-research.md` セクション9を参照

### 2.1 実装方針（sqlparser-rs パターンの採用）

sqlparser-rs の調査結果に基づき、以下の実装方式を採用する：

| コンポーネント | 採用パターン | 根拠 |
|----------------|--------------|------|
| **字句解析** | 手書き Tokenizer | 制御の容易さ、位置情報の正確な追跡 |
| **式パーサー** | Pratt Parser | 優先順位処理の柔軟性、拡張性 |
| **文パーサー** | Recursive Descent | キーワード駆動で直感的、保守性が高い |
| **方言対応** | Dialect trait | 将来の拡張ポイント（Alopex 固有構文） |
| **AST 走査** | Visitor パターン（将来） | 規模が大きくなってから導入 |

### 2.2 モジュール構成

```
alopex-sql/
├── src/
│   ├── lib.rs              # 公開 API
│   ├── tokenizer.rs        # 字句解析器
│   ├── keywords.rs         # SQL キーワード定義
│   ├── parser/
│   │   ├── mod.rs          # Parser 構造体・文パーサー
│   │   └── expr.rs         # Pratt Parser（式パーサー）
│   ├── ast/
│   │   ├── mod.rs          # AST 型定義
│   │   ├── expr.rs         # 式 AST
│   │   ├── stmt.rs         # 文 AST
│   │   └── span.rs         # 位置情報
│   ├── dialect.rs          # Alopex 方言定義
│   └── error.rs            # エラー型
```

### 2.3 Tokenizer 設計

#### Token 定義

```rust
/// Alopex SQL Token
#[derive(Debug, Clone, PartialEq)]
pub enum Token {
    EOF,

    // キーワードまたは識別子
    Word(Word),

    // リテラル
    Number(String),              // 数値（整数・浮動小数点）
    SingleQuotedString(String),  // 'string'

    // 演算子・区切り文字
    Comma,          // ,
    Eq,             // =
    Neq,            // <> または !=
    Lt,             // <
    Gt,             // >
    LtEq,           // <=
    GtEq,           // >=
    Plus,           // +
    Minus,          // -
    Mul,            // *
    Div,            // /
    Mod,            // %
    LParen,         // (
    RParen,         // )
    LBracket,       // [
    RBracket,       // ]
    Period,         // .
    Colon,          // :
    SemiColon,      // ;
    StringConcat,   // ||
}

/// キーワードまたは識別子
#[derive(Debug, Clone, PartialEq)]
pub struct Word {
    pub value: String,
    pub quote_style: Option<char>,  // None, '"', '`'
    pub keyword: Keyword,           // キーワードならマッチ、それ以外は NoKeyword
}

/// 位置情報付きトークン
#[derive(Debug, Clone)]
pub struct TokenWithSpan {
    pub token: Token,
    pub span: Span,
}
```

#### 位置情報（Span）の設計

sqlparser-rs パターンを採用：

```rust
/// ソース内の位置（1-indexed）
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct Location {
    pub line: u64,    // 1-based（0 は空/不明を表す）
    pub column: u64,  // 1-based
}

impl Location {
    /// 空の位置（不明）
    pub const fn empty() -> Self {
        Self { line: 0, column: 0 }
    }

    /// 新しい位置を作成
    pub const fn new(line: u64, column: u64) -> Self {
        Self { line, column }
    }
}

/// 範囲（開始〜終了）
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Span {
    pub start: Location,
    pub end: Location,
}

impl Span {
    /// 空の Span（位置不明）
    pub const fn empty() -> Self {
        Self {
            start: Location::empty(),
            end: Location::empty(),
        }
    }

    /// 2つの Span の和集合
    pub fn union(&self, other: &Span) -> Span {
        if self.start.line == 0 { return *other; }
        if other.start.line == 0 { return *self; }
        Span {
            start: std::cmp::min(self.start, other.start),
            end: std::cmp::max(self.end, other.end),
        }
    }
}
```

**エラーメッセージ例**:
```
error: unknown column 'foo'
  --> query.sql:3:15
   |
 3 | SELECT foo FROM users
   |        ^^^ column not found in table 'users'
```

### 2.4 Parser 構造体

```rust
pub struct Parser<'a> {
    /// トークン列
    tokens: Vec<TokenWithSpan>,
    /// 現在位置
    index: usize,
    /// SQL 方言
    dialect: &'a dyn Dialect,
    /// 再帰深度カウンター
    recursion_counter: RecursionCounter,
}

impl<'a> Parser<'a> {
    /// SQL 文字列からパース
    pub fn parse_sql(dialect: &'a dyn Dialect, sql: &str) -> Result<Vec<Statement>, ParserError> {
        let tokens = Tokenizer::new(dialect, sql).tokenize()?;
        let mut parser = Parser::new(dialect, tokens);
        parser.parse_statements()
    }

    /// 次のトークンを取得（位置を進める）
    fn next_token(&mut self) -> TokenWithSpan { ... }

    /// 次のトークンを覗き見（位置を進めない）
    fn peek_token(&self) -> &TokenWithSpan { ... }

    /// 1つ前に戻る
    fn prev_token(&mut self) { ... }

    /// 期待するトークンでなかった場合のエラー
    fn expected<T>(&self, expected: &str, found: &TokenWithSpan) -> Result<T, ParserError> { ... }
}
```

### 2.5 Pratt Parser（式パーサー）

#### 優先順位の定義

```rust
/// 演算子の優先順位（数値が大きいほど優先度が高い）
#[derive(Debug, Clone, Copy)]
pub enum Precedence {
    Period,       // 100: . (メンバアクセス)
    MulDivMod,    // 40:  *, /, %
    PlusMinus,    // 30:  +, -
    StringConcat, // 25:  ||
    Comparison,   // 20:  =, <>, <, >, <=, >=
    Between,      // 20:  BETWEEN
    Like,         // 19:  LIKE
    Is,           // 17:  IS NULL, IS NOT NULL
    UnaryNot,     // 15:  NOT
    And,          // 10:  AND
    Or,           // 5:   OR
}

impl Precedence {
    pub fn value(&self) -> u8 {
        match self {
            Self::Period => 100,
            Self::MulDivMod => 40,
            Self::PlusMinus => 30,
            Self::StringConcat => 25,
            Self::Comparison => 20,
            Self::Between => 20,
            Self::Like => 19,
            Self::Is => 17,
            Self::UnaryNot => 15,
            Self::And => 10,
            Self::Or => 5,
        }
    }
}

const PREC_UNKNOWN: u8 = 0;
```

#### Pratt Parser のコアアルゴリズム

```rust
impl Parser<'_> {
    /// 式をパース（エントリポイント）
    pub fn parse_expr(&mut self) -> Result<Expr, ParserError> {
        self.parse_subexpr(PREC_UNKNOWN)
    }

    /// 優先順位が変わるまでトークンをパース
    fn parse_subexpr(&mut self, precedence: u8) -> Result<Expr, ParserError> {
        let _guard = self.recursion_counter.try_decrease()?;

        // 1. prefix（前置式）をパース
        let mut expr = self.parse_prefix()?;

        // 2. infix（中置式）をループで処理
        loop {
            let next_prec = self.get_next_precedence()?;

            // 現在の優先順位以下なら終了
            if precedence >= next_prec {
                break;
            }

            // infix をパース
            expr = self.parse_infix(expr, next_prec)?;
        }

        Ok(expr)
    }

    /// 前置式のパース
    fn parse_prefix(&mut self) -> Result<Expr, ParserError> {
        let token = self.next_token();
        match &token.token {
            // リテラル
            Token::Number(n) => Ok(Expr::new(ExprKind::Literal(Literal::Number(n.clone())), token.span)),
            Token::SingleQuotedString(s) => Ok(Expr::new(ExprKind::Literal(Literal::String(s.clone())), token.span)),

            // キーワード
            Token::Word(w) => match w.keyword {
                Keyword::TRUE => Ok(Expr::new(ExprKind::Literal(Literal::Boolean(true)), token.span)),
                Keyword::FALSE => Ok(Expr::new(ExprKind::Literal(Literal::Boolean(false)), token.span)),
                Keyword::NULL => Ok(Expr::new(ExprKind::Literal(Literal::Null), token.span)),
                Keyword::NOT => {
                    let expr = self.parse_subexpr(Precedence::UnaryNot.value())?;
                    Ok(Expr::new(ExprKind::UnaryOp { op: UnaryOp::Not, operand: Box::new(expr) }, token.span))
                }
                Keyword::NoKeyword => {
                    // 識別子（カラム名）または関数呼び出し
                    self.parse_identifier_or_function(&w.value, token.span)
                }
                _ => self.expected("expression", &token),
            }

            // 単項マイナス
            Token::Minus => {
                let expr = self.parse_subexpr(Precedence::PlusMinus.value())?;
                Ok(Expr::new(ExprKind::UnaryOp { op: UnaryOp::Minus, operand: Box::new(expr) }, token.span))
            }

            // 括弧
            Token::LParen => {
                let expr = self.parse_expr()?;
                self.expect_token(Token::RParen)?;
                Ok(expr)
            }

            // ベクトルリテラル [1.0, 2.0, 3.0]
            Token::LBracket => self.parse_vector_literal(token.span),

            _ => self.expected("expression", &token),
        }
    }

    /// 中置式のパース
    fn parse_infix(&mut self, left: Expr, precedence: u8) -> Result<Expr, ParserError> {
        let token = self.next_token();
        let span_start = left.span.start;

        match &token.token {
            // 二項算術演算子
            Token::Plus | Token::Minus | Token::Mul | Token::Div | Token::Mod => {
                let op = match &token.token {
                    Token::Plus => BinaryOp::Add,
                    Token::Minus => BinaryOp::Sub,
                    Token::Mul => BinaryOp::Mul,
                    Token::Div => BinaryOp::Div,
                    Token::Mod => BinaryOp::Mod,
                    _ => unreachable!(),
                };
                let right = self.parse_subexpr(precedence)?;
                let span = Span { start: span_start, end: right.span.end };
                Ok(Expr::new(ExprKind::BinaryOp { left: Box::new(left), op, right: Box::new(right) }, span))
            }

            // 比較演算子
            Token::Eq | Token::Neq | Token::Lt | Token::Gt | Token::LtEq | Token::GtEq => {
                let op = match &token.token {
                    Token::Eq => BinaryOp::Eq,
                    Token::Neq => BinaryOp::Neq,
                    Token::Lt => BinaryOp::Lt,
                    Token::Gt => BinaryOp::Gt,
                    Token::LtEq => BinaryOp::LtEq,
                    Token::GtEq => BinaryOp::GtEq,
                    _ => unreachable!(),
                };
                let right = self.parse_subexpr(precedence)?;
                let span = Span { start: span_start, end: right.span.end };
                Ok(Expr::new(ExprKind::BinaryOp { left: Box::new(left), op, right: Box::new(right) }, span))
            }

            // 論理演算子（キーワード）
            Token::Word(w) => match w.keyword {
                Keyword::AND => {
                    let right = self.parse_subexpr(precedence)?;
                    let span = Span { start: span_start, end: right.span.end };
                    Ok(Expr::new(ExprKind::BinaryOp { left: Box::new(left), op: BinaryOp::And, right: Box::new(right) }, span))
                }
                Keyword::OR => {
                    let right = self.parse_subexpr(precedence)?;
                    let span = Span { start: span_start, end: right.span.end };
                    Ok(Expr::new(ExprKind::BinaryOp { left: Box::new(left), op: BinaryOp::Or, right: Box::new(right) }, span))
                }
                Keyword::LIKE => self.parse_like(left, false),
                Keyword::BETWEEN => self.parse_between(left, false),
                Keyword::IN => self.parse_in(left, false),
                Keyword::IS => self.parse_is(left),
                _ => self.expected("operator", &token),
            }

            _ => self.expected("operator", &token),
        }
    }

    /// 次のトークンの優先順位を取得
    fn get_next_precedence(&self) -> Result<u8, ParserError> {
        let token = self.peek_token();
        Ok(match &token.token {
            Token::Mul | Token::Div | Token::Mod => Precedence::MulDivMod.value(),
            Token::Plus | Token::Minus => Precedence::PlusMinus.value(),
            Token::StringConcat => Precedence::StringConcat.value(),
            Token::Eq | Token::Neq | Token::Lt | Token::Gt | Token::LtEq | Token::GtEq => Precedence::Comparison.value(),
            Token::Word(w) => match w.keyword {
                Keyword::AND => Precedence::And.value(),
                Keyword::OR => Precedence::Or.value(),
                Keyword::LIKE | Keyword::NOT => Precedence::Like.value(),
                Keyword::BETWEEN => Precedence::Between.value(),
                Keyword::IN => Precedence::Comparison.value(),
                Keyword::IS => Precedence::Is.value(),
                _ => PREC_UNKNOWN,
            }
            _ => PREC_UNKNOWN,
        })
    }
}
```

### 2.6 Dialect（方言）システム

```rust
/// SQL 方言 trait
pub trait Dialect: std::fmt::Debug + std::any::Any {
    /// 識別子の開始文字判定
    fn is_identifier_start(&self, ch: char) -> bool;

    /// 識別子の構成文字判定
    fn is_identifier_part(&self, ch: char) -> bool;

    /// カスタム文パーサー（デフォルトでは None）
    fn parse_statement(&self, _parser: &mut Parser) -> Option<Result<Statement, ParserError>> {
        None
    }

    /// カスタム前置式パーサー（デフォルトでは None）
    fn parse_prefix(&self, _parser: &mut Parser) -> Option<Result<Expr, ParserError>> {
        None
    }

    /// 優先順位の数値変換
    fn prec_value(&self, prec: Precedence) -> u8 {
        prec.value()
    }
}

/// Alopex SQL 方言
#[derive(Debug)]
pub struct AlopexDialect;

impl Dialect for AlopexDialect {
    fn is_identifier_start(&self, ch: char) -> bool {
        ch.is_alphabetic() || ch == '_'
    }

    fn is_identifier_part(&self, ch: char) -> bool {
        ch.is_alphanumeric() || ch == '_'
    }

    fn parse_prefix(&self, parser: &mut Parser) -> Option<Result<Expr, ParserError>> {
        // ベクトルリテラル [1.0, 2.0, 3.0] のパースを追加
        if parser.peek_token().token == Token::LBracket {
            return Some(parser.parse_vector_literal_from_bracket());
        }
        None
    }
}
```

### 2.7 再帰深度制限

```rust
/// スタックオーバーフロー防止のための再帰カウンター
pub struct RecursionCounter {
    remaining_depth: std::cell::Cell<usize>,
}

impl RecursionCounter {
    pub fn new(max_depth: usize) -> Self {
        Self {
            remaining_depth: std::cell::Cell::new(max_depth),
        }
    }

    /// 深度を1減らす（0になったらエラー）
    pub fn try_decrease(&self) -> Result<DepthGuard<'_>, ParserError> {
        let old_value = self.remaining_depth.get();
        if old_value == 0 {
            Err(ParserError::RecursionLimitExceeded)
        } else {
            self.remaining_depth.set(old_value - 1);
            Ok(DepthGuard { counter: self })
        }
    }
}

/// Drop 時に深度を復元する RAII ガード
pub struct DepthGuard<'a> {
    counter: &'a RecursionCounter,
}

impl Drop for DepthGuard<'_> {
    fn drop(&mut self) {
        let old_value = self.counter.remaining_depth.get();
        self.counter.remaining_depth.set(old_value + 1);
    }
}

/// デフォルト再帰深度
const DEFAULT_RECURSION_LIMIT: usize = 50;
```

---

## 3. AST 設計方針

### 3.1 再帰型への Box 適用ポリシー

Rust ではコンパイル時に型サイズを決定するため、**再帰的構造には `Box` が必須**。

**ポリシー**: 以下のケースでは必ず `Box<T>` を使用する:

| 構造 | 再帰パターン | 解決策 |
|------|--------------|--------|
| 二項演算 | `Expr → BinaryOp → Expr` | `Box<Expr>` |
| 単項演算 | `Expr → UnaryOp → Expr` | `Box<Expr>` |
| CASE WHEN | `Expr → CaseExpr → Expr` | `Box<Expr>` |
| サブクエリ（将来）| `Expr → Subquery → SelectStmt` | `Box<SelectStmt>` |
| ネストSELECT（将来）| `TableRef → SelectStmt` | `Box<SelectStmt>` |

**v0.3 での適用**:
```rust
pub enum ExprKind {
    BinaryOp {
        left: Box<Expr>,
        op: BinaryOp,
        right: Box<Expr>,
    },
    UnaryOp {
        op: UnaryOp,
        operand: Box<Expr>,
    },
    // 将来拡張用（v0.3 ではコメントアウト）
    // Subquery(Box<SelectStmt>),
}
```

### 3.2 Spanned trait パターン

sqlparser-rs の Spanned パターンを採用：

```rust
/// AST ノードの位置情報を取得する trait
pub trait Spanned {
    fn span(&self) -> Span;
}

/// 式 AST
#[derive(Debug, Clone)]
pub struct Expr {
    pub kind: ExprKind,
    pub span: Span,
}

impl Expr {
    pub fn new(kind: ExprKind, span: Span) -> Self {
        Self { kind, span }
    }
}

impl Spanned for Expr {
    fn span(&self) -> Span {
        self.span
    }
}

/// 文 AST
#[derive(Debug, Clone)]
pub struct Statement {
    pub kind: StatementKind,
    pub span: Span,
}

impl Spanned for Statement {
    fn span(&self) -> Span {
        self.span
    }
}
```

### 3.3 走査パターン選択と根拠

**v0.3 方針**: `match` + enum で開始し、必要に応じて Visitor/Fold を導入

| フェーズ | パターン | 用途 |
|----------|----------|------|
| v0.3.1-4 | `match` + enum | パース、単純な変換 |
| v0.3.5+ | `match` + 一部 Visitor | 型チェック、名前解決 |
| v0.4+ | Visitor/Fold trait | AST 最適化、複雑な変換 |

**将来の Visitor パターン（参考）**:
```rust
pub trait Visitor {
    type Break;

    fn pre_visit_expr(&mut self, _expr: &Expr) -> std::ops::ControlFlow<Self::Break> {
        std::ops::ControlFlow::Continue(())
    }

    fn post_visit_expr(&mut self, _expr: &Expr) -> std::ops::ControlFlow<Self::Break> {
        std::ops::ControlFlow::Continue(())
    }

    fn pre_visit_statement(&mut self, _stmt: &Statement) -> std::ops::ControlFlow<Self::Break> {
        std::ops::ControlFlow::Continue(())
    }

    fn post_visit_statement(&mut self, _stmt: &Statement) -> std::ops::ControlFlow<Self::Break> {
        std::ops::ControlFlow::Continue(())
    }
}
```

### 3.4 将来の拡張性

サブクエリ・JOIN 追加時の影響範囲を最小化するための設計:

| 将来機能 | 影響を受ける箇所 | 緩和策 |
|----------|------------------|--------|
| サブクエリ | `ExprKind`, `TableRef`, Planner | `Box<SelectStmt>` を予約 |
| JOIN | `FromClause`, Planner, Executor | `TableRef` を enum 化 |
| CTE | `Statement`, Planner | `WithClause` フィールド追加 |

**現在の設計での緩和策**:
```rust
// TableRef は将来の JOIN 対応を見越して enum 化
pub enum TableRef {
    /// 単一テーブル参照
    Table { name: String, alias: Option<String> },
    // 将来拡張
    // Join { left: Box<TableRef>, right: Box<TableRef>, ... },
    // Subquery(Box<SelectStmt>),
}
```

---

## 4. データ型仕様

### 4.1 スカラ型

| 型名 | Rust 対応 | サイズ | 説明 |
|------|-----------|--------|------|
| `INTEGER` | `i32` | 4 bytes | 32-bit 符号付き整数 |
| `BIGINT` | `i64` | 8 bytes | 64-bit 符号付き整数 |
| `FLOAT` | `f32` | 4 bytes | 32-bit IEEE 754 浮動小数点 |
| `DOUBLE` | `f64` | 8 bytes | 64-bit IEEE 754 浮動小数点 |
| `TEXT` | `String` | 可変 | UTF-8 文字列 |
| `BLOB` | `Vec<u8>` | 可変 | バイナリデータ |
| `BOOLEAN` | `bool` | 1 byte | `TRUE` / `FALSE` |

### 4.2 特殊型

#### VECTOR 型

```sql
-- 構文
column_name VECTOR(dimension [, metric])

-- 例
embedding VECTOR(128)           -- デフォルト: COSINE
embedding VECTOR(384, L2)       -- L2 距離
embedding VECTOR(768, INNER)    -- 内積
```

| パラメータ | 必須 | デフォルト | 説明 |
|------------|------|------------|------|
| `dimension` | ✅ | - | ベクトルの次元数（1-65535） |
| `metric` | ❌ | `COSINE` | 距離メトリクス |

**メトリクス一覧**:

| メトリクス | 説明 | 値域 | 最適化方向 |
|------------|------|------|------------|
| `COSINE` | コサイン類似度 | [-1, 1] | 大きいほど類似 |
| `L2` | ユークリッド距離 | [0, ∞) | 小さいほど類似 |
| `INNER` | 内積 | (-∞, ∞) | 大きいほど類似 |

#### TIMESTAMP 型

```sql
created_at TIMESTAMP
```

- 内部表現: Unix エポックからのマイクロ秒（`i64`）
- タイムゾーン: UTC 固定（v0.3 では TZ 非対応）
- リテラル: `'2025-01-15 10:30:00'` 形式

### 4.3 型変換規則

#### 暗黙的変換（自動）

| From | To | 条件 |
|------|----|------|
| `INTEGER` | `BIGINT` | 常に安全 |
| `INTEGER` | `FLOAT` | 精度損失の可能性あり |
| `INTEGER` | `DOUBLE` | 常に安全 |
| `FLOAT` | `DOUBLE` | 常に安全 |
| `BIGINT` | `DOUBLE` | 精度損失の可能性あり |

#### 明示的変換（CAST）

```sql
CAST(expr AS type)

-- 例
CAST('123' AS INTEGER)
CAST(1.5 AS INTEGER)      -- 切り捨て: 1
CAST(embedding AS BLOB)   -- ベクトル → バイナリ
```

### 4.4 NULL 処理セマンティクス

- **3値論理**: `TRUE`, `FALSE`, `NULL` (unknown)
- **NULL の伝搬**: `NULL` を含む演算結果は `NULL`
- **比較**: `NULL = NULL` は `NULL`（`FALSE` ではない）
- **IS NULL / IS NOT NULL**: NULL 判定専用

| 式 | 結果 |
|----|------|
| `1 + NULL` | `NULL` |
| `NULL = NULL` | `NULL` |
| `NULL IS NULL` | `TRUE` |
| `NULL AND TRUE` | `NULL` |
| `NULL OR TRUE` | `TRUE` |

---

## 5. DDL 構文仕様

### 5.1 CREATE TABLE

```sql
CREATE TABLE [IF NOT EXISTS] table_name (
    column_def [, column_def ...]
    [, table_constraint ...]
);

column_def:
    column_name data_type [column_constraint ...]

column_constraint:
    NOT NULL
  | NULL
  | PRIMARY KEY
  | DEFAULT literal
  | UNIQUE

table_constraint:
    PRIMARY KEY (column_name [, column_name ...])
```

**例**:
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE documents (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    embedding VECTOR(384, COSINE)
);
```

**制約**:
- PRIMARY KEY は 1 テーブルにつき 1 つまで
- VECTOR 型カラムに PRIMARY KEY は不可
- DEFAULT は定数リテラルまたは `NOW()` のみ

### 5.2 DROP TABLE

```sql
DROP TABLE [IF EXISTS] table_name;
```

**例**:
```sql
DROP TABLE users;
DROP TABLE IF EXISTS temp_data;
```

### 5.3 CREATE INDEX

```sql
CREATE INDEX [IF NOT EXISTS] index_name
    ON table_name (column_name)
    [USING method]
    [WITH (option = value [, ...])];

method:
    BTREE     -- スカラ型用（デフォルト）
  | HNSW      -- VECTOR 型用
```

**HNSW オプション**:

| オプション | 型 | デフォルト | 説明 |
|------------|-----|------------|------|
| `m` | INTEGER | 16 | ノードあたりの最大接続数 |
| `ef_construction` | INTEGER | 200 | 構築時の探索幅 |

**例**:
```sql
-- 通常のインデックス
CREATE INDEX idx_user_email ON users (email);

-- HNSW インデックス
CREATE INDEX idx_doc_embedding ON documents (embedding)
    USING HNSW
    WITH (m = 16, ef_construction = 200);
```

### 5.4 DROP INDEX

```sql
DROP INDEX [IF EXISTS] index_name;
```

### 5.5 将来拡張: ALTER TABLE

v0.4+ で以下を検討:
```sql
ALTER TABLE table_name
    ADD COLUMN column_def
  | DROP COLUMN column_name
  | RENAME COLUMN old_name TO new_name
  | RENAME TO new_table_name;
```

---

## 6. DML 構文仕様

### 6.1 SELECT

```sql
SELECT [DISTINCT] select_list
    FROM table_ref
    [WHERE condition]
    [ORDER BY order_list]
    [LIMIT count [OFFSET start]];

select_list:
    *
  | expr [[AS] alias] [, ...]

order_list:
    expr [ASC | DESC] [NULLS FIRST | NULLS LAST] [, ...]
```

**例**:
```sql
-- 基本
SELECT * FROM users;

-- 射影とエイリアス
SELECT id, name AS user_name FROM users;

-- WHERE + ORDER BY + LIMIT
SELECT * FROM documents
    WHERE title LIKE '%AI%'
    ORDER BY created_at DESC
    LIMIT 10 OFFSET 20;
```

### 6.2 INSERT

```sql
INSERT INTO table_name [(column_list)]
    VALUES (value_list) [, (value_list) ...];

value_list:
    literal [, ...]
```

**例**:
```sql
-- 基本
INSERT INTO users (id, name, email)
    VALUES (1, 'Alice', 'alice@example.com');

-- 複数行
INSERT INTO users (id, name) VALUES
    (2, 'Bob'),
    (3, 'Charlie');

-- ベクトル挿入
INSERT INTO documents (id, title, embedding)
    VALUES (1, 'AI Article', [0.1, 0.2, 0.3, ...]);
```

**ベクトルリテラル構文**:
```sql
[value, value, ...]

-- 例
[1.0, 2.0, 3.0]
[0.5, -0.3, 0.8, 0.1]
```

### 6.3 UPDATE

```sql
UPDATE table_name
    SET column_name = expr [, ...]
    [WHERE condition];
```

**例**:
```sql
UPDATE users SET name = 'Alice Smith' WHERE id = 1;

UPDATE documents
    SET embedding = [0.2, 0.3, 0.4, ...]
    WHERE id = 1;
```

**注意**: WHERE 句なしの UPDATE は全行更新（警告出力）

### 6.4 DELETE

```sql
DELETE FROM table_name
    [WHERE condition];
```

**例**:
```sql
DELETE FROM users WHERE id = 1;
DELETE FROM sessions WHERE expires_at < NOW();
```

**注意**: WHERE 句なしの DELETE は全行削除（警告出力）

---

## 7. 式・演算子仕様

### 7.1 演算子優先順位表（Pratt Parser 対応）

sqlparser-rs の Precedence パターンに基づく優先順位定義:

| 優先度値 | Precedence 名 | 演算子 | 結合性 | 説明 |
|----------|---------------|--------|--------|------|
| 100 | `Period` | `.` | 左 | メンバアクセス（将来予約） |
| 40 | `MulDivMod` | `*`, `/`, `%` | 左 | 乗算、除算、剰余 |
| 30 | `PlusMinus` | `+`, `-` | 左 | 加算、減算 |
| 25 | `StringConcat` | `\|\|` | 左 | 文字列連結 |
| 20 | `Comparison` | `=`, `<>`, `<`, `>`, `<=`, `>=`, `IN` | 左 | 比較 |
| 20 | `Between` | `BETWEEN ... AND ...` | - | 範囲比較 |
| 19 | `Like` | `LIKE`, `NOT LIKE` | 左 | パターンマッチング |
| 17 | `Is` | `IS NULL`, `IS NOT NULL` | 左 | NULL 判定 |
| 15 | `UnaryNot` | `NOT` | 右 | 論理否定 |
| 10 | `And` | `AND` | 左 | 論理積 |
| 5 | `Or` | `OR` | 左 | 論理和 |
| 0 | (unknown) | - | - | 優先順位なし |

**Pratt Parser との対応**:
```rust
impl Precedence {
    pub fn value(&self) -> u8 {
        match self {
            Self::Period => 100,
            Self::MulDivMod => 40,
            Self::PlusMinus => 30,
            Self::StringConcat => 25,
            Self::Comparison => 20,
            Self::Between => 20,
            Self::Like => 19,
            Self::Is => 17,
            Self::UnaryNot => 15,
            Self::And => 10,
            Self::Or => 5,
        }
    }
}
```

**パース例**: `1 + 2 * 3 > 5 AND x IS NOT NULL`
```
parse_subexpr(0)
  └─ prefix: 1
  └─ infix(+, 30):
       ├─ left: 1
       └─ right: parse_subexpr(30)
            └─ prefix: 2
            └─ infix(*, 40):
                 ├─ left: 2
                 └─ right: 3
  └─ infix(>, 20):
       ├─ left: 1 + 2 * 3
       └─ right: 5
  └─ infix(AND, 10):
       ├─ left: (1 + 2 * 3) > 5
       └─ right: parse_subexpr(10)
            └─ prefix: x
            └─ infix(IS, 17):
                 ├─ left: x
                 └─ right: NOT NULL
```

**括弧による優先順位の上書き**:
括弧内は `parse_expr()` を再帰呼び出しし、優先順位 0 から再開するため、すべての演算子より優先される。

### 7.2 比較演算子

| 演算子 | 説明 | 例 |
|--------|------|-----|
| `=` | 等価 | `a = b` |
| `<>` または `!=` | 不等価 | `a <> b` |
| `<` | より小さい | `a < b` |
| `>` | より大きい | `a > b` |
| `<=` | 以下 | `a <= b` |
| `>=` | 以上 | `a >= b` |

### 7.3 論理演算子

| 演算子 | 説明 | 真理値表 |
|--------|------|----------|
| `AND` | 論理積 | T∧T=T, T∧F=F, T∧N=N |
| `OR` | 論理和 | T∨F=T, F∨F=F, F∨N=N |
| `NOT` | 論理否定 | ¬T=F, ¬F=T, ¬N=N |

**短絡評価**: `AND`/`OR` は左から評価し、結果が確定した時点で右辺を評価しない。

### 7.4 LIKE / IN / BETWEEN

#### LIKE

```sql
expr LIKE pattern [ESCAPE escape_char]
```

| パターン | 意味 |
|----------|------|
| `%` | 任意の0文字以上 |
| `_` | 任意の1文字 |

**例**:
```sql
name LIKE 'A%'      -- A で始まる
name LIKE '%son'    -- son で終わる
name LIKE '_o_'     -- 3文字で中央が o
name LIKE '10\%%' ESCAPE '\'  -- 10% で始まる
```

#### IN

```sql
expr IN (value [, value ...])
expr NOT IN (value [, value ...])
```

**例**:
```sql
status IN ('active', 'pending')
id IN (1, 2, 3, 4, 5)
```

#### BETWEEN

```sql
expr BETWEEN low AND high
expr NOT BETWEEN low AND high
```

**セマンティクス**: `expr >= low AND expr <= high` と等価（両端を含む）

---

## 8. Vector 拡張仕様

### 8.1 ベクトルリテラル構文

```sql
[value, value, ...]
```

**例**:
```sql
[1.0, 2.0, 3.0]
[0.5, -0.3, 0.8, 0.1, 0.0]
```

**制約**:
- 要素は数値リテラル（整数または浮動小数点）
- 内部的には `Vec<f32>` で保持
- 空ベクトル `[]` は不可

### 8.2 vector_distance 関数

```sql
vector_distance(column, vector_literal, 'metric')
```

**引数**:

| 引数 | 型 | 説明 |
|------|----|------|
| `column` | VECTOR 型カラム | 比較対象カラム |
| `vector_literal` | ベクトルリテラル | クエリベクトル |
| `metric` | TEXT | `'cosine'`, `'l2'`, `'inner'` |

**戻り値**: `DOUBLE`（距離/類似度スコア）

**例**:
```sql
SELECT id, title,
       vector_distance(embedding, [0.1, 0.2, ...], 'cosine') AS score
    FROM documents
    WHERE vector_distance(embedding, [0.1, 0.2, ...], 'cosine') < 0.5;
```

### 8.3 vector_similarity 関数

`vector_distance` のエイリアス（可読性向上のため）。

```sql
vector_similarity(column, vector_literal, 'metric')
```

### 8.4 Top-K 検索最適化

以下のパターンは HNSW インデックスを利用した Top-K 検索に最適化される:

```sql
SELECT * FROM table
    ORDER BY vector_distance(column, query_vec, 'metric') [ASC|DESC]
    LIMIT k;
```

**最適化条件**:
1. ORDER BY に `vector_distance` / `vector_similarity` を使用
2. LIMIT 句が存在
3. 対象カラムに HNSW インデックスが存在
4. WHERE 句がないか、インデックス互換フィルタのみ

**最適化されるケース**:
```sql
-- ✅ 最適化される
SELECT * FROM docs
    ORDER BY vector_distance(embedding, [...], 'cosine')
    LIMIT 10;

-- ❌ 最適化されない（WHERE に非インデックス条件）
SELECT * FROM docs
    WHERE LENGTH(title) > 10
    ORDER BY vector_distance(embedding, [...], 'cosine')
    LIMIT 10;
```

---

## 8.5 将来拡張: TS (Time Series) 構文

v0.2.x 以降で、`alopex-query-common` 経由で skulk の型を使用して以下の TS 拡張構文を実装予定。

### MATCH 構文（PromQL スタイルラベルマッチング）

```sql
-- 構文
SELECT * FROM metrics
  WHERE MATCH(labels, '{job="api", instance=~"prod.*"}')

-- マッチ演算子
=   : 完全一致
!=  : 不一致
=~  : 正規表現マッチ
!~  : 正規表現非マッチ
```

**使用する型**: `skulk::query::{LabelMatcher, MatchOp}` (alopex-query-common 経由)

### TIME_BUCKET 関数

```sql
-- 構文
SELECT TIME_BUCKET(timestamp_col, '1h') AS bucket,
       SUM(value) AS total
  FROM metrics
  GROUP BY bucket

-- インターバル指定
'1m'  : 1分
'5m'  : 5分
'1h'  : 1時間
'1d'  : 1日
```

**使用する型**: `skulk::query::TSFunction::TimeBucket` (alopex-query-common 経由)

### 時系列関数 (RATE, DELTA, DERIVATIVE)

```sql
-- カウンタの秒間変化率
SELECT RATE(value, '5m') FROM metrics

-- ゲージの絶対差分
SELECT DELTA(value, '5m') FROM metrics

-- ゲージの秒間変化率
SELECT DERIVATIVE(value, '5m') FROM metrics
```

**使用する型**: `skulk::query::TSFunction` (alopex-query-common 経由)

**実装時の依存関係** (v0.2.x):

注意: alopex-sql は型の定義元であり、`alopex-query-common` には依存しない。
TS 拡張機能を使用する場合は UQM (`alopex-unified`) 経由でアクセスする。

```rust
// alopex-unified/Cargo.toml
[dependencies]
alopex-query-common = { path = "../alopex-query-common" }

// 使用例 (alopex-unified 内)
use alopex_query_common::{TSFunction, LabelMatcher, MatchOp};
// これらは実際には skulk::query から再エクスポートされた型
```

---

## 9. 組み込み関数一覧

### 9.1 数値関数

| 関数 | 説明 | 例 |
|------|------|-----|
| `ABS(x)` | 絶対値 | `ABS(-5)` → `5` |
| `ROUND(x [, n])` | 四捨五入 | `ROUND(3.14159, 2)` → `3.14` |
| `FLOOR(x)` | 切り捨て | `FLOOR(3.9)` → `3` |
| `CEIL(x)` | 切り上げ | `CEIL(3.1)` → `4` |
| `SQRT(x)` | 平方根 | `SQRT(16)` → `4` |
| `POW(x, y)` | べき乗 | `POW(2, 3)` → `8` |
| `MOD(x, y)` | 剰余 | `MOD(10, 3)` → `1` |

### 9.2 文字列関数

| 関数 | 説明 | 例 |
|------|------|-----|
| `LENGTH(s)` | 文字数 | `LENGTH('hello')` → `5` |
| `UPPER(s)` | 大文字化 | `UPPER('hello')` → `'HELLO'` |
| `LOWER(s)` | 小文字化 | `LOWER('HELLO')` → `'hello'` |
| `SUBSTR(s, start [, len])` | 部分文字列 | `SUBSTR('hello', 2, 3)` → `'ell'` |
| `TRIM(s)` | 空白除去 | `TRIM('  hi  ')` → `'hi'` |
| `LTRIM(s)` | 左空白除去 | `LTRIM('  hi')` → `'hi'` |
| `RTRIM(s)` | 右空白除去 | `RTRIM('hi  ')` → `'hi'` |
| `CONCAT(s1, s2, ...)` | 連結 | `CONCAT('a', 'b')` → `'ab'` |
| `REPLACE(s, from, to)` | 置換 | `REPLACE('aaa', 'a', 'b')` → `'bbb'` |

### 9.3 日時関数

| 関数 | 説明 | 例 |
|------|------|-----|
| `NOW()` | 現在時刻 (UTC) | `NOW()` → `2025-01-15 10:30:00` |
| `DATE(ts)` | 日付部分抽出 | `DATE(NOW())` → `2025-01-15` |
| `TIME(ts)` | 時刻部分抽出 | `TIME(NOW())` → `10:30:00` |
| `YEAR(ts)` | 年抽出 | `YEAR(NOW())` → `2025` |
| `MONTH(ts)` | 月抽出 | `MONTH(NOW())` → `1` |
| `DAY(ts)` | 日抽出 | `DAY(NOW())` → `15` |

**注意**: v0.3 ではタイムゾーン処理は UTC 固定。

### 9.4 集約関数

| 関数 | 説明 | NULL 処理 |
|------|------|-----------|
| `COUNT(*)` | 行数 | NULL を含む |
| `COUNT(col)` | 非 NULL 値の数 | NULL を除外 |
| `SUM(col)` | 合計 | NULL を無視 |
| `AVG(col)` | 平均 | NULL を無視 |
| `MIN(col)` | 最小値 | NULL を無視 |
| `MAX(col)` | 最大値 | NULL を無視 |
| `GROUP_CONCAT(col[, sep])` | 文字列連結 | NULL を無視 |
| `STRING_AGG(col, sep)` | 文字列連結 | NULL を無視 |

`COUNT/SUM/AVG/MIN/MAX/GROUP_CONCAT/STRING_AGG` は `DISTINCT` 修飾をサポートする。
DISTINCT の重複判定は GROUP BY と同一のキー等価性に従い、NULL は集約対象外。
`TOTAL(DISTINCT ...)` は未対応。

**注意**: v0.7.3 以降、非 DISTINCT 集約は単一プロセス内 partial→final 実行に対応する。
DISTINCT 集約は2段 partial→final では重複排除が保証できないため Single 実行に固定する。

---

## 10. エラーコード・メッセージ仕様

### 10.1 エラーコード体系

```
ALOPEX-[CATEGORY][NUMBER]

CATEGORY:
  P: Parse error (構文エラー)
  T: Type error (型エラー)
  R: Runtime error (実行時エラー)
  C: Catalog error (カタログエラー)
```

### 10.2 構文エラー (P)

| コード | メッセージ | 説明 |
|--------|------------|------|
| `ALOPEX-P001` | Unexpected token `{token}` at line {line}, column {col} | 予期しないトークン |
| `ALOPEX-P002` | Expected `{expected}` but found `{found}` | 期待するトークンがない |
| `ALOPEX-P003` | Unterminated string literal | 文字列リテラルが閉じられていない |
| `ALOPEX-P004` | Invalid number literal `{value}` | 不正な数値リテラル |
| `ALOPEX-P005` | Invalid vector literal | 不正なベクトルリテラル |

**エラー出力フォーマット**:
```
error[ALOPEX-P001]: Unexpected token 'FORM' at line 1, column 15
  --> query.sql:1:15
   |
 1 | SELECT * FORM users
   |              ^^^^ did you mean 'FROM'?
```

### 10.3 型エラー (T)

| コード | メッセージ | 説明 |
|--------|------------|------|
| `ALOPEX-T001` | Type mismatch: expected `{expected}`, found `{found}` | 型不一致 |
| `ALOPEX-T002` | Cannot compare `{type1}` with `{type2}` | 比較不可能な型 |
| `ALOPEX-T003` | Vector dimension mismatch: expected {expected}, found {found} | ベクトル次元不一致 |
| `ALOPEX-T004` | Cannot apply operator `{op}` to `{type}` | 演算子適用不可 |

### 10.4 実行時エラー (R)

| コード | メッセージ | 説明 |
|--------|------------|------|
| `ALOPEX-R001` | Division by zero | ゼロ除算 |
| `ALOPEX-R002` | Null constraint violation on column `{col}` | NOT NULL 違反 |
| `ALOPEX-R003` | Unique constraint violation on column `{col}` | UNIQUE 違反 |
| `ALOPEX-R004` | Primary key violation: duplicate value `{value}` | 主キー重複 |

### 10.5 カタログエラー (C)

| コード | メッセージ | 説明 |
|--------|------------|------|
| `ALOPEX-C001` | Table `{name}` does not exist | テーブル不存在 |
| `ALOPEX-C002` | Table `{name}` already exists | テーブル重複 |
| `ALOPEX-C003` | Column `{name}` does not exist in table `{table}` | カラム不存在 |
| `ALOPEX-C004` | Index `{name}` does not exist | インデックス不存在 |

---

## 11. 予約語一覧

以下は Alopex SQL の予約語であり、引用符なしで識別子として使用できない。

### DDL 関連
```
CREATE, DROP, TABLE, INDEX, IF, EXISTS, NOT, NULL, PRIMARY, KEY,
UNIQUE, DEFAULT, USING, WITH, CONSTRAINT, REFERENCES
```

### DML 関連
```
SELECT, INSERT, UPDATE, DELETE, FROM, WHERE, INTO, VALUES, SET,
ORDER, BY, ASC, DESC, LIMIT, OFFSET, DISTINCT, AS, NULLS, FIRST, LAST
```

### 型関連
```
INTEGER, INT, BIGINT, FLOAT, DOUBLE, TEXT, BLOB, BOOLEAN, BOOL,
TIMESTAMP, VECTOR
```

### 演算子/述語関連
```
AND, OR, NOT, IN, BETWEEN, LIKE, IS, ESCAPE, TRUE, FALSE
```

### 関数関連
```
CAST, CASE, WHEN, THEN, ELSE, END, NOW
```

### インデックス関連
```
BTREE, HNSW, COSINE, L2, INNER
```

### 将来予約（v0.3 では未使用）
```
JOIN, LEFT, RIGHT, INNER, OUTER, FULL, CROSS, ON, NATURAL,
GROUP, HAVING, UNION, INTERSECT, EXCEPT, ALL, ANY, SOME,
EXISTS, WITH, RECURSIVE, OVER, PARTITION, WINDOW,
BEGIN, COMMIT, ROLLBACK, TRANSACTION, SAVEPOINT
```

---

## 12. PostgreSQL との差分まとめ

| 機能 | PostgreSQL | Alopex SQL v0.3 | 備考 |
|------|------------|-----------------|------|
| 型キャスト | `::type`, `CAST()` | `CAST()` のみ | `::` は将来検討 |
| 文字列リテラル | `'string'`, `E'escape'` | `'string'` のみ | エスケープ記法なし |
| 識別子引用 | `"identifier"` | 未サポート | 将来追加予定 |
| 配列型 | `int[]` | 未サポート | ベクトル型で代替 |
| JSON 型 | `json`, `jsonb` | 未サポート | v0.5+ で検討 |
| SERIAL | `SERIAL`, `BIGSERIAL` | 未サポート | INTEGER + 手動採番 |
| スキーマ | `schema.table` | 未サポート | 単一スキーマ |
| RETURNING | `INSERT ... RETURNING *` | 未サポート | v0.4 で検討 |
| UPSERT | `ON CONFLICT` | 未サポート | v0.4 で検討 |
| 正規表現 | `~`, `~*` | 未サポート | LIKE のみ |

---

## 13. 実装マイルストーン

> **Note (2025-12-18)**: CD ワークフロー修正により v0.3.0 が crates.io に公開済み（旧 v0.1.3 Vector SQL 相当）。
> 旧 v0.1.0~v0.1.3 は v0.3.0 に統合、v0.1.4 以降は v0.4.0 以降に再番号付け。

### v0.3.0 SQL Frontend ✅ crates.io 公開済

以下の機能が v0.3.0 として crates.io に公開済み（旧 v0.1.0~v0.1.3 相当）:

| コンポーネント | 内容 | 状態 |
|----------------|------|------|
| Parser | Lexer/AST + DDL/DML Parser | ✅ 完了 |
| Planner | Catalog + LogicalPlan + 名前解決・型チェック | ✅ 完了 |
| Storage Engine | RowCodec + KeyEncoder + TableStorage/IndexStorage + TxnBridge | ✅ 完了 |
| Executor | DDL/DML Executor + Iterator ベース実行 | ✅ 完了 |
| Vector SQL | `vector_similarity` 関数 + Top-K 最適化 | ✅ 完了 |

### v0.4.0 Embedded Integration ⏳ 予定

- `Database::execute_sql` API
- `Transaction::execute_sql` API
- Catalog の永続化

### v0.5.0+ 後続バージョン

#### 依存関係の方向性（TS 拡張）

**重要**: alopex-sql と skulk が型の**定義元 (Source of Truth)** である。`alopex-query-common` は薄いファサードとして型を再エクスポートする。

```
    ┌─────────────┐  ┌─────────────────┐
    │   skulk     │  │   alopex-sql    │   ← SOURCE OF TRUTH
    │  (TSDB)     │  │  (本クレート)    │     型の定義元
    └──────┬──────┘  └────────┬────────┘
           │                  │
           └────────┬─────────┘
                    │ 再エクスポート
                    ▼
           ┌─────────────────────┐
           │ alopex-query-common │   ← FACADE
           │  (型の再エクスポート) │     薄いラッパー
           └─────────┬───────────┘
                     │
                     ▼
           ┌──────────────────┐
           │  alopex-unified  │
           │     (UQM)        │
           └──────────────────┘
```

**TS 拡張で使用する型** (`alopex-query-common` 経由で skulk の型を利用):
- `skulk::query::TSFunction`: 時系列関数 (rate, delta, time_bucket など)
- `skulk::query::LabelMatcher`, `MatchOp`: MATCH 構文用ラベルマッチャー
- `alopex_query_common::TimeRange`, `QueryContext`: 補助型 (独自定義)

**禁止事項**:
- ❌ `skulk` クレートへの直接依存（`alopex-query-common` 経由で利用）
- ❌ `alopex-query-common` への依存（循環依存回避、alopex-sql は型の定義元）

**参照ドキュメント**:
- [alopex-query-common 設計書](../../docs-internal/design/alopex-query-common-design.md) - 型の再エクスポート層
- [Skulk v0.4 Query Engine 要件](../../.spec-workflow/specs/skulk-v0.4-query-engine/requirements.md) - 時系列型の定義元

| バージョン | 内容 | 対応 DB |
|------------|------|---------|
| v0.5.0 | GROUP BY / Aggregation | v0.5 |
| v0.5.1 | 次世代検索インデックス基盤（SHA-256/SimHash/UUIDv7） | v0.5 |
| v0.5.2 | キャッシュ・メモリ管理（I/O計測、アダプティブキャッシュ） | v0.5 |
| v0.6.0 | JOIN Support（INNER/LEFT/RIGHT） | v0.6 |
| v0.7.0 | WASM Parser（Read-Only SQL） | v0.7 |
| v0.8.0 | Subquery（WHERE/FROM 句） | v0.7 |
| v0.9.0 | Distributed Query Planner（Chirps v0.3 依存） | v0.8 |
| v0.10.0 | Raft-aware Executor（Chirps v0.6 依存） | v0.9 |
| v0.11.0 | Multi-Raft Query（Chirps v0.7 依存） | v0.10 |
| v0.12.0 | Federation Query（Chirps v0.8 依存） | v1.0 |
| v1.0.0 | Query Optimizer（コストベース最適化） | v1.0 |

---

## 13. v0.7.4 SQL 拡張

v0.7.4 は既存のベクトル関数と集約関数を維持したまま、レジストリ管理の
スカラー関数、ハッシュ/エンコード関数、システム関数、PRAGMA を追加する。
破壊的変更は意図していない。`md5` は互換性・フィンガープリント用途に限り、
パスワード保存や署名など衝突耐性が必要な用途には使用しない。

### 13.1 数値・文字列・条件・型情報

以下の関数は型検査後にレジストリ経由で評価される。NULL 規則と短絡評価は
各関数の SQL semantics に従う。

| 分類 | 関数 |
|------|------|
| 数値・三角 | `ABS`, `SIGN`, `ROUND`, `FLOOR`, `CEIL`, `CEILING`, `TRUNC`, `MOD`, `POWER`, `POW`, `SQRT`, `EXP`, `LN`, `LOG`, `LOG10`, `SIN`, `COS`, `TAN`, `ASIN`, `ACOS`, `ATAN`, `ATAN2`, `PI`, `DEGREES`, `RADIANS`, `RANDOM` |
| 文字列 | `LENGTH`, `CHAR_LENGTH`, `OCTET_LENGTH`, `UPPER`, `LOWER`, `INITCAP`, `SUBSTR`, `LEFT`, `RIGHT`, `TRIM`, `LTRIM`, `RTRIM`, `REPLACE`, `INSTR`, `STRPOS`, `CONCAT`, `CONCAT_WS`, `REPEAT`, `REVERSE`, `LPAD`, `RPAD`, `SPLIT_PART` |
| 正規表現 | `REGEXP_REPLACE`, `REGEXP_MATCH`, `REGEXP_MATCHES` |
| 条件・型 | `COALESCE`, `NULLIF`, `IFNULL`, `IIF`, `GREATEST`, `LEAST`, `TYPEOF`, `PG_TYPEOF`, `QUOTE` |

パターン演算子は `LIKE`, `ILIKE`, `GLOB`, `SIMILAR TO` をサポートする。
`NOT` と `ESCAPE`、NULL 結果、大小文字規則は演算子ごとに適用される。
SQL 標準形式 `SUBSTRING(s FROM start FOR length)`, `POSITION(sub IN s)`,
`TRIM(chars FROM s)` は対応する関数形式へ正規化される。

### 13.2 ハッシュ・UUID・エンコード

| 関数 | 戻り値 | 注記 |
|------|--------|------|
| `SHA256(value)` | BLOB | SHA-256 digest。入力上限16 MiB |
| `MD5(value)` | TEXT | 小文字16進。セキュリティ用途禁止 |
| `SIMHASH(value)` | BIGINT | ASCII空白分割、SHA-256先頭8バイトによる決定的64-bit値 |
| `HAMMING_DISTANCE(a, b)` | INTEGER | 64-bit bit pattern の popcount |
| `GEN_RANDOM_UUID()` / `UUIDV7()` | TEXT | 標準UUID表記、非決定的 |
| `HEX(value)` / `UNHEX(value)` | TEXT / BLOB | HEX出力は大文字、入力不正はエラー |
| `ENCODE(value, format)` / `DECODE(value, format)` | TEXT / BLOB | `hex` または `base64`、base64は標準padding必須 |

### 13.3 システム関数と PRAGMA

`memory_stats()` と `io_stats()` はバックエンドが提供する統計だけをJSON TEXT
で返し、対象外の統計は NULL を返す。`clear_cache()` は消去したバイト数を
BIGINT で返す。

```sql
SELECT memory_stats(), io_stats(), clear_cache();
PRAGMA cache_size = 1024;       -- 4096-byte pages
PRAGMA memory_limit = '256MiB'; -- KiB/MiB/GiB または KB/MB/GB
PRAGMA io_stats;
```

`PRAGMA cache_size`、`PRAGMA memory_limit` の変更は実行結果が成功となり、
`PRAGMA io_stats` は `io_stats` という1列のQuery結果を返す。負値、未知の
PRAGMA名、不正な単位はエラーとなる。

## 14. 更新履歴

| バージョン | 日付 | 内容 |
|------------|------|------|
| 0.3.0-draft | 2025-11-29 | 初版作成 |
| 0.3.0-draft | 2025-11-30 | 実装マイルストーンセクション追加 |
| 0.3.1-draft | 2025-12-02 | sqlparser-rs 調査に基づくパーサー実装アーキテクチャ追加（Pratt Parser、Dialect システム、Visitor パターン） |
| 0.3.2-draft | 2025-12-15 | TS 拡張構文セクション追加、alopex-query-common 依存関係の方向性を明記 |
| 0.3.3-draft | 2025-12-16 | 依存関係の方向性修正（skulk/alopex-sql が SOURCE OF TRUTH、alopex-query-common が再エクスポート） |
| 0.3.4-draft | 2025-12-18 | CD ワークフローによる v0.3.0 公開を反映しバージョン番号を再調整（v0.1.x→v0.3.0統合、v0.1.4→v0.4.0、後続バージョン繰り上げ） |
| 0.7.4-draft | 2026-07-17 | レジストリ・ハッシュ/UUID/エンコード・システム関数・PRAGMA の実装仕様を反映 |

---

## 付録 A: 文法定義（簡略 BNF）

```bnf
<statement> ::= <select_stmt>
              | <insert_stmt>
              | <update_stmt>
              | <delete_stmt>
              | <create_table_stmt>
              | <drop_table_stmt>
              | <create_index_stmt>
              | <drop_index_stmt>

<select_stmt> ::= SELECT [DISTINCT] <select_list>
                  FROM <table_ref>
                  [WHERE <expr>]
                  [ORDER BY <order_list>]
                  [LIMIT <number> [OFFSET <number>]]

<insert_stmt> ::= INSERT INTO <table_name> [( <column_list> )]
                  VALUES <values_list>

<update_stmt> ::= UPDATE <table_name>
                  SET <assignment_list>
                  [WHERE <expr>]

<delete_stmt> ::= DELETE FROM <table_name>
                  [WHERE <expr>]

<expr> ::= <literal>
         | <column_ref>
         | <expr> <binary_op> <expr>
         | <unary_op> <expr>
         | <function_call>
         | '(' <expr> ')'
         | <vector_literal>

<vector_literal> ::= '[' <number> (',' <number>)* ']'

<data_type> ::= INTEGER | BIGINT | FLOAT | DOUBLE
              | TEXT | BLOB | BOOLEAN | TIMESTAMP
              | VECTOR '(' <number> [',' <metric>] ')'

<metric> ::= COSINE | L2 | INNER
```
