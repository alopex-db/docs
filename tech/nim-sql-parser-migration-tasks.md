# Nim SQL パーサー移行タスク票

**作成日**: 2026-06-27
**目的**: alopex-sql クレートの SQL パーサー（Tokenizer / Parser / AST）を Nim に移行し、C ABI FFI で Rust Planner に統合する

---

## アーキテクチャ概要

```
┌─────────────────────────────────────────┐
│  Nim SQL Parser                         │
│  ├── Lexer (tokenizer)                  │
│  ├── Parser (recursive descent + Pratt) │
│  └── AST → JSON シリアライズ             │
│  出力: JSON 文字列 (C ABI)               │
└────────────┬────────────────────────────┘
             │ extern "C" FFI (JSON over cstring)
             ▼
┌─────────────────────────────────────────┐
│  alopex-sql (Rust)                      │
│  ├── FFI Bridge (JSON → Rust AST)       │
│  ├── Planner (AST → LogicalPlan)        │  ← 変更なし
│  ├── TypeChecker                        │  ← 変更なし
│  └── Executor                           │  ← 変更なし
└─────────────────────────────────────────┘
```

---

## 依存関係マップ

### パーサーの呼び出し元（変更が必要な箇所）

| ファイル | 呼び出し | 変更内容 |
|---|---|---|
| `alopex-sql/src/planner/mod.rs` | `Statement`, `StatementKind` を消費 | FFI Bridge 経由で同じ型を受け取る（変更不要） |
| `alopex-embedded/src/sql_api.rs` | `Parser::parse_sql(&dialect, sql)` | FFI Bridge の `parse_sql()` に置換 |
| `alopex-server/src/http/sql.rs` | `Parser::parse_sql(&AlopexDialect, sql)` | 同上 |
| `alopex-server/src/grpc/mod.rs` | `Parser::parse_sql(&AlopexDialect, sql)` | 同上 |

### 変更不要な箇所（パーサー出力を間接的に消費）

| 層 | 理由 |
|---|---|
| `Planner` | AST 型（`Statement`, `Expr` 等）をそのまま消費。FFI Bridge が同じ Rust AST 型を生成すれば変更不要 |
| `TypeChecker` | `Expr` → `TypedExpr` 変換。Planner と同様 |
| `Executor` | `LogicalPlan` のみ消費。AST に直接依存しない |
| `Catalog` | メタデータのみ。パーサーに依存しない |
| `Storage` | 値のみ。パーサーに依存しない |

### Rust AST 型（Nim が生成する必要がある型）

```
Statement { kind: StatementKind, span: Span }
├── StatementKind::Select(Select)
│   ├── distinct: bool
│   ├── projection: Vec<SelectItem>  [Wildcard | Expr{expr, alias}]
│   ├── from: TableRef {name, alias}
│   ├── selection: Option<Expr>      (WHERE)
│   ├── group_by: Option<Vec<Expr>>
│   ├── having: Option<Expr>
│   ├── order_by: Vec<OrderByExpr>   {expr, asc, nulls_first}
│   ├── limit: Option<Expr>
│   └── offset: Option<Expr>
├── StatementKind::Insert(Insert)
│   ├── table: String
│   ├── columns: Option<Vec<String>>
│   └── values: Vec<Vec<Expr>>
├── StatementKind::Update(Update)
│   ├── table: String
│   ├── assignments: Vec<Assignment> {column, value}
│   └── selection: Option<Expr>
├── StatementKind::Delete(Delete)
│   ├── table: String
│   └── selection: Option<Expr>
├── StatementKind::CreateTable(CreateTable)
│   ├── if_not_exists: bool
│   ├── name: String
│   ├── columns: Vec<ColumnDef>     {name, data_type, constraints}
│   ├── constraints: Vec<TableConstraint>
│   └── with_options: Vec<(String, String)>
├── StatementKind::DropTable(DropTable)
├── StatementKind::CreateIndex(CreateIndex)
│   ├── name, table, column: String
│   ├── method: Option<IndexMethod>  [BTree | Hnsw]
│   └── options: Vec<IndexOption>
└── StatementKind::DropIndex(DropIndex)

Expr { kind: ExprKind, span: Span }
├── Literal(Number|String|Boolean|Null)
├── ColumnRef { table: Option<String>, column: String }
├── BinaryOp { left, op, right }     [Add|Sub|Mul|Div|Mod|Eq|Neq|Lt|Gt|LtEq|GtEq|And|Or|StringConcat]
├── UnaryOp { op, operand }          [Not|Minus]
├── FunctionCall { name, args, distinct, star }
├── Between { expr, low, high, negated }
├── Like { expr, pattern, escape, negated }
├── InList { expr, list, negated }
├── IsNull { expr, negated }
└── VectorLiteral(Vec<f64>)

DataType: Integer|Int|BigInt|Float|Double|Text|Blob|Boolean|Bool|Timestamp|Vector{dimension,metric}
```

---

## マイルストーンとタスク

### M0: 準備（1日）

| # | タスク | 依存 | 成果物 |
|---|---|---|---|
| M0-1 | experiment/sql-parser-trial ブランチの nim-sql-parser を feature/nim-parser-migration ブランチにコピー | — | 作業ブランチ |
| M0-2 | Nim ビルドを alopex の Makefile / CI に統合（nimble install + nim c） | M0-1 | `make nim-parser` ターゲット |
| M0-3 | `.github/workflows/` に Nim ビルドステップ追加 | M0-2 | CI で Nim パーサーがビルド可能 |

### M1: Nim パーサーを Rust AST 互換に拡充（3〜5日）

試験実装では基本 DML/DDL のみ。Rust 版パーサーの全機能に合わせて拡充する。

| # | タスク | 依存 | 成果物 |
|---|---|---|---|
| M1-1 | AST 型を Rust 版と完全一致させる（フィールド名・型・variant） | M0-1 | `src/ast.nim` 更新 |
| M1-2 | Lexer に不足キーワードを追加（CAST, CASE, WHEN, THEN, ELSE, END, NOW, HNSW, BTREE, CONSTRAINT, ESCAPE 等 88 キーワード） | M0-1 | `src/lexer.nim` 更新 |
| M1-3 | Lexer に `||`（StringConcat）、`[` `]`（ベクトルリテラル）トークン追加 | M1-2 | `src/lexer.nim` 更新 |
| M1-4 | Parser: CREATE INDEX / DROP INDEX 対応 | M1-1 | `src/parser.nim` 更新 |
| M1-5 | Parser: WITH オプション句パース（CREATE TABLE / CREATE INDEX） | M1-4 | `src/parser.nim` 更新 |
| M1-6 | Parser: VECTOR(dimension, metric) データ型パース | M1-5 | `src/parser.nim` 更新 |
| M1-7 | Parser: ベクトルリテラル `[1.0, 2.0, -3.0]` パース | M1-3, M1-6 | `src/parser.nim` 更新 |
| M1-8 | Parser: FunctionCall の DISTINCT / star 対応（COUNT(DISTINCT x), COUNT(*)） | M1-1 | `src/parser.nim` 更新 |
| M1-9 | Parser: StringConcat `||` 演算子対応 | M1-3 | `src/parser.nim` 更新 |
| M1-10 | Parser: GROUP BY / HAVING 対応（試験実装から移植済みだが Rust テストで検証） | M1-1 | `src/parser.nim` 更新 |
| M1-11 | Parser: NULLS FIRST / NULLS LAST 対応（ORDER BY） | M1-1 | `src/parser.nim` 更新 |
| M1-12 | Parser: 複数文パース（`;` 区切り） | M1-1 | `src/parser.nim` 更新 |
| M1-13 | Span（位置情報）を全 AST ノードに付与 | M1-1〜M1-12 | 全ファイル更新 |
| M1-14 | Rust テスト 74+ ケースを全て Nim テストに移植・PASS 確認 | M1-1〜M1-13 | `tests/test_parser.nim` 更新 |

### M2: JSON シリアライズ層（1〜2日）

Nim AST → JSON → Rust AST の変換パイプラインを構築する。

| # | タスク | 依存 | 成果物 |
|---|---|---|---|
| M2-1 | Nim AST → JSON シリアライズを Rust AST フィールド名と完全一致させる | M1-14 | `src/alopex_sql_parser.nim` 更新 |
| M2-2 | JSON スキーマ定義書を作成（Nim ↔ Rust 間の契約） | M2-1 | `docs/json-ast-schema.md` |
| M2-3 | Nim 側の JSON 出力に対するスナップショットテスト追加 | M2-1 | `tests/test_json_output.nim` |

### M3: Rust FFI Bridge（2〜3日）

Rust 側に Nim パーサーを呼び出す FFI 層を構築する。

| # | タスク | 依存 | 成果物 |
|---|---|---|---|
| M3-1 | `alopex-sql/src/nim_ffi.rs` 作成: `extern "C"` 宣言 + libalopex_sql_parser.so リンク | M2-1 | `nim_ffi.rs` |
| M3-2 | `alopex-sql/build.rs` 作成: Nim ライブラリのリンク設定 | M3-1 | `build.rs` |
| M3-3 | JSON → Rust AST デシリアライズ実装（`serde_json` で `Statement` を構築） | M2-2 | `src/nim_bridge.rs` |
| M3-4 | `NimParser::parse_sql(sql: &str) -> Result<Vec<Statement>>` ラッパー実装 | M3-1, M3-3 | `src/nim_bridge.rs` |
| M3-5 | Rust 側パーサーとの等価性テスト: 同一 SQL → 同一 AST を検証 | M3-4 | `tests/nim_parity_test.rs` |
| M3-6 | エラーケースの FFI 伝播テスト（不正 SQL → Nim エラー → Rust ParserError） | M3-4 | `tests/nim_error_test.rs` |

### M4: 呼び出し元の切り替え（1日）

| # | タスク | 依存 | 成果物 |
|---|---|---|---|
| M4-1 | `alopex-sql/src/lib.rs` に feature flag `nim-parser` 追加 | M3-5 | `Cargo.toml` + `lib.rs` |
| M4-2 | `Parser::parse_sql()` を feature flag で Nim / Rust 切り替え可能にする | M4-1 | `src/parser/mod.rs` 更新 |
| M4-3 | `alopex-embedded/src/sql_api.rs` が feature flag 経由で Nim パーサーを使用 | M4-2 | 変更なし（透過的） |
| M4-4 | `alopex-server` が feature flag 経由で Nim パーサーを使用 | M4-2 | 変更なし（透過的） |
| M4-5 | 全統合テスト（`cargo test -p alopex-sql --features nim-parser,lane_ci`）PASS | M4-2 | CI green |

### M5: 検証・最適化（2〜3日）

| # | タスク | 依存 | 成果物 |
|---|---|---|---|
| M5-1 | パース性能ベンチマーク: Nim vs Rust で同一 SQL 1000 回パース | M4-5 | ベンチマーク結果 |
| M5-2 | メモリリークテスト: Nim ORC + Rust FFI でリーク検出 | M4-5 | Valgrind / AddressSanitizer レポート |
| M5-3 | エラーメッセージ品質: Span 情報が正しく伝播されることを検証 | M4-5 | テスト追加 |
| M5-4 | Dockerfile 更新: マルチステージビルドに Nim ステージ追加 | M4-5 | `Dockerfile` 更新 |
| M5-5 | CI ワークフロー更新: `nim-parser` feature を CI マトリクスに追加 | M5-4 | `.github/workflows/` 更新 |

### M6: Rust パーサーの段階的廃止（1日）

| # | タスク | 依存 | 成果物 |
|---|---|---|---|
| M6-1 | `nim-parser` feature をデフォルト有効化 | M5-1〜M5-5 | `Cargo.toml` 更新 |
| M6-2 | Rust パーサー（`src/parser/`, `src/tokenizer/`）を `#[cfg(not(feature = "nim-parser"))]` で条件コンパイル化 | M6-1 | 既存コード保持 |
| M6-3 | リリースノート・CHANGELOG に Nim パーサー移行を記載 | M6-2 | ドキュメント更新 |

---

## タイムライン

```
M0 (1d)  M1 (3-5d)      M2 (1-2d)  M3 (2-3d)    M4 (1d)  M5 (2-3d)  M6 (1d)
├────────┼──────────────┼──────────┼────────────┼────────┼──────────┼────────┤
準備      Nim パーサー    JSON       FFI Bridge   切替     検証       廃止
          拡充           シリアライズ                                Rust parser

合計: 11〜16 日（2〜3 週間）
```

---

## リスクと緩和策

| リスク | 影響 | 緩和策 |
|---|---|---|
| Nim ORC と Rust FFI 間のメモリリーク | メモリ使用量増大 | M5-2 で Valgrind 検証。`alopex_free_string()` を確実に呼び出す |
| JSON シリアライズのオーバーヘッド | パース速度低下 | 将来的に JSON → C 構造体直接渡しに最適化可能。現時点では無視可能（パースは全体の数%） |
| Nim コンパイラのバージョン間互換性 | CI 破損 | Docker イメージでバージョン固定（`nimlang/nim:2.2`） |
| Rust AST 型の変更に Nim 側が追従できない | パース結果不一致 | M3-5 の等価性テストが回帰を検出。JSON スキーマを契約として管理 |
| feature flag による条件コンパイルの複雑化 | ビルド設定の混乱 | M6 で Rust パーサーを完全廃止し、feature flag を削除 |

---

## 成功基準

1. `cargo test -p alopex-sql --features nim-parser,lane_ci` — **全テスト PASS**
2. `cargo test -p alopex-embedded --features nim-parser` — **全テスト PASS**
3. Nim パーサーの release ビルド時間 — **3 秒以内**
4. パース性能 — **Rust 版と同等以上**（Binary Trees ベンチマークから Nim が有利と予測）
5. メモリリーク — **ゼロ**（Valgrind clean）
