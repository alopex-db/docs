# alopex-sql Query Engine Milestone

> 詳細仕様は `.spec-workflow/specs/` 配下の各 spec ドキュメントを参照。

> **Note (2025-12-18)**: CD ワークフロー修正により v0.3.0 が crates.io に公開済み（旧 v0.1.3 Vector SQL 相当）。
> 旧 v0.1.0~v0.1.3 は v0.3.0 に統合、v0.1.4 以降は v0.4.0 以降に再番号付け。

## Overview

alopex-sql クエリエンジンの実装マイルストーンと、各バージョンで実装する具体的な関数・型の一覧。

### v0.3.0 SQL Frontend ✅ crates.io 公開済

| コンポーネント | 内容 | 状態 |
|----------------|------|------|
| Parser | Lexer + AST + DDL/DML Parser | ✅ 完了 |
| Planner | Catalog + LogicalPlan + 名前解決・型チェック | ✅ 完了 |
| Storage Engine | RowCodec + KeyEncoder + TableStorage/IndexStorage + TxnBridge | ✅ 完了 |
| Executor | DDL/DML Executor + Iterator ベース実行 | ✅ 完了 |
| Vector SQL | `vector_similarity` 関数 + Top-K 最適化 | ✅ 完了 |

### 後続バージョン

| Version | Milestone | Status | Spec Location |
|---------|-----------|--------|---------------|
| **v0.4.0** | **Embedded Integration** | ⏳ Planned | `.spec-workflow/specs/alopex-sql-v0.4.0/` |
| v0.5.0 | GROUP BY / Aggregation | ⏳ Planned | - |
| v0.5.1 | 次世代検索インデックス基盤 | ⏳ Planned | - |
| v0.5.2 | キャッシュ・メモリ管理 | ⏳ Planned | - |
| v0.6.0 | JOIN Support | ⏳ Planned | - |
| v0.7.0 | WASM Parser | ⏳ Planned | - |
| v0.8.0 | Subquery | ⏳ Planned | - |

---

## Executor 詳細仕様 (v0.3.0 に統合済み)

> 以下は旧 v0.1.2 Executor の詳細仕様。v0.3.0 として crates.io に公開済み。

### Module Structure

```
alopex-sql/src/executor/
├── mod.rs           # Executor trait & main dispatcher
├── error.rs         # ExecutorError enum
├── result.rs        # ExecutionResult, QueryResult
├── evaluator/
│   ├── mod.rs       # evaluate() entry point
│   ├── binary.rs    # BinaryOp evaluation
│   ├── unary.rs     # UnaryOp evaluation
│   └── null.rs      # NULL 3-valued logic helpers
├── ddl/
│   ├── mod.rs       # DDL dispatcher
│   ├── create_table.rs
│   ├── drop_table.rs
│   ├── create_index.rs
│   └── drop_index.rs
├── dml/
│   ├── mod.rs       # DML dispatcher
│   ├── insert.rs
│   ├── update.rs
│   └── delete.rs
└── query/
    ├── mod.rs       # Query executor
    ├── scan.rs
    ├── filter.rs
    ├── sort.rs
    └── limit.rs
```

### Core Types

```rust
// executor/error.rs
pub enum ExecutorError {
    // Storage errors
    Storage(StorageError),

    // Constraint violations
    ConstraintViolation(ConstraintViolation),

    // Evaluation errors
    Evaluation(EvaluationError),

    // Unsupported operations
    UnsupportedOperation(String),
    UnsupportedExpression(String),

    // Catalog errors
    TableNotFound(String),
    TableAlreadyExists(String),
    IndexNotFound(String),
    IndexAlreadyExists(String),
    ColumnRequired(String),
}

pub enum ConstraintViolation {
    NotNull { column: String },
    PrimaryKey { column: String, value: SqlValue },
}

pub enum EvaluationError {
    DivisionByZero,
    Overflow,
    TypeMismatch { expected: String, actual: String },
    InvalidColumnRef { index: usize },
}

// executor/result.rs
pub enum ExecutionResult {
    /// DDL success (CREATE/DROP)
    Success,

    /// DML success with affected row count
    RowsAffected(u64),

    /// Query result with columns and rows
    Query(QueryResult),
}

pub struct QueryResult {
    /// Column metadata for result set
    pub columns: Vec<ColumnInfo>,

    /// Result rows (each row matches columns order)
    pub rows: Vec<Vec<SqlValue>>,
}

pub struct ColumnInfo {
    pub name: String,
    pub data_type: ResolvedType,
}
```

### Main Executor Interface

```rust
// executor/mod.rs

/// Main executor that processes LogicalPlan.
pub struct Executor<S: KVStore> {
    catalog: Catalog,
    bridge: TxnBridge<S>,
}

impl<S: KVStore> Executor<S> {
    /// Create a new executor with the given KV store.
    pub fn new(store: Arc<S>) -> Self;

    /// Execute a logical plan and return the result.
    ///
    /// Each call is a single transaction:
    /// - DDL/DML: write transaction
    /// - Query: read transaction
    pub fn execute(&mut self, plan: LogicalPlan) -> Result<ExecutionResult, ExecutorError>;
}
```

### Expression Evaluator

```rust
// executor/evaluator/mod.rs

/// Evaluation context holding the current row data.
pub struct EvalContext<'a> {
    /// Current row values (indexed by column_index)
    pub row: &'a [SqlValue],
}

/// Evaluate a typed expression in the given context.
///
/// # Supported (v0.1.2)
/// - Literal, ColumnRef
/// - BinaryOp: +, -, *, /, =, <>, <, <=, >, >=, AND, OR
/// - UnaryOp: NOT, - (negation)
/// - IsNull, IsNotNull
///
/// # Unsupported (returns UnsupportedExpression error)
/// - Between, Like, InList, Cast, FunctionCall, VectorLiteral
pub fn evaluate(expr: &TypedExpr, ctx: &EvalContext) -> Result<SqlValue, EvaluationError>;

// executor/evaluator/binary.rs

/// Evaluate arithmetic: +, -, *, /
/// - NULL propagation: any NULL operand → NULL result
/// - Division by zero → DivisionByZero error
/// - Integer overflow → Overflow error
pub fn eval_arithmetic(
    left: &SqlValue,
    op: BinaryOp,
    right: &SqlValue,
) -> Result<SqlValue, EvaluationError>;

/// Evaluate comparison: =, <>, <, <=, >, >=
/// - NULL propagation: any NULL operand → NULL result (not true/false)
/// - Type coercion: Integer/BigInt/Float/Double are comparable
pub fn eval_comparison(
    left: &SqlValue,
    op: BinaryOp,
    right: &SqlValue,
) -> Result<SqlValue, EvaluationError>;

/// Evaluate logical: AND, OR
/// - 3-valued logic:
///   - NULL AND true → NULL
///   - NULL AND false → false
///   - NULL OR true → true
///   - NULL OR false → NULL
pub fn eval_logical(
    left: &SqlValue,
    op: BinaryOp,
    right: &SqlValue,
) -> Result<SqlValue, EvaluationError>;

// executor/evaluator/unary.rs

/// Evaluate NOT
/// - NOT true → false
/// - NOT false → true
/// - NOT NULL → NULL
pub fn eval_not(operand: &SqlValue) -> Result<SqlValue, EvaluationError>;

/// Evaluate unary minus (negation)
/// - -NULL → NULL
/// - -Integer(n) → Integer(-n)
/// - -Float(n) → Float(-n)
pub fn eval_negate(operand: &SqlValue) -> Result<SqlValue, EvaluationError>;

// executor/evaluator/null.rs

/// Check if value is truthy for filter evaluation.
/// - true → true
/// - false, NULL, other → false
pub fn is_truthy(value: &SqlValue) -> bool;
```

### DDL Executors

```rust
// executor/ddl/create_table.rs

/// Execute CREATE TABLE.
///
/// 1. Check if table exists (error or skip based on if_not_exists)
/// 2. Assign unique table_id via catalog
/// 3. Register table metadata in catalog (persisted)
/// 4. Return Success
pub fn execute_create_table<S: KVStore>(
    txn: &mut SqlTransaction<S>,
    catalog: &mut Catalog,
    table: TableMetadata,
    if_not_exists: bool,
) -> Result<ExecutionResult, ExecutorError>;

// executor/ddl/drop_table.rs

/// Execute DROP TABLE.
///
/// 1. Resolve table_id (error or skip based on if_exists)
/// 2. Get all indexes for this table
/// 3. For each index: delete all index entries, remove from catalog
/// 4. Delete all rows (scan key space and delete)
/// 5. Remove table from catalog
/// 6. Return Success
pub fn execute_drop_table<S: KVStore>(
    txn: &mut SqlTransaction<S>,
    catalog: &mut Catalog,
    name: &str,
    if_exists: bool,
) -> Result<ExecutionResult, ExecutorError>;

// executor/ddl/create_index.rs

/// Execute CREATE INDEX.
///
/// 1. Resolve table_id
/// 2. Check if index exists (error or skip based on if_not_exists)
/// 3. Assign unique index_id via catalog
/// 4. Scan all existing rows and build index entries
/// 5. Register index metadata in catalog
/// 6. Return Success
pub fn execute_create_index<S: KVStore>(
    txn: &mut SqlTransaction<S>,
    catalog: &mut Catalog,
    index: IndexMetadata,
    if_not_exists: bool,
) -> Result<ExecutionResult, ExecutorError>;

// executor/ddl/drop_index.rs

/// Execute DROP INDEX.
///
/// 1. Resolve index_id (error or skip based on if_exists)
/// 2. Delete all index entries (scan index key space and delete)
/// 3. Remove index from catalog
/// 4. Return Success
pub fn execute_drop_index<S: KVStore>(
    txn: &mut SqlTransaction<S>,
    catalog: &mut Catalog,
    name: &str,
    if_exists: bool,
) -> Result<ExecutionResult, ExecutorError>;
```

### DML Executors

```rust
// executor/dml/insert.rs

/// Execute INSERT.
///
/// 1. Resolve table metadata and table_id
/// 2. Validate all columns are provided (v0.1.2: no DEFAULT)
/// 3. For each row:
///    a. Evaluate TypedExpr values → SqlValue
///    b. Validate NOT NULL constraints
///    c. Validate PRIMARY KEY uniqueness (if applicable)
///    d. Assign row_id via RowIdGenerator
///    e. Insert row via TableStorage::insert()
///    f. Insert index entries for all indexes on this table
/// 4. Return RowsAffected(count)
pub fn execute_insert<S: KVStore>(
    txn: &mut SqlTransaction<S>,
    catalog: &Catalog,
    table: &str,
    columns: &[String],
    values: &[Vec<TypedExpr>],
) -> Result<ExecutionResult, ExecutorError>;

// executor/dml/update.rs

/// Execute UPDATE.
///
/// 1. Resolve table metadata and table_id
/// 2. Scan all rows via TableStorage::scan()
/// 3. For each row:
///    a. Evaluate filter predicate (if any)
///    b. If filter is truthy:
///       - Evaluate assignment expressions
///       - Validate constraints (NOT NULL, PK uniqueness)
///       - For indexed columns: delete old index entries
///       - Update row via TableStorage::update()
///       - For indexed columns: insert new index entries
///       - Increment affected count
/// 4. Return RowsAffected(count)
pub fn execute_update<S: KVStore>(
    txn: &mut SqlTransaction<S>,
    catalog: &Catalog,
    table: &str,
    assignments: &[TypedAssignment],
    filter: Option<&TypedExpr>,
) -> Result<ExecutionResult, ExecutorError>;

// executor/dml/delete.rs

/// Execute DELETE.
///
/// 1. Resolve table metadata and table_id
/// 2. Scan all rows via TableStorage::scan()
/// 3. For each row:
///    a. Evaluate filter predicate (if any)
///    b. If filter is truthy:
///       - Delete index entries for all indexes on this table
///       - Delete row via TableStorage::delete()
///       - Increment affected count
/// 4. Return RowsAffected(count)
pub fn execute_delete<S: KVStore>(
    txn: &mut SqlTransaction<S>,
    catalog: &Catalog,
    table: &str,
    filter: Option<&TypedExpr>,
) -> Result<ExecutionResult, ExecutorError>;
```

### Query Executor

```rust
// executor/query/mod.rs

/// Execute a query plan (SELECT).
///
/// Recursively executes the plan tree:
/// - Scan → scan rows from table
/// - Filter → filter rows by predicate
/// - Sort → sort rows by expressions
/// - Limit → apply limit/offset
///
/// Returns Query(QueryResult) with columns and rows.
pub fn execute_query<S: KVStore>(
    txn: &mut SqlTransaction<S>,
    catalog: &Catalog,
    plan: &LogicalPlan,
) -> Result<ExecutionResult, ExecutorError>;

// executor/query/scan.rs

/// Execute Scan plan.
///
/// 1. Resolve table metadata and table_id
/// 2. Scan all rows via TableStorage::scan() (row_id ascending order)
/// 3. Apply projection (All or Columns)
/// 4. Return Vec<Row> where Row = (row_id, Vec<SqlValue>)
pub fn execute_scan<S: KVStore>(
    txn: &mut SqlTransaction<S>,
    catalog: &Catalog,
    table: &str,
    projection: &Projection,
) -> Result<Vec<Row>, ExecutorError>;

// executor/query/filter.rs

/// Execute Filter plan.
///
/// 1. Execute input plan to get rows
/// 2. For each row:
///    a. Evaluate predicate in EvalContext
///    b. If is_truthy(result), keep row
/// 3. Return filtered rows
pub fn execute_filter<S: KVStore>(
    input_rows: Vec<Row>,
    predicate: &TypedExpr,
) -> Result<Vec<Row>, ExecutorError>;

// executor/query/sort.rs

/// Execute Sort plan.
///
/// 1. Execute input plan to get rows
/// 2. Sort rows by SortExpr list:
///    - Evaluate each sort expression
///    - Compare using SqlValue::partial_cmp (NULLs last/first based on direction)
///    - Apply ASC/DESC
/// 3. Return sorted rows
pub fn execute_sort<S: KVStore>(
    input_rows: Vec<Row>,
    order_by: &[SortExpr],
) -> Result<Vec<Row>, ExecutorError>;

// executor/query/limit.rs

/// Execute Limit plan.
///
/// 1. Execute input plan to get rows
/// 2. Apply offset (skip first N rows)
/// 3. Apply limit (take at most M rows)
/// 4. Return limited rows
pub fn execute_limit<S: KVStore>(
    input_rows: Vec<Row>,
    limit: Option<u64>,
    offset: Option<u64>,
) -> Result<Vec<Row>, ExecutorError>;
```

### ID Generators

```rust
// catalog/id_generator.rs (extension to existing Catalog)

impl Catalog {
    /// Allocate a new unique table_id.
    /// Persisted in catalog storage, monotonically increasing.
    pub fn allocate_table_id(&mut self) -> u32;

    /// Allocate a new unique index_id.
    /// Persisted in catalog storage, monotonically increasing.
    pub fn allocate_index_id(&mut self) -> u32;
}

// storage/row_id.rs (extension to TableStorage)

impl<'txn, 'store, T: KVTransaction> TableStorage<'txn, 'store, T> {
    /// Allocate a new unique row_id for this table.
    /// Persisted per-table, monotonically increasing.
    pub fn allocate_row_id(&mut self) -> Result<u64, StorageError>;
}
```

### Reference: PK/Unique Constraint Strategies (Other DBs)

- **TiDB**: Unique/PK をセカンダリインデックスキーにエンコードし、2PC の prewrite で重複検査。悲観/楽観で遅延チェックを切替可。パーティション跨ぎは tableID をプレフィックスに持つグローバルインデックスで一意性を維持。
- **CockroachDB**: すべての Unique を「ユニークセカンダリインデックス＋値に PK 埋め込み」で担保し、インデックス backfill でも重複を検出してスキーマ変更を失敗・ロールバック。
- **YugabyteDB (YSQL)**: PostgreSQL 互換で Unique/PK は自動でユニークインデックス化。DocDB では `ybctid`（PK エンコード）をインデックス値に含めて分散下でも一意性を保証し、コレーション列はソートキー＋元文字列の両方を保持して比較と一意性を両立。

#### Pros/Cons (for reference)

- **TiDB**  
  - Pros: 遅延チェックでレイテンシを抑えられ、グローバルインデックスでパーティションを跨いでも一意性を維持。クラスタ化 PK で範囲アクセスが高速。  
  - Cons: 遅延チェックはコミット時エラーになりやすくリトライ負荷が増える。グローバルインデックス/クラスタ化 PK のメタ管理が複雑でオーバーヘッド大。楽観/悲観で挙動差分があり運用理解が必要。
- **CockroachDB**  
  - Pros: 「ユニークインデックス＋PK 埋め込み」でシンプルかつ一貫。backfill でも重複を検出して安全にロールバック可能。  
  - Cons: 大規模テーブルでの backfill/検証が重く、ユニークインデックス更新が書き込みボトルネックになりやすい。
- **YugabyteDB (YSQL)**  
  - Pros: PostgreSQL 互換でアプリ移行が容易。DocDB の `ybctid` により分散でも一意性を維持し、文字列コレーション付き PK/Unique も正しく比較できる。  
  - Cons: 互換性維持のためインデックス再構築コストが高い。コレーション列はソートキー＋元文字列の二重保持でストレージ増、ICU 変更時に再構築リスク。

##### Detailed Findings

- **TiDB**  
  - Unique/PK は TiKV のインデックスキーで担保。2PC の prewrite フェーズで `PresumeKeyNotExists` を用いた重複チェックを行い、悲観/楽観で遅延チェック可（`docs/design/2022-08-04-pessimistic-lazy-constraint-check.md`）。  
  - クラスタ化 PK はテーブルデータ自体を PK でソート保存し、セカンダリユニークインデックスはキーにハンドル（PK）を埋め込み、一意性をキー単位で検証（`docs/design/2020-05-08-cluster-index.md`）。  
  - パーティションテーブルはグローバルインデックスを `tableID` プレフィックスで保持し、全パーティション一意性を保証（`docs/design/2020-08-04-global-index.md`）。  
  - 書き込み経路はインデックスごとにロック/検査を行うため、ホットユニークキーではスループットが下がりやすい。

- **CockroachDB**  
  - すべての Unique は「ユニークセカンダリインデックス＋値に PK を埋め込む」形式で、NULL を含む場合も PK でユニーク性を確定させるエンコード（`docs/tech-notes/encoding.md`）。  
  - インデックス backfill 時も重複検出を行い、ユニーク違反があればスキーマ変更を失敗・ロールバック（`docs/tech-notes/index-backfill.md`）。  
  - 明快なモデルだが、大規模 backfill やユニークインデックス多用時は書き込み I/O が増大。

- **YugabyteDB (YSQL)**  
  - PostgreSQL 互換で、Unique/PK 定義時にユニークインデックスを自動作成。DocDB では `ybctid`（PK エンコード）をインデックス値に含め、分散環境でもキーの一意性を保証。  
  - コレーション付き列はソートキーと元文字列の二重保存で比較と一意性を両立（`architecture/design/ysql-collation-support.md` など）。  
  - Online index backfill でもユニーク違反を検出し、CREATE INDEX を中断・清掃するフローが定義されている（`architecture/design/online-index-backfill.md`）。  
  - 互換性維持のため再構築コストが高く、ICU バージョン差異による再作成リスクがある。

---

## Vector SQL 詳細仕様 (v0.3.0 に統合済み)

> 以下は旧 v0.1.3 Vector SQL の仕様。v0.3.0 として crates.io に公開済み。

### Planned Functions

```rust
// executor/evaluator/functions.rs (v0.1.3)

/// Evaluate vector_similarity function.
///
/// vector_similarity(vec1, vec2, metric) → Float
/// - metric: 'cosine' | 'l2' | 'inner'
/// - Validates dimension match
/// - Returns similarity score
pub fn eval_vector_similarity(
    vec1: &[f32],
    vec2: &[f32],
    metric: VectorMetric,
) -> Result<SqlValue, EvaluationError>;

// executor/query/vector_sort.rs (v0.1.3)

/// Optimized Top-K vector search.
///
/// ORDER BY vector_similarity(...) DESC LIMIT K
/// - Uses heap-based selection for O(n log k) instead of O(n log n)
pub fn execute_vector_topk<S: KVStore>(
    input_rows: Vec<Row>,
    similarity_expr: &TypedExpr,
    k: u64,
) -> Result<Vec<Row>, ExecutorError>;
```

---

## v0.4.0 Embedded Integration ⏳ 予定

> 旧 v0.1.4。詳細仕様は `.spec-workflow/specs/alopex-sql-v0.4.0/requirements.md` を参照。

### Planned APIs

```rust
// alopex-embedded/src/database.rs (v0.4.0)

impl Database {
    /// Execute a SQL statement and return the result.
    ///
    /// # Example
    /// ```
    /// let result = db.execute_sql("SELECT * FROM users WHERE id = 1")?;
    /// match result {
    ///     ExecutionResult::Query(qr) => {
    ///         for row in qr.rows {
    ///             println!("{:?}", row);
    ///         }
    ///     }
    ///     _ => {}
    /// }
    /// ```
    pub fn execute_sql(&self, sql: &str) -> Result<ExecutionResult, Error>;
}

// alopex-embedded/src/transaction.rs (v0.4.0)

impl Transaction<'_> {
    /// Execute a SQL statement within this transaction.
    ///
    /// Multiple SQL statements share the same transaction context.
    pub fn execute_sql(&mut self, sql: &str) -> Result<ExecutionResult, Error>;
}
```

---

## v0.5.0 GROUP BY / Aggregation ⏳ 予定

> 旧 v0.2.0。対応 Alopex DB: v0.5

### New Keywords (Reserved)

```
GROUP, BY, HAVING, COUNT, SUM, AVG, MIN, MAX
```

### New Syntax

```sql
SELECT [aggregate_function | column], ...
    FROM table
    [WHERE condition]
    GROUP BY column [, column ...]
    [HAVING aggregate_condition]
    [ORDER BY ...]
    [LIMIT ...];
```

### Aggregate Functions

```rust
// executor/evaluator/aggregate.rs (v0.5.0)

/// Aggregate function types
pub enum AggregateFunction {
    Count,      // COUNT(*) or COUNT(column)
    CountStar,  // COUNT(*) - includes NULLs
    Sum,        // SUM(column)
    Avg,        // AVG(column)
    Min,        // MIN(column)
    Max,        // MAX(column)
}

/// Aggregate accumulator state
pub trait Accumulator {
    fn update(&mut self, value: &SqlValue);
    fn finalize(&self) -> SqlValue;
    fn merge(&mut self, other: &Self);
}

/// Create accumulator for aggregate function
pub fn create_accumulator(func: AggregateFunction) -> Box<dyn Accumulator>;

// Concrete accumulators
pub struct CountAccumulator { count: u64 }
pub struct SumAccumulator { sum: Option<f64> }
pub struct AvgAccumulator { sum: f64, count: u64 }
pub struct MinAccumulator { min: Option<SqlValue> }
pub struct MaxAccumulator { max: Option<SqlValue> }
```

### New LogicalPlan Variant

```rust
// planner/logical_plan.rs (v0.5.0 extension)

pub enum LogicalPlan {
    // ... existing variants ...

    /// Aggregate operation (GROUP BY)
    Aggregate {
        /// Input plan to aggregate
        input: Box<LogicalPlan>,
        /// GROUP BY expressions
        group_by: Vec<TypedExpr>,
        /// Aggregate expressions (COUNT, SUM, etc.)
        aggregates: Vec<AggregateExpr>,
        /// Optional HAVING filter
        having: Option<TypedExpr>,
    },
}

pub struct AggregateExpr {
    pub function: AggregateFunction,
    pub arg: Option<Box<TypedExpr>>,  // None for COUNT(*)
    pub distinct: bool,                // COUNT(DISTINCT col)
    pub alias: Option<String>,
}
```

### Query Executor Extension

```rust
// executor/query/aggregate.rs (v0.5.0)

/// Execute GROUP BY aggregation.
///
/// 1. Scan input rows
/// 2. Group rows by GROUP BY key
/// 3. For each group: apply aggregate accumulators
/// 4. Apply HAVING filter (if any)
/// 5. Return aggregated results
pub fn execute_aggregate<S: KVStore>(
    input_rows: Vec<Row>,
    group_by: &[TypedExpr],
    aggregates: &[AggregateExpr],
    having: Option<&TypedExpr>,
) -> Result<Vec<Row>, ExecutorError>;
```

---

## v0.5.1 次世代検索インデックス基盤 ⏳ 予定

> 旧 v0.2.1。対応 Alopex DB: v0.5

### New Index Types

```sql
-- SHA-256 based content-addressable index
CREATE INDEX idx_content ON documents (content) USING HASH;

-- SimHash for near-duplicate detection
CREATE INDEX idx_simhash ON documents (text) USING SIMHASH;

-- UUIDv7 time-ordered index
CREATE INDEX idx_uuid ON events (id) USING UUIDV7;
```

### New Functions

```rust
// executor/evaluator/functions/hash.rs (v0.5.1)

/// SHA-256 hash function
pub fn eval_sha256(value: &SqlValue) -> Result<SqlValue, EvaluationError>;

/// SimHash for locality-sensitive hashing
pub fn eval_simhash(value: &SqlValue) -> Result<SqlValue, EvaluationError>;

/// Generate UUIDv7 (time-ordered UUID)
pub fn eval_uuidv7() -> Result<SqlValue, EvaluationError>;

/// Hamming distance for SimHash comparison
pub fn eval_hamming_distance(a: &SqlValue, b: &SqlValue) -> Result<SqlValue, EvaluationError>;
```

---

## v0.5.2 キャッシュ・メモリ管理 ⏳ 予定

> 旧 v0.2.2。対応 Alopex DB: v0.5

### New System Functions

```rust
// executor/evaluator/functions/system.rs (v0.5.2)

/// Get current memory usage statistics
pub fn eval_memory_stats() -> Result<SqlValue, EvaluationError>;

/// Get I/O statistics
pub fn eval_io_stats() -> Result<SqlValue, EvaluationError>;

/// Clear query cache
pub fn eval_clear_cache() -> Result<SqlValue, EvaluationError>;
```

### New PRAGMA Commands

```sql
PRAGMA cache_size = 1024;        -- Set cache size in pages
PRAGMA memory_limit = '100MB';   -- Set memory limit
PRAGMA io_stats;                 -- Show I/O statistics
```

---

## v0.6.0 JOIN Support ⏳ 予定

> 旧 v0.3.0。対応 Alopex DB: v0.6

### New Keywords (Reserved)

```
JOIN, LEFT, RIGHT, INNER, OUTER, FULL, CROSS, ON, NATURAL, USING
```

### New Syntax

```sql
SELECT ...
    FROM table1
    [INNER | LEFT | RIGHT | FULL] JOIN table2 ON condition
    [WHERE ...]
    ...;

-- Shorthand
SELECT ... FROM t1, t2 WHERE t1.id = t2.fk_id;  -- implicit CROSS JOIN with filter
SELECT ... FROM t1 NATURAL JOIN t2;              -- join on common column names
SELECT ... FROM t1 JOIN t2 USING (common_col);   -- join on specific common column
```

### New LogicalPlan Variant

```rust
// planner/logical_plan.rs (v0.6.0 extension)

pub enum LogicalPlan {
    // ... existing variants ...

    /// JOIN operation
    Join {
        /// Left input
        left: Box<LogicalPlan>,
        /// Right input
        right: Box<LogicalPlan>,
        /// Join type
        join_type: JoinType,
        /// Join condition (ON clause)
        condition: Option<TypedExpr>,
        /// Using columns (USING clause)
        using: Option<Vec<String>>,
    },
}

pub enum JoinType {
    Inner,      // INNER JOIN (default)
    Left,       // LEFT OUTER JOIN
    Right,      // RIGHT OUTER JOIN
    Full,       // FULL OUTER JOIN
    Cross,      // CROSS JOIN (cartesian product)
}
```

### Join Executor

```rust
// executor/query/join.rs (v0.6.0)

/// Execute JOIN operation.
///
/// Algorithms:
/// - Nested Loop Join (default, small tables)
/// - Hash Join (large tables, equi-join)
pub fn execute_join<S: KVStore>(
    left_rows: Vec<Row>,
    right_rows: Vec<Row>,
    join_type: JoinType,
    condition: Option<&TypedExpr>,
) -> Result<Vec<Row>, ExecutorError>;

/// Nested loop join implementation
pub fn nested_loop_join(
    left: &[Row],
    right: &[Row],
    condition: &TypedExpr,
    join_type: JoinType,
) -> Result<Vec<Row>, ExecutorError>;

/// Hash join implementation (for equi-joins)
pub fn hash_join(
    left: &[Row],
    right: &[Row],
    left_key: usize,
    right_key: usize,
    join_type: JoinType,
) -> Result<Vec<Row>, ExecutorError>;
```

---

## v0.7.0 WASM Parser ⏳ 予定

> 旧 v0.4.0。対応 Alopex DB: v0.7

### Target

```
wasm32-unknown-unknown
```

### Scope (Read-Only SQL)

```rust
// alopex-sql-wasm/src/lib.rs (v0.7.0)

/// WASM-compatible SQL parser and executor
/// Supports read-only operations only
#[wasm_bindgen]
pub struct WasmSqlEngine {
    // ... lightweight executor for queries
}

#[wasm_bindgen]
impl WasmSqlEngine {
    /// Parse SQL and return AST as JSON
    pub fn parse(&self, sql: &str) -> Result<JsValue, JsError>;

    /// Execute SELECT query on provided data
    pub fn query(&self, sql: &str, data: &JsValue) -> Result<JsValue, JsError>;
}
```

### Supported Operations

```
- SELECT (with all clauses)
- Built-in scalar functions
- Expression evaluation
```

### NOT Supported (WASM)

```
- DDL (CREATE, DROP, ALTER)
- DML (INSERT, UPDATE, DELETE)
- Transactions
```

---

## v0.8.0 Subquery ⏳ 予定

> 旧 v0.5.0。対応 Alopex DB: v0.7

### New Keywords (Reserved)

```
EXISTS, ANY, SOME, ALL
```

### New Syntax

```sql
-- Scalar subquery
SELECT name, (SELECT COUNT(*) FROM orders WHERE user_id = u.id) AS order_count
    FROM users u;

-- WHERE subquery
SELECT * FROM users WHERE id IN (SELECT user_id FROM orders);

-- EXISTS subquery
SELECT * FROM users u WHERE EXISTS (SELECT 1 FROM orders WHERE user_id = u.id);

-- FROM subquery (derived table)
SELECT * FROM (SELECT id, name FROM users WHERE active) AS active_users;
```

### New TypedExprKind Variants

```rust
// planner/typed_expr.rs (v0.8.0 extension)

pub enum TypedExprKind {
    // ... existing variants ...

    /// Scalar subquery (returns single value)
    ScalarSubquery(Box<LogicalPlan>),

    /// IN subquery
    InSubquery {
        expr: Box<TypedExpr>,
        subquery: Box<LogicalPlan>,
        negated: bool,
    },

    /// EXISTS subquery
    Exists {
        subquery: Box<LogicalPlan>,
        negated: bool,
    },

    /// Quantified comparison (ANY/ALL)
    Quantified {
        expr: Box<TypedExpr>,
        op: BinaryOp,
        quantifier: Quantifier,  // Any, All
        subquery: Box<LogicalPlan>,
    },
}

pub enum Quantifier {
    Any,   // = ANY, < ANY, etc.
    All,   // = ALL, < ALL, etc.
}
```

### Subquery Executor

```rust
// executor/query/subquery.rs (v0.8.0)

/// Execute scalar subquery
pub fn execute_scalar_subquery<S: KVStore>(
    txn: &mut SqlTransaction<S>,
    catalog: &Catalog,
    subquery: &LogicalPlan,
) -> Result<SqlValue, ExecutorError>;

/// Execute IN subquery
pub fn execute_in_subquery<S: KVStore>(
    txn: &mut SqlTransaction<S>,
    catalog: &Catalog,
    value: &SqlValue,
    subquery: &LogicalPlan,
    negated: bool,
) -> Result<bool, ExecutorError>;

/// Execute EXISTS subquery
pub fn execute_exists<S: KVStore>(
    txn: &mut SqlTransaction<S>,
    catalog: &Catalog,
    subquery: &LogicalPlan,
) -> Result<bool, ExecutorError>;
```

---

## v0.9.0+ Distributed Query (Chirps 依存) ⏳ 予定

> 旧 v0.6.0+。対応 Alopex DB: v0.8+

### Version Roadmap

| Version | Feature | Chirps Dependency |
|---------|---------|-------------------|
| v0.9.0 | Distributed Query Planner | Chirps v0.3 |
| v0.10.0 | Raft-aware Executor | Chirps v0.6 |
| v0.11.0 | Multi-Raft Query | Chirps v0.7 |
| v0.12.0 | Federation Query | Chirps v0.8 |
| v1.0.0 | Query Optimizer | - |

### New Concepts (v0.9.0+)

```rust
// planner/distributed.rs (v0.9.0+)

/// Distributed query plan
pub enum DistributedPlan {
    /// Execute on single node
    Local(LogicalPlan),

    /// Scatter query to multiple shards, gather results
    ScatterGather {
        scatter: Box<LogicalPlan>,
        gather: GatherType,
        shards: Vec<ShardId>,
    },

    /// Execute on specific shard
    Remote {
        plan: Box<LogicalPlan>,
        target: ShardId,
    },
}

pub enum GatherType {
    Union,          // Simple union of results
    MergeSort,      // Merge sorted results
    Aggregate,      // Aggregate across shards
}
```

---

## Reserved Keywords Summary

### Currently Implemented (v0.3.0 - crates.io 公開済み)

```
-- DDL
CREATE, DROP, TABLE, INDEX, IF, EXISTS, NOT, NULL, PRIMARY, KEY,
UNIQUE, DEFAULT, USING, WITH

-- DML
SELECT, INSERT, UPDATE, DELETE, FROM, WHERE, INTO, VALUES, SET,
ORDER, BY, ASC, DESC, LIMIT, OFFSET, DISTINCT, AS, NULLS, FIRST, LAST

-- Types
INTEGER, INT, BIGINT, FLOAT, DOUBLE, TEXT, BLOB, BOOLEAN, BOOL,
TIMESTAMP, VECTOR

-- Operators
AND, OR, NOT, IN, BETWEEN, LIKE, IS, ESCAPE, TRUE, FALSE

-- Index
BTREE, HNSW, COSINE, L2, INNER

-- Functions
CAST, NOW
```

### Reserved for Future (Not Yet Implemented)

```
-- v0.5.0 Aggregation
GROUP, HAVING, COUNT, SUM, AVG, MIN, MAX

-- v0.6.0 JOIN
JOIN, LEFT, RIGHT, OUTER, FULL, CROSS, ON, NATURAL

-- v0.8.0 Subquery
EXISTS, ANY, SOME, ALL, WITH, RECURSIVE

-- v0.9.0+ Advanced
UNION, INTERSECT, EXCEPT,
OVER, PARTITION, WINDOW,
BEGIN, COMMIT, ROLLBACK, TRANSACTION, SAVEPOINT,
CASE, WHEN, THEN, ELSE, END,
TRIGGER, VIEW, FOREIGN, REFERENCES, CASCADE,
RETURNING, CONFLICT
```

---

## Built-in Functions Roadmap

> SQLite/PostgreSQL互換を目指し、両DBで共通する関数を優先実装。
> 詳細は `reference/sqlite-sql-reference.md`, `reference/postgresql-functions-reference.md` を参照。

### v0.3.0 (Executor - crates.io 公開済み)

```
-- 実装済み
CAST(expr AS type)
NOW()
```

### v0.3.0 (Vector SQL - crates.io 公開済み)

```
-- ベクトル演算
vector_distance(vec1, vec2, metric)      -- 距離計算 (cosine/l2/inner)
vector_similarity(vec1, vec2, metric)    -- 類似度計算
vector_dims(vec)                         -- 次元数取得
vector_norm(vec)                         -- ノルム計算
```

### v0.5.0 (Aggregation)

```
-- 基本集約関数 (SQLite/PostgreSQL共通)
COUNT(*)                    -- 全行カウント
COUNT(expr)                 -- 非NULL値カウント
COUNT(DISTINCT expr)        -- ユニーク値カウント
SUM(expr)                   -- 合計
AVG(expr)                   -- 平均
MIN(expr)                   -- 最小値
MAX(expr)                   -- 最大値

-- 拡張集約関数 (PostgreSQL互換)
TOTAL(expr)                 -- 合計 (SQLite互換: NULLで0.0を返す)
GROUP_CONCAT(expr)          -- 文字列連結 (SQLite)
STRING_AGG(expr, delim)     -- 文字列連結 (PostgreSQL)
```

### v0.5.1 (Hash/UUID Index)

```
-- ハッシュ関数
SHA256(value)               -- SHA-256ハッシュ (bytea返却)
MD5(value)                  -- MD5ハッシュ (text返却, PostgreSQL互換)
SIMHASH(value)              -- SimHash (類似検索用)
HAMMING_DISTANCE(a, b)      -- ハミング距離

-- UUID関数
GEN_RANDOM_UUID()           -- ランダムUUID v4 (PostgreSQL互換)
UUIDV7()                    -- 時系列UUID v7

-- エンコード関数
HEX(value)                  -- 16進数エンコード (SQLite互換)
UNHEX(value)                -- 16進数デコード (SQLite互換)
ENCODE(bytea, format)       -- エンコード (PostgreSQL互換: base64/hex)
DECODE(text, format)        -- デコード (PostgreSQL互換)
```

### v0.5.3 (Core Scalar Functions)

```
-- 数値関数 (SQLite/PostgreSQL共通)
ABS(x)                      -- 絶対値
SIGN(x)                     -- 符号 (-1, 0, 1)
ROUND(x)                    -- 四捨五入
ROUND(x, n)                 -- 小数点n桁で四捨五入
FLOOR(x)                    -- 切り捨て
CEIL(x) / CEILING(x)        -- 切り上げ
TRUNC(x)                    -- ゼロ方向切り捨て
TRUNC(x, n)                 -- 小数点n桁で切り捨て
MOD(x, y)                   -- 剰余
POWER(x, y) / POW(x, y)     -- べき乗
SQRT(x)                     -- 平方根
EXP(x)                      -- e^x
LN(x)                       -- 自然対数
LOG(x)                      -- 自然対数 (SQLite) / 常用対数 (PostgreSQL)
LOG10(x)                    -- 常用対数
LOG(b, x)                   -- 底bの対数 (PostgreSQL)
RANDOM()                    -- 乱数

-- 三角関数 (PostgreSQL互換, SQLite 3.35+)
SIN(x), COS(x), TAN(x)      -- 正弦/余弦/正接 (ラジアン)
ASIN(x), ACOS(x), ATAN(x)   -- 逆三角関数
ATAN2(y, x)                 -- 2引数逆正接
DEGREES(x)                  -- ラジアン→度
RADIANS(x)                  -- 度→ラジアン
PI()                        -- 円周率

-- 文字列関数 (SQLite/PostgreSQL共通)
LENGTH(s)                   -- 文字数
CHAR_LENGTH(s)              -- 文字数 (PostgreSQL標準SQL)
OCTET_LENGTH(s)             -- バイト数
UPPER(s)                    -- 大文字変換
LOWER(s)                    -- 小文字変換
INITCAP(s)                  -- 各単語先頭大文字 (PostgreSQL)
SUBSTR(s, start, len)       -- 部分文字列 (SQLite)
SUBSTRING(s FROM start FOR len)  -- 部分文字列 (PostgreSQL標準SQL)
LEFT(s, n)                  -- 左からn文字 (PostgreSQL)
RIGHT(s, n)                 -- 右からn文字 (PostgreSQL)
TRIM(s)                     -- 両端空白除去
LTRIM(s)                    -- 左空白除去
RTRIM(s)                    -- 右空白除去
TRIM(chars FROM s)          -- 指定文字除去 (PostgreSQL)
REPLACE(s, from, to)        -- 置換
INSTR(s, sub)               -- 位置検索 (SQLite)
POSITION(sub IN s)          -- 位置検索 (PostgreSQL標準SQL)
STRPOS(s, sub)              -- 位置検索 (PostgreSQL)
CONCAT(s1, s2, ...)         -- 連結 (NULL無視)
CONCAT_WS(sep, s1, s2, ...) -- 区切り文字付き連結
REPEAT(s, n)                -- 繰り返し
REVERSE(s)                  -- 逆順
LPAD(s, len, fill)          -- 左パディング
RPAD(s, len, fill)          -- 右パディング
SPLIT_PART(s, delim, n)     -- 分割取得 (PostgreSQL)

-- 正規表現関数 (PostgreSQL)
REGEXP_REPLACE(s, pattern, replacement)
REGEXP_MATCH(s, pattern)
REGEXP_MATCHES(s, pattern, flags)

-- パターンマッチング演算子
LIKE                        -- パターンマッチ (SQLite/PostgreSQL)
ILIKE                       -- 大文字小文字無視 (PostgreSQL)
GLOB                        -- Unixグロブ (SQLite)
SIMILAR TO                  -- SQL正規表現 (PostgreSQL)

-- 条件関数 (SQLite/PostgreSQL共通)
COALESCE(v1, v2, ...)       -- 最初の非NULL値
NULLIF(v1, v2)              -- 等しければNULL
IFNULL(v1, v2)              -- NULLなら代替値 (SQLite)
IIF(cond, then, else)       -- 条件分岐 (SQLite 3.32+)
GREATEST(v1, v2, ...)       -- 最大値 (PostgreSQL)
LEAST(v1, v2, ...)          -- 最小値 (PostgreSQL)

-- 型情報関数
TYPEOF(x)                   -- 型名 (SQLite)
PG_TYPEOF(x)                -- 型名 (PostgreSQL)
QUOTE(x)                    -- SQLリテラル形式 (SQLite)
```

### v0.5.4 (Date/Time Functions)

```
-- 現在日時 (SQLite/PostgreSQL共通)
NOW()                       -- 現在のタイムスタンプ (PostgreSQL)
CURRENT_TIMESTAMP           -- 現在のタイムスタンプ (標準SQL)
CURRENT_DATE                -- 現在の日付
CURRENT_TIME                -- 現在の時刻

-- 日時抽出 (PostgreSQL互換)
EXTRACT(field FROM ts)      -- フィールド抽出 (year/month/day/hour/minute/second/epoch等)
DATE_PART('field', ts)      -- フィールド抽出 (PostgreSQL関数形式)

-- 日時構築 (PostgreSQL互換)
MAKE_DATE(year, month, day)
MAKE_TIME(hour, min, sec)
MAKE_TIMESTAMP(y, m, d, h, min, sec)
MAKE_INTERVAL(...)

-- 日時変換
DATE(ts)                    -- タイムスタンプ→日付 (SQLite)
TIME(ts)                    -- タイムスタンプ→時刻 (SQLite)
DATETIME(ts, modifier, ...) -- 日時構築/変換 (SQLite)
STRFTIME(format, ts)        -- 日時フォーマット (SQLite)
TO_CHAR(ts, format)         -- 日時フォーマット (PostgreSQL)
TO_TIMESTAMP(text, format)  -- 文字列→タイムスタンプ (PostgreSQL)
TO_DATE(text, format)       -- 文字列→日付 (PostgreSQL)

-- 日時演算
DATE_TRUNC('field', ts)     -- 切り捨て (PostgreSQL)
AGE(ts1, ts2)               -- 2日時の差 (PostgreSQL)
DATE_ADD(ts, interval)      -- 日時加算
DATE_SUB(ts, interval)      -- 日時減算
JULIANDAY(ts)               -- ユリウス日 (SQLite)
UNIXEPOCH(ts)               -- Unix時刻 (SQLite 3.38+)
```

### v0.6.0+ (Advanced Functions)

```
-- ウィンドウ関数 (PostgreSQL互換, v0.6.0)
ROW_NUMBER() OVER (...)     -- 連番
RANK() OVER (...)           -- 順位 (同値で同順位、次は飛ぶ)
DENSE_RANK() OVER (...)     -- 密順位 (同値で同順位、次は連続)
NTILE(n) OVER (...)         -- n分割グループ番号
LAG(expr, offset, default) OVER (...)   -- N行前の値
LEAD(expr, offset, default) OVER (...)  -- N行後の値
FIRST_VALUE(expr) OVER (...) -- フレーム内最初の値
LAST_VALUE(expr) OVER (...)  -- フレーム内最後の値
NTH_VALUE(expr, n) OVER (...) -- フレーム内N番目の値
SUM(...) OVER (...)         -- ウィンドウ集約
AVG(...) OVER (...)
COUNT(...) OVER (...)

-- JSON関数 (v0.6.1)
-- SQLite互換
JSON(text)                  -- JSON検証・正規化
JSON_VALID(text)            -- JSON有効性チェック
JSON_TYPE(json)             -- 型取得
JSON_EXTRACT(json, path)    -- 値抽出
JSON_OBJECT(key, val, ...)  -- オブジェクト作成
JSON_ARRAY(val, ...)        -- 配列作成
JSON_INSERT(json, path, val, ...)  -- 挿入
JSON_REPLACE(json, path, val, ...) -- 置換
JSON_SET(json, path, val, ...)     -- 設定
JSON_REMOVE(json, path, ...)       -- 削除
JSON_ARRAY_LENGTH(json)     -- 配列長
JSON_EACH(json)             -- 要素展開
JSON_TREE(json)             -- 全要素展開
JSON_GROUP_ARRAY(expr)      -- 集約→配列
JSON_GROUP_OBJECT(key, val) -- 集約→オブジェクト

-- PostgreSQL互換
json -> key                 -- キーでJSON取得
json ->> key                -- キーでテキスト取得
json #> path                -- パスでJSON取得
json #>> path               -- パスでテキスト取得
JSONB_SET(target, path, new_value)
JSONB_INSERT(target, path, new_value)
JSONB_BUILD_OBJECT(...)
JSONB_BUILD_ARRAY(...)
JSONB_AGG(expr)
JSONB_OBJECT_AGG(key, val)

-- 配列関数 (PostgreSQL, v0.6.2)
ARRAY[...]                  -- 配列リテラル
ARRAY_AGG(expr)             -- 配列集約
ARRAY_APPEND(arr, elem)     -- 末尾追加
ARRAY_PREPEND(elem, arr)    -- 先頭追加
ARRAY_CAT(arr1, arr2)       -- 連結
ARRAY_REMOVE(arr, elem)     -- 要素削除
ARRAY_REPLACE(arr, from, to) -- 要素置換
ARRAY_LENGTH(arr, dim)      -- 長さ
ARRAY_POSITION(arr, elem)   -- 位置検索
ARRAY_POSITIONS(arr, elem)  -- 全位置検索
UNNEST(arr)                 -- 行展開
STRING_TO_ARRAY(s, delim)   -- 文字列→配列
ARRAY_TO_STRING(arr, delim) -- 配列→文字列

-- 集合生成関数 (PostgreSQL, v0.6.2)
GENERATE_SERIES(start, stop)         -- 数列生成
GENERATE_SERIES(start, stop, step)   -- ステップ付き
GENERATE_SERIES(start, stop, interval) -- 日時系列

-- 統計集約関数 (PostgreSQL, v0.7.0)
VARIANCE(expr) / VAR_SAMP(expr)   -- 標本分散
VAR_POP(expr)                      -- 母分散
STDDEV(expr) / STDDEV_SAMP(expr)  -- 標本標準偏差
STDDEV_POP(expr)                   -- 母標準偏差
COVAR_SAMP(Y, X)                   -- 標本共分散
COVAR_POP(Y, X)                    -- 母共分散
CORR(Y, X)                         -- 相関係数
PERCENTILE_CONT(fraction) WITHIN GROUP (ORDER BY expr)  -- 連続パーセンタイル
PERCENTILE_DISC(fraction) WITHIN GROUP (ORDER BY expr)  -- 離散パーセンタイル
MODE() WITHIN GROUP (ORDER BY expr)  -- 最頻値

-- 全文検索関数 (PostgreSQL, v0.8.0+)
TO_TSVECTOR(config, document)   -- 文書→tsvector
TO_TSQUERY(config, query)       -- クエリ→tsquery
PLAINTO_TSQUERY(config, query)  -- プレーンテキスト→tsquery
WEBSEARCH_TO_TSQUERY(config, query)  -- Web検索形式
TS_RANK(tsvector, tsquery)      -- 関連度スコア
TS_HEADLINE(config, document, query)  -- ハイライト

-- ネットワークアドレス関数 (PostgreSQL, v0.9.0+)
HOST(inet)                  -- ホスト部分
NETWORK(inet)               -- ネットワーク部
NETMASK(inet)               -- ネットマスク
MASKLEN(inet)               -- マスク長
BROADCAST(inet)             -- ブロードキャスト
```

### Functions Compatibility Matrix

| カテゴリ | SQLite | PostgreSQL | alopex-sql Target |
|---------|--------|------------|-------------------|
| 算術 | ✅ | ✅ | v0.5.3 |
| 三角関数 | ✅ (3.35+) | ✅ | v0.5.3 |
| 文字列 | ✅ | ✅ | v0.5.3 |
| 正規表現 | ❌ | ✅ | v0.5.3 (PostgreSQL互換) |
| 日付・時刻 | ✅ | ✅ | v0.5.4 |
| 条件 | ✅ | ✅ | v0.5.3 |
| 集約 | ✅ | ✅ | v0.5.0 |
| ウィンドウ | ✅ | ✅ | v0.6.0 |
| JSON | ✅ | ✅ | v0.6.1 |
| 配列 | ❌ | ✅ | v0.6.2 (PostgreSQL互換) |
| 集合生成 | ❌ | ✅ | v0.6.2 (PostgreSQL互換) |
| 全文検索 | FTS5拡張 | ✅ | v0.8.0+ (PostgreSQL互換) |
| UUID | 拡張 | ✅ | v0.5.1 |
| ハッシュ | ❌ | ✅ | v0.5.1 |
| ベクトル | ❌ | 拡張 | v0.3.0 (独自・crates.io 公開済み) |

---

## Version Dependencies

> **Note (2025-12-18)**: CD ワークフロー修正により v0.3.0 が crates.io に公開済み（旧 v0.1.3 Vector SQL 相当）。
> 旧 v0.1.x は v0.3.0 に統合、旧 v0.1.4 以降は v0.4.0 以降に再番号付け。

```
┌─────────────────────────────────────────────────────────────┐
│ v0.3.0 ✅ crates.io 公開済み (旧 v0.1.0~v0.1.3 統合)        │
│   ├── Parser (Lexer + AST + DDL/DML)                        │
│   ├── Planner (Catalog + LogicalPlan)                       │
│   ├── Storage Engine (RowCodec + KeyEncoder + TxnBridge)    │
│   ├── Executor (DDL/DML)                                    │
│   └── Vector SQL (vector_similarity, Top-K)                 │
└─────────────────────────────────────────────────────────────┘
    ↓
v0.4.0 Embedded Integration (execute_sql API) ──→ Alopex DB v0.4
    ↓
v0.5.0 GROUP BY / Aggregation ──────────────────→ Alopex DB v0.5
    ↓
v0.5.1 Hash/UUID Index (SHA-256/SimHash/UUIDv7)
    ↓
v0.5.2 Cache/Memory Management
    ↓
v0.6.0 JOIN Support ────────────────────────────→ Alopex DB v0.6
    ↓
v0.7.0 WASM Parser (Read-Only)
    ↓
v0.8.0 Subquery ────────────────────────────────→ Alopex DB v0.7
    ↓
v0.9.0 Distributed Query Planner ───────────────→ Alopex DB v0.8 (Chirps v0.3)
    ↓
v0.10.0 Raft-aware Executor ────────────────────→ Alopex DB v0.9 (Chirps v0.6)
    ↓
v0.11.0 Multi-Raft Query ───────────────────────→ Alopex DB v0.10 (Chirps v0.7)
    ↓
v0.12.0 Federation Query ───────────────────────→ Alopex DB v1.0 (Chirps v0.8)
    ↓
v1.0.0 Query Optimizer (Cost-based)
```

---

## Change History

| Date | Version | Changes |
|------|---------|---------|
| 2025-12-09 | 0.1.0 | Initial creation with v0.1.2 Executor detailed spec |
| 2025-12-09 | 0.2.0 | Added v0.2.0+ roadmap with detailed function signatures and reserved keywords |
| 2025-12-09 | 0.3.0 | Comprehensive update to Built-in Functions Roadmap based on SQLite/PostgreSQL reference documents |
| 2025-12-18 | 0.4.0 | **バージョン再番号付け**: CD ワークフロー修正により v0.3.0 が crates.io に公開済み（旧 v0.1.3 Vector SQL 相当）。旧 v0.1.0~v0.1.3 は v0.3.0 に統合、旧 v0.1.4 以降は v0.4.0 以降に再番号付け。全セクションのバージョン番号を更新。 |
