# Alopex Columnar Engine 技術仕様書

**バージョン**: 1.0
**最終更新日**: 2025-12-05
**ステータス**: Draft

---

## 1. 概要

### 1.1 目的

Alopex Columnar Engineは、DuckDB/Polarsのような高速分析クエリを実現しながら、Alopexの既存KVSデータレイアウトを永続化層として活用するハイブリッドカラムナDBエンジンである。

### 1.2 設計目標

| 目標 | 指標 | 参考 |
|------|------|------|
| 高圧縮 | 40倍以上（生データ比） | Parquet/Arrow水準 |
| 高スループット | 1GB/s以上のスキャン速度 | DuckDB水準 |
| 低レイテンシ | 分析クエリ50ms以下 | InfluxDB 3水準 |
| Dual API | SQL + DataFrame | DuckDB + Polars |
| 統一永続化 | Alopex KVS上 | 独自優位性 |

### 1.3 アーキテクチャ概要

```
┌─────────────────────────────────────────────────────────────────┐
│                     User-Facing APIs                             │
│  ┌─────────────────────────┐  ┌─────────────────────────────┐  │
│  │      SQL API            │  │     DataFrame API           │  │
│  │  (DuckDB-compatible)    │  │  (Polars-compatible)        │  │
│  └───────────┬─────────────┘  └─────────────┬───────────────┘  │
│              │                              │                   │
│              └──────────────┬───────────────┘                   │
│                             │                                   │
├─────────────────────────────┼───────────────────────────────────┤
│                             ▼                                   │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │              Logical Plan Builder                          │ │
│  │  (Lazy Evaluation / Query AST)                            │ │
│  └─────────────────────────┬─────────────────────────────────┘ │
│                             │                                   │
│  ┌─────────────────────────┴─────────────────────────────────┐ │
│  │                Query Optimizer                             │ │
│  │  - Predicate Pushdown                                     │ │
│  │  - Projection Pruning                                      │ │
│  │  - Join Reordering                                         │ │
│  │  - Common Subexpression Elimination                       │ │
│  └─────────────────────────┬─────────────────────────────────┘ │
│                             │                                   │
│  ┌─────────────────────────┴─────────────────────────────────┐ │
│  │           Physical Plan Generator                          │ │
│  │  (Volcano-style → Vectorized Execution)                   │ │
│  └─────────────────────────┬─────────────────────────────────┘ │
│                             │                                   │
├─────────────────────────────┼───────────────────────────────────┤
│                             ▼                                   │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │            Vectorized Execution Engine                     │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐   │ │
│  │  │ TableScan   │  │ Filter      │  │ HashAggregate   │   │ │
│  │  │ (SIMD)      │  │ (SIMD)      │  │ (Parallel)      │   │ │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘   │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐   │ │
│  │  │ HashJoin    │  │ Sort        │  │ Window          │   │ │
│  │  │ (Parallel)  │  │ (External)  │  │ (Streaming)     │   │ │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘   │ │
│  └─────────────────────────┬─────────────────────────────────┘ │
│                             │                                   │
├─────────────────────────────┼───────────────────────────────────┤
│                             ▼                                   │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │              Columnar Storage Layer                        │ │
│  │  ┌─────────────────────────────────────────────────────┐ │ │
│  │  │  RecordBatch (Arrow-compatible in-memory format)    │ │ │
│  │  └─────────────────────────────────────────────────────┘ │ │
│  │  ┌─────────────────────────────────────────────────────┐ │ │
│  │  │  ColumnSegment (Encoded/Compressed on-disk format)  │ │ │
│  │  └─────────────────────────────────────────────────────┘ │ │
│  └─────────────────────────┬─────────────────────────────────┘ │
│                             │                                   │
├─────────────────────────────┼───────────────────────────────────┤
│                             ▼                                   │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │              Alopex KVS Persistence Layer                  │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐   │ │
│  │  │ LSM-Tree    │  │ WAL         │  │ .alopex File    │   │ │
│  │  │ MemTable    │  │ Durability  │  │ Section 0x03    │   │ │
│  │  └─────────────┘  └─────────────┘  └─────────────────┘   │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. データモデル

### 2.1 型システム

#### 2.1.1 論理型（Logical Types）

```rust
/// 論理データ型（ユーザー向け）
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DataType {
    // Numeric
    Int8,
    Int16,
    Int32,
    Int64,
    UInt8,
    UInt16,
    UInt32,
    UInt64,
    Float32,
    Float64,
    Decimal128 { precision: u8, scale: i8 },

    // Temporal
    Date32,          // days since epoch
    Date64,          // milliseconds since epoch
    Time64,          // nanoseconds since midnight
    Timestamp {
        unit: TimeUnit,
        timezone: Option<String>,
    },
    Duration(TimeUnit),
    Interval(IntervalUnit),

    // String/Binary
    Utf8,            // variable-length UTF-8
    LargeUtf8,       // large variable-length UTF-8
    Binary,          // variable-length binary
    LargeBinary,     // large variable-length binary
    FixedSizeBinary(usize),

    // Nested
    List(Box<DataType>),
    LargeList(Box<DataType>),
    FixedSizeList(Box<DataType>, usize),
    Struct(Vec<Field>),
    Map { key: Box<DataType>, value: Box<DataType> },
    Union(Vec<(i8, Field)>, UnionMode),

    // Special
    Boolean,
    Null,

    // Extension (Alopex-specific)
    Vector { dimension: usize, element: VectorElementType },
    Json,
    Uuid,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TimeUnit {
    Second,
    Millisecond,
    Microsecond,
    Nanosecond,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum VectorElementType {
    Float32,
    Float64,
    Int8,
    Binary,
}
```

#### 2.1.2 物理型（Physical Types）

Alopex KVSの既存`columnar::encoding`モジュールを拡張：

```rust
/// 物理ストレージ型（既存のLogicalTypeを拡張）
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PhysicalType {
    // 既存（alopex-core互換）
    Int64,
    Float64,
    Bool,
    Binary,
    Fixed(u16),

    // 追加：固定幅数値
    Int8,
    Int16,
    Int32,
    UInt8,
    UInt16,
    UInt32,
    UInt64,
    Float32,

    // 追加：時間系（内部的にはInt64/Int32）
    Date32,
    Date64,
    Time64,
    Timestamp,
    Duration,

    // 追加：ネスト構造
    List,
    Struct,
}
```

### 2.2 スキーマ定義

```rust
/// フィールド定義
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Field {
    pub name: String,
    pub data_type: DataType,
    pub nullable: bool,
    pub metadata: HashMap<String, String>,
}

/// テーブルスキーマ
#[derive(Clone, Debug)]
pub struct Schema {
    pub fields: Vec<Field>,
    pub metadata: HashMap<String, String>,
}

impl Schema {
    pub fn new(fields: Vec<Field>) -> Self {
        Self { fields, metadata: HashMap::new() }
    }

    pub fn field(&self, name: &str) -> Option<&Field> {
        self.fields.iter().find(|f| f.name == name)
    }

    pub fn index_of(&self, name: &str) -> Option<usize> {
        self.fields.iter().position(|f| f.name == name)
    }
}
```

---

## 3. SQL API

### 3.1 概要

PostgreSQL互換のSQL APIを提供。既存の`alopex-sql`クレート（SQLite + PostgreSQL方言）を拡張し、Alopex固有の分析機能を追加。

> **方言選択の根拠**: DuckDB/PolarsのSQLはPostgreSQL互換のため、追加方言は不要。Alopex固有拡張（ベクトル検索、カラムナストレージオプション）のみ追加する。

### 3.2 接続とセッション

```rust
/// データベース接続（PostgreSQL互換API）
pub struct Connection {
    catalog: Arc<Catalog>,
    session: SessionContext,
    config: ConnectionConfig,
}

impl Connection {
    /// インメモリデータベースを開く
    pub fn open_in_memory() -> Result<Self> {
        Self::open_with_config(ConnectionConfig::in_memory())
    }

    /// ファイルベースデータベースを開く
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        Self::open_with_config(ConnectionConfig::file(path))
    }

    /// SQLクエリを実行
    pub fn execute(&self, sql: &str) -> Result<QueryResult> {
        let plan = self.session.sql(sql)?;
        plan.collect()
    }

    /// SQLクエリを実行（遅延評価、DataFrame返却）
    pub fn query(&self, sql: &str) -> Result<LazyFrame> {
        let plan = self.session.sql(sql)?;
        Ok(LazyFrame::from_logical_plan(plan))
    }

    /// プリペアドステートメント作成
    pub fn prepare(&self, sql: &str) -> Result<PreparedStatement> {
        PreparedStatement::new(&self.session, sql)
    }

    /// トランザクション開始
    pub fn begin_transaction(&self) -> Result<Transaction> {
        Transaction::begin(&self.session)
    }
}

/// クエリ結果
pub struct QueryResult {
    schema: Arc<Schema>,
    batches: Vec<RecordBatch>,
}

impl QueryResult {
    pub fn schema(&self) -> &Schema { &self.schema }
    pub fn num_rows(&self) -> usize { self.batches.iter().map(|b| b.num_rows()).sum() }
    pub fn to_dataframe(&self) -> DataFrame { DataFrame::from_batches(self.batches.clone()) }
}
```

### 3.3 SQLダイアレクト

PostgreSQL互換のSQL構文をベースに、Alopex固有拡張を追加：

#### Alopex固有拡張
- `FLOAT[n]` / `VECTOR(n)`: ベクトル型
- `vector_distance()`: ベクトル距離計算関数
- `WITH (storage='columnar', ...)`: カラムナストレージオプション
- `COPY ... (FORMAT PARQUET|CSV)`: 外部ファイル連携

#### サポートするPostgreSQL構文

```sql
-- テーブル作成（カラムナストレージ指定）
CREATE TABLE events (
    id BIGINT PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    event_type VARCHAR,
    payload JSON,
    embedding FLOAT[384]  -- ベクトル型
) WITH (
    storage = 'columnar',
    compression = 'zstd',
    row_group_size = 100000
);

-- COPY文（高速バルクロード）
COPY events FROM 'events.parquet' (FORMAT PARQUET);
COPY events FROM 'events.csv' (FORMAT CSV, HEADER TRUE);

-- 分析クエリ
SELECT
    date_trunc('hour', timestamp) AS hour,
    event_type,
    COUNT(*) AS count,
    AVG(json_extract(payload, '$.duration')::DOUBLE) AS avg_duration
FROM events
WHERE timestamp >= '2025-01-01'
GROUP BY hour, event_type
ORDER BY hour, count DESC;

-- ウィンドウ関数
SELECT
    id,
    timestamp,
    SUM(value) OVER (
        PARTITION BY category
        ORDER BY timestamp
        ROWS BETWEEN 100 PRECEDING AND CURRENT ROW
    ) AS rolling_sum
FROM metrics;

-- CTEとサブクエリ
WITH daily_stats AS (
    SELECT date_trunc('day', timestamp) AS day, COUNT(*) AS cnt
    FROM events GROUP BY 1
)
SELECT * FROM daily_stats WHERE cnt > 1000;

-- ベクトル検索（Alopex拡張）
SELECT id, content,
       vector_distance(embedding, $1, 'cosine') AS distance
FROM documents
ORDER BY distance
LIMIT 10;
```

### 3.4 バッチ処理API

```rust
/// バッチインサート（高速バルクロード）
impl Connection {
    /// RecordBatchからの高速挿入
    pub fn insert_batch(&self, table: &str, batch: &RecordBatch) -> Result<u64> {
        let plan = InsertPlan::new(table, batch);
        self.session.execute_insert(plan)
    }

    /// イテレータからのストリーミング挿入
    pub fn insert_stream<I>(&self, table: &str, batches: I) -> Result<u64>
    where
        I: Iterator<Item = RecordBatch>,
    {
        let mut total = 0;
        for batch in batches {
            total += self.insert_batch(table, &batch)?;
        }
        Ok(total)
    }

    /// Parquet/CSVからの直接ロード
    pub fn copy_from(&self, table: &str, path: &Path, format: FileFormat) -> Result<u64> {
        let reader = format.open_reader(path)?;
        self.insert_stream(table, reader.batches())
    }
}
```

---

## 4. DataFrame API

### 4.1 概要

PolarsライクなLazy/Eager評価をサポートするDataFrame API。

### 4.2 Eager DataFrame

```rust
/// Eager評価DataFrame（即時実行）
#[derive(Clone)]
pub struct DataFrame {
    schema: Arc<Schema>,
    batches: Vec<RecordBatch>,
}

impl DataFrame {
    /// 新規作成
    pub fn new(schema: Schema, batches: Vec<RecordBatch>) -> Self {
        Self { schema: Arc::new(schema), batches }
    }

    /// スキーマ取得
    pub fn schema(&self) -> &Schema { &self.schema }

    /// 行数取得
    pub fn height(&self) -> usize {
        self.batches.iter().map(|b| b.num_rows()).sum()
    }

    /// 列数取得
    pub fn width(&self) -> usize { self.schema.fields.len() }

    /// カラム選択
    pub fn select<I, S>(&self, columns: I) -> Result<DataFrame>
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        let cols: Vec<_> = columns.into_iter().collect();
        let indices: Vec<_> = cols.iter()
            .map(|c| self.schema.index_of(c.as_ref()))
            .collect::<Option<Vec<_>>>()
            .ok_or(Error::ColumnNotFound)?;

        let new_schema = Schema::new(
            indices.iter().map(|&i| self.schema.fields[i].clone()).collect()
        );
        let new_batches = self.batches.iter()
            .map(|b| b.project(&indices))
            .collect::<Result<Vec<_>>>()?;

        Ok(DataFrame::new(new_schema, new_batches))
    }

    /// フィルタリング
    pub fn filter(&self, predicate: &Expr) -> Result<DataFrame> {
        let filtered = self.batches.iter()
            .map(|b| filter_batch(b, predicate))
            .collect::<Result<Vec<_>>>()?;
        Ok(DataFrame::new((*self.schema).clone(), filtered))
    }

    /// ソート
    pub fn sort(&self, by: &[&str], descending: &[bool]) -> Result<DataFrame> {
        let sorted = sort_batches(&self.batches, by, descending)?;
        Ok(DataFrame::new((*self.schema).clone(), sorted))
    }

    /// グループ化集約
    pub fn group_by<I, S>(&self, keys: I) -> GroupBy
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        GroupBy::new(self.clone(), keys)
    }

    /// 結合
    pub fn join(
        &self,
        other: &DataFrame,
        left_on: &[&str],
        right_on: &[&str],
        how: JoinType,
    ) -> Result<DataFrame> {
        join_dataframes(self, other, left_on, right_on, how)
    }

    /// 先頭N行
    pub fn head(&self, n: usize) -> DataFrame {
        self.slice(0, n)
    }

    /// スライス
    pub fn slice(&self, offset: usize, length: usize) -> DataFrame {
        slice_batches(&self.batches, &self.schema, offset, length)
    }

    /// Lazy変換
    pub fn lazy(&self) -> LazyFrame {
        LazyFrame::from_dataframe(self.clone())
    }
}
```

### 4.3 Lazy DataFrame

```rust
/// Lazy評価DataFrame（遅延実行、クエリ最適化対象）
#[derive(Clone)]
pub struct LazyFrame {
    plan: LogicalPlan,
}

impl LazyFrame {
    /// 論理プランから作成
    pub fn from_logical_plan(plan: LogicalPlan) -> Self {
        Self { plan }
    }

    /// DataFrameから作成
    pub fn from_dataframe(df: DataFrame) -> Self {
        Self { plan: LogicalPlan::InMemory(df) }
    }

    /// カラム選択（遅延）
    pub fn select<E: Into<Expr>>(self, exprs: Vec<E>) -> Self {
        let exprs = exprs.into_iter().map(|e| e.into()).collect();
        Self { plan: LogicalPlan::Project { input: Box::new(self.plan), exprs } }
    }

    /// フィルタリング（遅延）
    pub fn filter(self, predicate: Expr) -> Self {
        Self { plan: LogicalPlan::Filter { input: Box::new(self.plan), predicate } }
    }

    /// グループ化集約（遅延）
    pub fn group_by<E: Into<Expr>>(self, keys: Vec<E>) -> LazyGroupBy {
        LazyGroupBy::new(self, keys)
    }

    /// ソート（遅延）
    pub fn sort(self, by: Vec<Expr>, descending: Vec<bool>) -> Self {
        Self {
            plan: LogicalPlan::Sort {
                input: Box::new(self.plan),
                by,
                descending
            }
        }
    }

    /// 結合（遅延）
    pub fn join(
        self,
        other: LazyFrame,
        left_on: Vec<Expr>,
        right_on: Vec<Expr>,
        how: JoinType,
    ) -> Self {
        Self {
            plan: LogicalPlan::Join {
                left: Box::new(self.plan),
                right: Box::new(other.plan),
                left_on,
                right_on,
                how,
            }
        }
    }

    /// LIMIT（遅延）
    pub fn limit(self, n: usize) -> Self {
        Self { plan: LogicalPlan::Limit { input: Box::new(self.plan), n } }
    }

    /// 論理プランを表示（デバッグ用）
    pub fn describe_plan(&self) -> String {
        self.plan.display()
    }

    /// 最適化後の論理プランを表示
    pub fn describe_optimized_plan(&self) -> Result<String> {
        let optimized = optimize(&self.plan)?;
        Ok(optimized.display())
    }

    /// 実行（DataFrame取得）
    pub fn collect(self) -> Result<DataFrame> {
        let optimized = optimize(&self.plan)?;
        let physical = plan_to_physical(&optimized)?;
        execute_physical(physical)
    }

    /// ストリーミング実行（イテレータ取得）
    pub fn stream(self) -> Result<RecordBatchStream> {
        let optimized = optimize(&self.plan)?;
        let physical = plan_to_physical(&optimized)?;
        execute_streaming(physical)
    }
}
```

### 4.4 式API（Expression API）

```rust
/// 式（Expression）
#[derive(Clone, Debug)]
pub enum Expr {
    // リテラル
    Literal(ScalarValue),

    // カラム参照
    Column(String),

    // エイリアス
    Alias(Box<Expr>, String),

    // 二項演算
    BinaryOp {
        left: Box<Expr>,
        op: BinaryOperator,
        right: Box<Expr>,
    },

    // 単項演算
    UnaryOp {
        op: UnaryOperator,
        expr: Box<Expr>,
    },

    // 関数呼び出し
    Function {
        name: String,
        args: Vec<Expr>,
    },

    // 集約関数
    AggregateFunction {
        func: AggregateFunc,
        args: Vec<Expr>,
        distinct: bool,
    },

    // ウィンドウ関数
    WindowFunction {
        func: WindowFunc,
        args: Vec<Expr>,
        partition_by: Vec<Expr>,
        order_by: Vec<(Expr, bool)>,
        window_frame: Option<WindowFrame>,
    },

    // CASE WHEN
    Case {
        operand: Option<Box<Expr>>,
        when_then: Vec<(Expr, Expr)>,
        else_expr: Option<Box<Expr>>,
    },

    // CAST
    Cast {
        expr: Box<Expr>,
        data_type: DataType,
    },

    // IN
    InList {
        expr: Box<Expr>,
        list: Vec<Expr>,
        negated: bool,
    },

    // BETWEEN
    Between {
        expr: Box<Expr>,
        low: Box<Expr>,
        high: Box<Expr>,
        negated: bool,
    },

    // IS NULL
    IsNull(Box<Expr>),
    IsNotNull(Box<Expr>),

    // サブクエリ
    Subquery(Box<LogicalPlan>),

    // ワイルドカード
    Wildcard,
}

/// ビルダーAPI（Polarsスタイル）
pub fn col(name: &str) -> Expr {
    Expr::Column(name.to_string())
}

pub fn lit<V: Into<ScalarValue>>(value: V) -> Expr {
    Expr::Literal(value.into())
}

impl Expr {
    pub fn alias(self, name: &str) -> Expr {
        Expr::Alias(Box::new(self), name.to_string())
    }

    pub fn eq(self, other: Expr) -> Expr {
        Expr::BinaryOp {
            left: Box::new(self),
            op: BinaryOperator::Eq,
            right: Box::new(other),
        }
    }

    pub fn gt(self, other: Expr) -> Expr {
        Expr::BinaryOp {
            left: Box::new(self),
            op: BinaryOperator::Gt,
            right: Box::new(other),
        }
    }

    pub fn and(self, other: Expr) -> Expr {
        Expr::BinaryOp {
            left: Box::new(self),
            op: BinaryOperator::And,
            right: Box::new(other),
        }
    }

    pub fn or(self, other: Expr) -> Expr {
        Expr::BinaryOp {
            left: Box::new(self),
            op: BinaryOperator::Or,
            right: Box::new(other),
        }
    }

    pub fn sum(self) -> Expr {
        Expr::AggregateFunction {
            func: AggregateFunc::Sum,
            args: vec![self],
            distinct: false,
        }
    }

    pub fn mean(self) -> Expr {
        Expr::AggregateFunction {
            func: AggregateFunc::Avg,
            args: vec![self],
            distinct: false,
        }
    }

    pub fn count(self) -> Expr {
        Expr::AggregateFunction {
            func: AggregateFunc::Count,
            args: vec![self],
            distinct: false,
        }
    }

    pub fn min(self) -> Expr {
        Expr::AggregateFunction {
            func: AggregateFunc::Min,
            args: vec![self],
            distinct: false,
        }
    }

    pub fn max(self) -> Expr {
        Expr::AggregateFunction {
            func: AggregateFunc::Max,
            args: vec![self],
            distinct: false,
        }
    }

    pub fn cast(self, data_type: DataType) -> Expr {
        Expr::Cast {
            expr: Box::new(self),
            data_type,
        }
    }
}
```

### 4.5 使用例

```rust
use alopex_columnar::{Connection, LazyFrame, col, lit};

fn main() -> Result<()> {
    // SQL API
    let conn = Connection::open("analytics.alopex")?;

    let result = conn.execute(r#"
        SELECT
            date_trunc('day', timestamp) AS day,
            COUNT(*) AS events,
            AVG(duration) AS avg_duration
        FROM events
        WHERE timestamp >= '2025-01-01'
        GROUP BY day
        ORDER BY day
    "#)?;

    println!("{}", result.to_dataframe());

    // DataFrame API（Eager）
    let df = conn.query("SELECT * FROM events")?.collect()?;

    let filtered = df
        .filter(&col("status").eq(lit("success")))?
        .select(["id", "timestamp", "duration"])?
        .sort(&["timestamp"], &[false])?;

    // DataFrame API（Lazy、最適化あり）
    let lazy_result = conn
        .query("SELECT * FROM events")?
        .filter(col("timestamp").gt(lit("2025-01-01")))
        .select(vec![col("id"), col("duration").alias("d")])
        .group_by(vec![col("category")])
        .agg(vec![
            col("d").sum().alias("total_duration"),
            col("id").count().alias("event_count"),
        ])
        .sort(vec![col("total_duration")], vec![true])
        .limit(100)
        .collect()?;

    println!("{}", lazy_result);

    Ok(())
}
```

---

## 5. クエリエンジン

### 5.1 論理プラン

```rust
/// 論理プラン（DataFusion参考）
#[derive(Clone, Debug)]
pub enum LogicalPlan {
    /// テーブルスキャン
    TableScan {
        table_name: String,
        projection: Option<Vec<usize>>,
        filters: Vec<Expr>,
        limit: Option<usize>,
    },

    /// インメモリデータ
    InMemory(DataFrame),

    /// 射影（SELECT）
    Project {
        input: Box<LogicalPlan>,
        exprs: Vec<Expr>,
    },

    /// フィルタ（WHERE）
    Filter {
        input: Box<LogicalPlan>,
        predicate: Expr,
    },

    /// 集約（GROUP BY）
    Aggregate {
        input: Box<LogicalPlan>,
        group_exprs: Vec<Expr>,
        aggr_exprs: Vec<Expr>,
    },

    /// ソート（ORDER BY）
    Sort {
        input: Box<LogicalPlan>,
        by: Vec<Expr>,
        descending: Vec<bool>,
    },

    /// 結合（JOIN）
    Join {
        left: Box<LogicalPlan>,
        right: Box<LogicalPlan>,
        left_on: Vec<Expr>,
        right_on: Vec<Expr>,
        how: JoinType,
    },

    /// 制限（LIMIT）
    Limit {
        input: Box<LogicalPlan>,
        n: usize,
    },

    /// ユニオン（UNION）
    Union {
        inputs: Vec<LogicalPlan>,
        all: bool,
    },

    /// サブクエリ
    Subquery {
        input: Box<LogicalPlan>,
        alias: String,
    },

    /// ウィンドウ
    Window {
        input: Box<LogicalPlan>,
        window_exprs: Vec<Expr>,
    },

    /// Distinct
    Distinct {
        input: Box<LogicalPlan>,
    },
}
```

### 5.2 クエリオプティマイザ

```rust
/// オプティマイザルール
pub trait OptimizerRule: Send + Sync {
    fn name(&self) -> &str;
    fn optimize(&self, plan: &LogicalPlan) -> Result<Option<LogicalPlan>>;
}

/// 組み込みルール
pub struct PredicatePushdown;
pub struct ProjectionPruning;
pub struct CommonSubexprElimination;
pub struct JoinReordering;
pub struct ConstantFolding;
pub struct SimplifyFilters;

/// オプティマイザ
pub struct Optimizer {
    rules: Vec<Box<dyn OptimizerRule>>,
    max_iterations: usize,
}

impl Optimizer {
    pub fn new() -> Self {
        Self {
            rules: vec![
                Box::new(ConstantFolding),
                Box::new(SimplifyFilters),
                Box::new(PredicatePushdown),
                Box::new(ProjectionPruning),
                Box::new(CommonSubexprElimination),
                Box::new(JoinReordering),
            ],
            max_iterations: 10,
        }
    }

    pub fn optimize(&self, plan: &LogicalPlan) -> Result<LogicalPlan> {
        let mut current = plan.clone();

        for _ in 0..self.max_iterations {
            let mut changed = false;

            for rule in &self.rules {
                if let Some(optimized) = rule.optimize(&current)? {
                    current = optimized;
                    changed = true;
                }
            }

            if !changed {
                break;
            }
        }

        Ok(current)
    }
}
```

### 5.3 物理プラン

```rust
/// 物理プラン（実行可能）
#[derive(Debug)]
pub enum PhysicalPlan {
    /// テーブルスキャン（カラムナセグメント読み込み）
    ColumnarScan {
        table_name: String,
        projection: Vec<usize>,
        filters: Vec<PhysicalExpr>,
        limit: Option<usize>,
    },

    /// フィルタ（ベクトル化）
    VectorizedFilter {
        input: Box<PhysicalPlan>,
        predicate: PhysicalExpr,
    },

    /// 射影（ベクトル化）
    VectorizedProject {
        input: Box<PhysicalPlan>,
        exprs: Vec<PhysicalExpr>,
    },

    /// ハッシュ集約（並列）
    ParallelHashAggregate {
        input: Box<PhysicalPlan>,
        group_exprs: Vec<PhysicalExpr>,
        aggr_exprs: Vec<AggregateExpr>,
        partitions: usize,
    },

    /// ハッシュ結合（並列）
    ParallelHashJoin {
        left: Box<PhysicalPlan>,
        right: Box<PhysicalPlan>,
        left_on: Vec<PhysicalExpr>,
        right_on: Vec<PhysicalExpr>,
        how: JoinType,
        partitions: usize,
    },

    /// ソート（外部ソート対応）
    ExternalSort {
        input: Box<PhysicalPlan>,
        by: Vec<PhysicalExpr>,
        descending: Vec<bool>,
        memory_limit: usize,
    },

    /// 制限
    LimitExec {
        input: Box<PhysicalPlan>,
        n: usize,
    },

    /// マージ（並列結果統合）
    CoalescePartitions {
        input: Box<PhysicalPlan>,
    },

    /// 再パーティション（並列度調整）
    Repartition {
        input: Box<PhysicalPlan>,
        partitioning: Partitioning,
    },
}

/// 実行コンテキスト
pub struct ExecutionContext {
    /// 並列度
    pub parallelism: usize,
    /// バッチサイズ
    pub batch_size: usize,
    /// メモリ制限
    pub memory_limit: usize,
    /// 一時ファイルディレクトリ
    pub temp_dir: PathBuf,
}

impl Default for ExecutionContext {
    fn default() -> Self {
        Self {
            parallelism: num_cpus::get(),
            batch_size: 8192,
            memory_limit: 1024 * 1024 * 1024, // 1GB
            temp_dir: std::env::temp_dir().join("alopex"),
        }
    }
}
```

### 5.4 ベクトル化実行

```rust
/// RecordBatch（Arrow互換のカラムナーバッチ）
pub struct RecordBatch {
    schema: Arc<Schema>,
    columns: Vec<ArrayRef>,
    num_rows: usize,
}

/// 配列参照（ポリモーフィック）
pub type ArrayRef = Arc<dyn Array>;

/// 配列トレイト
pub trait Array: Send + Sync {
    fn data_type(&self) -> &DataType;
    fn len(&self) -> usize;
    fn is_null(&self, index: usize) -> bool;
    fn null_count(&self) -> usize;
    fn slice(&self, offset: usize, length: usize) -> ArrayRef;
}

/// 型付き配列
pub struct Int64Array {
    values: Vec<i64>,
    null_bitmap: Option<Bitmap>,
}

pub struct Float64Array {
    values: Vec<f64>,
    null_bitmap: Option<Bitmap>,
}

pub struct StringArray {
    offsets: Vec<i32>,
    data: Vec<u8>,
    null_bitmap: Option<Bitmap>,
}

/// ベクトル化演算（SIMDカーネル）
pub mod kernels {
    use std::simd::*;

    /// ベクトル化加算
    pub fn add_i64(a: &[i64], b: &[i64], out: &mut [i64]) {
        const LANES: usize = 4;
        let chunks = a.len() / LANES;

        for i in 0..chunks {
            let offset = i * LANES;
            let va = i64x4::from_slice(&a[offset..]);
            let vb = i64x4::from_slice(&b[offset..]);
            let result = va + vb;
            result.copy_to_slice(&mut out[offset..]);
        }

        // 残り
        for i in (chunks * LANES)..a.len() {
            out[i] = a[i] + b[i];
        }
    }

    /// ベクトル化比較（GT）
    pub fn gt_i64(a: &[i64], b: i64) -> Vec<bool> {
        const LANES: usize = 4;
        let chunks = a.len() / LANES;
        let mut result = Vec::with_capacity(a.len());

        let vb = i64x4::splat(b);

        for i in 0..chunks {
            let offset = i * LANES;
            let va = i64x4::from_slice(&a[offset..]);
            let mask = va.simd_gt(vb);
            for j in 0..LANES {
                result.push(mask.test(j));
            }
        }

        for i in (chunks * LANES)..a.len() {
            result.push(a[i] > b);
        }

        result
    }

    /// ベクトル化フィルタ適用
    pub fn filter_batch(batch: &RecordBatch, mask: &[bool]) -> RecordBatch {
        let selected: Vec<usize> = mask.iter()
            .enumerate()
            .filter_map(|(i, &m)| if m { Some(i) } else { None })
            .collect();

        let columns: Vec<ArrayRef> = batch.columns.iter()
            .map(|col| take(col, &selected))
            .collect();

        RecordBatch {
            schema: batch.schema.clone(),
            columns,
            num_rows: selected.len(),
        }
    }
}
```

---

## 6. カラムナストレージ

### 6.1 セグメントフォーマット

既存の`alopex-core::columnar::segment`を拡張：

```rust
/// カラムナセグメント（拡張版）
pub struct ColumnSegmentV2 {
    /// セグメントメタデータ
    pub meta: SegmentMetaV2,
    /// 列データ（エンコード済み）
    pub columns: Vec<EncodedColumn>,
    /// 統計情報
    pub statistics: SegmentStatistics,
}

/// セグメントメタデータV2
#[derive(Clone, Debug)]
pub struct SegmentMetaV2 {
    /// バージョン
    pub version: u16,
    /// スキーマ
    pub schema: Arc<Schema>,
    /// 行数
    pub num_rows: u64,
    /// 作成タイムスタンプ
    pub created_at: u64,
    /// 圧縮前サイズ
    pub uncompressed_size: u64,
    /// 圧縮後サイズ
    pub compressed_size: u64,
    /// RowGroup情報
    pub row_groups: Vec<RowGroupMeta>,
}

/// RowGroupメタデータ
#[derive(Clone, Debug)]
pub struct RowGroupMeta {
    /// 行数
    pub num_rows: u64,
    /// オフセット
    pub offset: u64,
    /// 圧縮後サイズ
    pub compressed_size: u64,
    /// 列メタデータ
    pub columns: Vec<ColumnChunkMeta>,
}

/// 列チャンクメタデータ
#[derive(Clone, Debug)]
pub struct ColumnChunkMeta {
    /// 列インデックス
    pub column_index: usize,
    /// エンコーディング
    pub encoding: EncodingV2,
    /// 圧縮
    pub compression: CompressionV2,
    /// オフセット
    pub offset: u64,
    /// 圧縮後サイズ
    pub compressed_size: u64,
    /// 非圧縮サイズ
    pub uncompressed_size: u64,
    /// Null数
    pub null_count: u64,
    /// 統計
    pub statistics: Option<ColumnStatistics>,
}

/// セグメント統計
#[derive(Clone, Debug)]
pub struct SegmentStatistics {
    /// 行数
    pub num_rows: u64,
    /// 列統計
    pub column_stats: Vec<ColumnStatistics>,
}

/// 列統計
#[derive(Clone, Debug)]
pub struct ColumnStatistics {
    /// 最小値
    pub min: Option<ScalarValue>,
    /// 最大値
    pub max: Option<ScalarValue>,
    /// Null数
    pub null_count: u64,
    /// Distinct数（推定）
    pub distinct_count: Option<u64>,
}
```

### 6.2 エンコーディング

既存の`alopex-core::columnar::encoding`を大幅拡張：

```rust
/// エンコーディングV2（高圧縮対応）
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EncodingV2 {
    // 既存
    Plain,
    Dictionary,
    Rle,
    Bitpack,

    // 追加：数値最適化
    Delta,           // 差分エンコーディング
    DeltaLength,     // 可変長差分
    ByteStreamSplit, // 浮動小数点最適化

    // 追加：整数最適化
    ZigZag,          // 符号付き整数の効率的表現
    Varint,          // 可変長整数
    FOR,             // Frame of Reference
    PFOR,            // Patched Frame of Reference

    // 追加：文字列最適化
    DeltaLengthByteArray,  // 長さの差分
    IncrementalString,     // 増分文字列（ソート済み向け）
}

/// 圧縮V2（追加アルゴリズム）
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CompressionV2 {
    None,
    Lz4,     // 既存
    Zstd,    // 高圧縮
    Snappy,  // 高速
    Brotli,  // Web向け高圧縮
}

/// エンコーダ選択ヒューリスティック
pub struct EncodingSelector;

impl EncodingSelector {
    /// 列データに最適なエンコーディングを選択
    pub fn select(
        data_type: &DataType,
        sample: &ArrayRef,
        target: EncodingTarget,
    ) -> EncodingV2 {
        match data_type {
            DataType::Int64 | DataType::Int32 => {
                let stats = analyze_integer_column(sample);

                if stats.is_sorted && stats.delta_range_small {
                    EncodingV2::Delta
                } else if stats.cardinality_ratio < 0.1 {
                    EncodingV2::Dictionary
                } else if stats.has_long_runs {
                    EncodingV2::Rle
                } else if stats.value_range_small {
                    EncodingV2::FOR
                } else {
                    EncodingV2::Plain
                }
            }

            DataType::Float64 | DataType::Float32 => {
                EncodingV2::ByteStreamSplit
            }

            DataType::Boolean => {
                EncodingV2::Bitpack
            }

            DataType::Utf8 | DataType::Binary => {
                let stats = analyze_string_column(sample);

                if stats.cardinality_ratio < 0.3 {
                    EncodingV2::Dictionary
                } else if stats.is_sorted {
                    EncodingV2::IncrementalString
                } else {
                    EncodingV2::DeltaLengthByteArray
                }
            }

            DataType::Timestamp { .. } => {
                // タイムスタンプは通常ソート済みなのでDeltaが効果的
                EncodingV2::Delta
            }

            _ => EncodingV2::Plain,
        }
    }
}

/// エンコーディングターゲット
pub enum EncodingTarget {
    /// 圧縮率優先
    HighCompression,
    /// 速度優先
    FastAccess,
    /// バランス
    Balanced,
}
```

### 6.3 圧縮パイプライン

```rust
/// 圧縮パイプライン
pub struct CompressionPipeline {
    /// ターゲット圧縮レベル
    level: CompressionLevel,
    /// Zstd辞書（事前学習済み）
    zstd_dict: Option<ZstdDictionary>,
}

#[derive(Clone, Copy)]
pub enum CompressionLevel {
    /// 速度優先（Snappy/LZ4）
    Fast,
    /// バランス（Zstd level 3）
    Balanced,
    /// 高圧縮（Zstd level 9+辞書）
    High,
    /// 最高圧縮（Zstd level 19+辞書）
    Maximum,
}

impl CompressionPipeline {
    pub fn new(level: CompressionLevel) -> Self {
        Self { level, zstd_dict: None }
    }

    /// 辞書学習
    pub fn train_dictionary(&mut self, samples: &[&[u8]]) -> Result<()> {
        if matches!(self.level, CompressionLevel::High | CompressionLevel::Maximum) {
            let dict = zstd::dict::EncoderDictionary::copy(
                samples,
                if matches!(self.level, CompressionLevel::Maximum) { 19 } else { 9 }
            )?;
            self.zstd_dict = Some(dict);
        }
        Ok(())
    }

    /// 圧縮
    pub fn compress(&self, data: &[u8]) -> Result<Vec<u8>> {
        match self.level {
            CompressionLevel::Fast => {
                lz4::block::compress(data, None, false)
                    .map_err(|e| Error::Compression(e.to_string()))
            }
            CompressionLevel::Balanced => {
                let mut encoder = zstd::Encoder::new(Vec::new(), 3)?;
                encoder.write_all(data)?;
                Ok(encoder.finish()?)
            }
            CompressionLevel::High => {
                let level = 9;
                if let Some(ref dict) = self.zstd_dict {
                    let mut encoder = zstd::Encoder::with_prepared_dictionary(
                        Vec::new(), dict
                    )?;
                    encoder.write_all(data)?;
                    Ok(encoder.finish()?)
                } else {
                    let mut encoder = zstd::Encoder::new(Vec::new(), level)?;
                    encoder.write_all(data)?;
                    Ok(encoder.finish()?)
                }
            }
            CompressionLevel::Maximum => {
                let level = 19;
                if let Some(ref dict) = self.zstd_dict {
                    let mut encoder = zstd::Encoder::with_prepared_dictionary(
                        Vec::new(), dict
                    )?;
                    encoder.set_parameter(zstd::stream::raw::CParameter::CompressionLevel(level))?;
                    encoder.write_all(data)?;
                    Ok(encoder.finish()?)
                } else {
                    let mut encoder = zstd::Encoder::new(Vec::new(), level)?;
                    encoder.write_all(data)?;
                    Ok(encoder.finish()?)
                }
            }
        }
    }

    /// 解凍
    pub fn decompress(&self, data: &[u8], uncompressed_size: usize) -> Result<Vec<u8>> {
        match self.level {
            CompressionLevel::Fast => {
                lz4::block::decompress(data, Some(uncompressed_size as i32))
                    .map_err(|e| Error::Compression(e.to_string()))
            }
            _ => {
                let mut decoder = if let Some(ref dict) = self.zstd_dict {
                    zstd::Decoder::with_prepared_dictionary(
                        std::io::Cursor::new(data),
                        &zstd::dict::DecoderDictionary::copy(dict.as_bytes())
                    )?
                } else {
                    zstd::Decoder::new(std::io::Cursor::new(data))?
                };

                let mut out = Vec::with_capacity(uncompressed_size);
                decoder.read_to_end(&mut out)?;
                Ok(out)
            }
        }
    }
}
```

---

## 7. KVS永続化レイヤ

### 7.1 KVSレイアウト設計

Alopex KVS上にカラムナセグメントを格納するキーレイアウト：

```rust
/// カラムナデータのKVSキー設計
pub mod key_layout {
    /// プレフィックス定義
    pub const PREFIX_TABLE_META: u8 = 0x10;
    pub const PREFIX_COLUMN_SEGMENT: u8 = 0x11;
    pub const PREFIX_SEGMENT_INDEX: u8 = 0x12;
    pub const PREFIX_STATISTICS: u8 = 0x13;
    pub const PREFIX_ROW_GROUP: u8 = 0x14;

    /// テーブルメタデータキー
    /// Format: [PREFIX_TABLE_META][table_name_length:u16][table_name:bytes]
    pub fn table_meta_key(table_name: &str) -> Vec<u8> {
        let mut key = Vec::with_capacity(3 + table_name.len());
        key.push(PREFIX_TABLE_META);
        key.extend_from_slice(&(table_name.len() as u16).to_le_bytes());
        key.extend_from_slice(table_name.as_bytes());
        key
    }

    /// セグメントインデックスキー
    /// Format: [PREFIX_SEGMENT_INDEX][table_id:u32]
    pub fn segment_index_key(table_id: u32) -> Vec<u8> {
        let mut key = Vec::with_capacity(5);
        key.push(PREFIX_SEGMENT_INDEX);
        key.extend_from_slice(&table_id.to_le_bytes());
        key
    }

    /// カラムセグメントキー
    /// Format: [PREFIX_COLUMN_SEGMENT][table_id:u32][segment_id:u64][column_idx:u16]
    pub fn column_segment_key(table_id: u32, segment_id: u64, column_idx: u16) -> Vec<u8> {
        let mut key = Vec::with_capacity(15);
        key.push(PREFIX_COLUMN_SEGMENT);
        key.extend_from_slice(&table_id.to_le_bytes());
        key.extend_from_slice(&segment_id.to_le_bytes());
        key.extend_from_slice(&column_idx.to_le_bytes());
        key
    }

    /// RowGroupキー
    /// Format: [PREFIX_ROW_GROUP][table_id:u32][segment_id:u64][row_group_idx:u32]
    pub fn row_group_key(table_id: u32, segment_id: u64, row_group_idx: u32) -> Vec<u8> {
        let mut key = Vec::with_capacity(17);
        key.push(PREFIX_ROW_GROUP);
        key.extend_from_slice(&table_id.to_le_bytes());
        key.extend_from_slice(&segment_id.to_le_bytes());
        key.extend_from_slice(&row_group_idx.to_le_bytes());
        key
    }

    /// 統計情報キー
    /// Format: [PREFIX_STATISTICS][table_id:u32][segment_id:u64]
    pub fn statistics_key(table_id: u32, segment_id: u64) -> Vec<u8> {
        let mut key = Vec::with_capacity(13);
        key.push(PREFIX_STATISTICS);
        key.extend_from_slice(&table_id.to_le_bytes());
        key.extend_from_slice(&segment_id.to_le_bytes());
        key
    }
}
```

### 7.2 カラムナストレージマネージャ

```rust
/// カラムナストレージマネージャ（KVS統合）
pub struct ColumnarStorageManager {
    /// KVSストア
    kv_store: Arc<dyn KVStore>,
    /// カタログ
    catalog: Arc<Catalog>,
    /// 圧縮パイプライン
    compression: CompressionPipeline,
    /// セグメントキャッシュ
    segment_cache: Arc<SegmentCache>,
}

impl ColumnarStorageManager {
    pub fn new(kv_store: Arc<dyn KVStore>, config: ColumnarConfig) -> Self {
        Self {
            kv_store,
            catalog: Arc::new(Catalog::new()),
            compression: CompressionPipeline::new(config.compression_level),
            segment_cache: Arc::new(SegmentCache::new(config.cache_size)),
        }
    }

    /// テーブル作成
    pub async fn create_table(&self, name: &str, schema: Schema) -> Result<TableId> {
        let table_id = self.catalog.next_table_id();
        let meta = TableMeta {
            id: table_id,
            name: name.to_string(),
            schema: Arc::new(schema),
            created_at: current_timestamp(),
            segments: vec![],
        };

        let key = key_layout::table_meta_key(name);
        let value = bincode::serialize(&meta)?;
        self.kv_store.put(&key, &value).await?;

        self.catalog.register_table(meta)?;

        Ok(table_id)
    }

    /// セグメント書き込み
    pub async fn write_segment(
        &self,
        table_id: TableId,
        batches: Vec<RecordBatch>,
    ) -> Result<SegmentId> {
        let table = self.catalog.get_table(table_id)?;
        let segment_id = self.catalog.next_segment_id(table_id);

        // RecordBatchをカラムセグメントに変換
        let segment = self.encode_segment(&table.schema, batches)?;

        // KVSに書き込み
        let mut txn = self.kv_store.begin_transaction().await?;

        // 各列を個別に書き込み
        for (col_idx, encoded_column) in segment.columns.iter().enumerate() {
            let key = key_layout::column_segment_key(
                table_id, segment_id, col_idx as u16
            );
            txn.put(&key, &encoded_column.data).await?;
        }

        // 統計情報を書き込み
        let stats_key = key_layout::statistics_key(table_id, segment_id);
        let stats_value = bincode::serialize(&segment.statistics)?;
        txn.put(&stats_key, &stats_value).await?;

        // メタデータ更新
        let index_key = key_layout::segment_index_key(table_id);
        let mut index: SegmentIndex = self.kv_store
            .get(&index_key).await?
            .map(|v| bincode::deserialize(&v))
            .transpose()?
            .unwrap_or_default();

        index.segments.push(SegmentIndexEntry {
            id: segment_id,
            num_rows: segment.meta.num_rows,
            min_timestamp: segment.statistics.min_timestamp,
            max_timestamp: segment.statistics.max_timestamp,
            compressed_size: segment.meta.compressed_size,
        });

        txn.put(&index_key, &bincode::serialize(&index)?).await?;

        txn.commit().await?;

        Ok(segment_id)
    }

    /// セグメント読み込み（列プルーニング対応）
    pub async fn read_segment(
        &self,
        table_id: TableId,
        segment_id: SegmentId,
        columns: &[usize],
    ) -> Result<Vec<RecordBatch>> {
        // キャッシュチェック
        if let Some(cached) = self.segment_cache.get(table_id, segment_id, columns) {
            return Ok(cached);
        }

        let table = self.catalog.get_table(table_id)?;

        // 必要な列のみ読み込み（Projection Pushdown）
        let mut column_data = Vec::with_capacity(columns.len());

        for &col_idx in columns {
            let key = key_layout::column_segment_key(
                table_id, segment_id, col_idx as u16
            );
            let data = self.kv_store.get(&key).await?
                .ok_or(Error::SegmentNotFound)?;

            let decoded = self.decode_column(&table.schema.fields[col_idx], &data)?;
            column_data.push(decoded);
        }

        // RecordBatchに変換
        let projected_schema = Arc::new(Schema::new(
            columns.iter().map(|&i| table.schema.fields[i].clone()).collect()
        ));

        let batches = self.columns_to_batches(projected_schema, column_data)?;

        // キャッシュに追加
        self.segment_cache.put(table_id, segment_id, columns, batches.clone());

        Ok(batches)
    }

    /// テーブルスキャン（統計ベースプルーニング）
    pub async fn scan_table(
        &self,
        table_id: TableId,
        projection: &[usize],
        filter: Option<&Expr>,
    ) -> Result<RecordBatchStream> {
        let table = self.catalog.get_table(table_id)?;

        // セグメントインデックス取得
        let index_key = key_layout::segment_index_key(table_id);
        let index: SegmentIndex = self.kv_store
            .get(&index_key).await?
            .map(|v| bincode::deserialize(&v))
            .transpose()?
            .unwrap_or_default();

        // フィルタに基づくセグメントプルーニング
        let candidate_segments = if let Some(filter) = filter {
            self.prune_segments(&index.segments, filter)?
        } else {
            index.segments.clone()
        };

        // ストリーミング読み込み
        let stream = SegmentScanStream::new(
            self.clone(),
            table_id,
            candidate_segments,
            projection.to_vec(),
            filter.cloned(),
        );

        Ok(Box::pin(stream))
    }

    /// 統計ベースセグメントプルーニング
    fn prune_segments(
        &self,
        segments: &[SegmentIndexEntry],
        filter: &Expr,
    ) -> Result<Vec<SegmentIndexEntry>> {
        let mut result = Vec::new();

        for segment in segments {
            // 統計情報取得
            let stats = self.get_segment_statistics(segment.id)?;

            // フィルタ条件と統計情報の比較
            if self.segment_might_match(&stats, filter) {
                result.push(segment.clone());
            }
        }

        Ok(result)
    }

    /// セグメントがフィルタに一致する可能性があるか
    fn segment_might_match(&self, stats: &SegmentStatistics, filter: &Expr) -> bool {
        // Min/Maxベースのプルーニング
        match filter {
            Expr::BinaryOp { left, op, right } => {
                match (left.as_ref(), op, right.as_ref()) {
                    (Expr::Column(col), BinaryOperator::Gt, Expr::Literal(val)) => {
                        if let Some(col_stats) = stats.column_stats.iter()
                            .find(|s| s.column_name == *col)
                        {
                            if let (Some(max), Some(threshold)) =
                                (&col_stats.max, val.try_to_comparable())
                            {
                                return max > &threshold;
                            }
                        }
                        true // 判断できない場合はスキップしない
                    }
                    (Expr::Column(col), BinaryOperator::Lt, Expr::Literal(val)) => {
                        if let Some(col_stats) = stats.column_stats.iter()
                            .find(|s| s.column_name == *col)
                        {
                            if let (Some(min), Some(threshold)) =
                                (&col_stats.min, val.try_to_comparable())
                            {
                                return min < &threshold;
                            }
                        }
                        true
                    }
                    _ => true,
                }
            }
            _ => true,
        }
    }

    fn encode_segment(
        &self,
        schema: &Schema,
        batches: Vec<RecordBatch>,
    ) -> Result<ColumnSegmentV2> {
        let mut columns = Vec::with_capacity(schema.fields.len());
        let mut total_rows = 0u64;
        let mut column_stats = Vec::new();

        for (col_idx, field) in schema.fields.iter().enumerate() {
            // 全バッチから該当列を抽出
            let arrays: Vec<ArrayRef> = batches.iter()
                .map(|b| b.column(col_idx).clone())
                .collect();

            // エンコーディング選択
            let encoding = EncodingSelector::select(
                &field.data_type,
                &arrays[0],
                EncodingTarget::Balanced,
            );

            // エンコード
            let encoded = self.encode_column(&arrays, encoding)?;

            // 圧縮
            let compressed = self.compression.compress(&encoded)?;

            // 統計収集
            let stats = compute_column_statistics(&arrays, &field.name);
            column_stats.push(stats);

            columns.push(EncodedColumn {
                encoding,
                compression: self.compression.level.into(),
                data: compressed,
                uncompressed_size: encoded.len() as u64,
            });

            if col_idx == 0 {
                total_rows = arrays.iter().map(|a| a.len() as u64).sum();
            }
        }

        Ok(ColumnSegmentV2 {
            meta: SegmentMetaV2 {
                version: 2,
                schema: Arc::new(schema.clone()),
                num_rows: total_rows,
                created_at: current_timestamp(),
                uncompressed_size: columns.iter().map(|c| c.uncompressed_size).sum(),
                compressed_size: columns.iter().map(|c| c.data.len() as u64).sum(),
                row_groups: vec![],
            },
            columns,
            statistics: SegmentStatistics {
                num_rows: total_rows,
                column_stats,
            },
        })
    }
}
```

---

## 8. .alopexファイル統合

### 8.1 セクション0x03: ColumnarSegment

既存の`.alopex`ファイルフォーマットとの統合：

```rust
/// Columnarセクションライター
pub struct ColumnarSectionWriter {
    /// セクションタイプ
    pub const SECTION_TYPE: u8 = 0x03;
}

impl ColumnarSectionWriter {
    /// セグメントをセクションとして書き込み
    pub fn write_section(
        file: &mut AlopexFileBuilder,
        segment: &ColumnSegmentV2,
    ) -> Result<SectionEntry> {
        let mut section_data = Vec::new();

        // セグメントヘッダ
        section_data.extend_from_slice(&segment.meta.version.to_le_bytes());
        section_data.extend_from_slice(&segment.meta.num_rows.to_le_bytes());
        section_data.extend_from_slice(&(segment.columns.len() as u32).to_le_bytes());

        // スキーマ（bincode）
        let schema_bytes = bincode::serialize(&segment.meta.schema)?;
        section_data.extend_from_slice(&(schema_bytes.len() as u32).to_le_bytes());
        section_data.extend_from_slice(&schema_bytes);

        // 統計情報
        let stats_bytes = bincode::serialize(&segment.statistics)?;
        section_data.extend_from_slice(&(stats_bytes.len() as u32).to_le_bytes());
        section_data.extend_from_slice(&stats_bytes);

        // 列データ（オフセットテーブル + データ）
        let mut column_offsets = Vec::with_capacity(segment.columns.len());
        let mut column_data = Vec::new();

        for col in &segment.columns {
            column_offsets.push(column_data.len() as u64);

            // 列ヘッダ
            column_data.push(col.encoding as u8);
            column_data.push(col.compression as u8);
            column_data.extend_from_slice(&col.uncompressed_size.to_le_bytes());
            column_data.extend_from_slice(&(col.data.len() as u64).to_le_bytes());

            // 列データ
            column_data.extend_from_slice(&col.data);
        }

        // オフセットテーブル
        for offset in &column_offsets {
            section_data.extend_from_slice(&offset.to_le_bytes());
        }

        // 列データ
        section_data.extend_from_slice(&column_data);

        // CRC32チェックサム
        let mut hasher = crc32fast::Hasher::new();
        hasher.update(&section_data);
        let checksum = hasher.finalize();

        // セクションエントリ作成
        let entry = SectionEntry {
            section_type: Self::SECTION_TYPE,
            section_id: file.next_section_id(),
            offset: file.current_offset(),
            length: section_data.len() as u64,
            checksum,
        };

        file.write_section_data(&section_data)?;

        Ok(entry)
    }
}

/// Columnarセクションリーダー
pub struct ColumnarSectionReader;

impl ColumnarSectionReader {
    /// セクションからセグメントを読み込み
    pub fn read_section(
        data: &[u8],
        columns: Option<&[usize]>,  // 列プルーニング
    ) -> Result<ColumnSegmentV2> {
        let mut pos = 0;

        // ヘッダ読み込み
        let version = u16::from_le_bytes(data[pos..pos+2].try_into()?);
        pos += 2;
        let num_rows = u64::from_le_bytes(data[pos..pos+8].try_into()?);
        pos += 8;
        let num_columns = u32::from_le_bytes(data[pos..pos+4].try_into()?) as usize;
        pos += 4;

        // スキーマ
        let schema_len = u32::from_le_bytes(data[pos..pos+4].try_into()?) as usize;
        pos += 4;
        let schema: Arc<Schema> = Arc::new(bincode::deserialize(&data[pos..pos+schema_len])?);
        pos += schema_len;

        // 統計情報
        let stats_len = u32::from_le_bytes(data[pos..pos+4].try_into()?) as usize;
        pos += 4;
        let statistics: SegmentStatistics = bincode::deserialize(&data[pos..pos+stats_len])?;
        pos += stats_len;

        // オフセットテーブル
        let mut column_offsets = Vec::with_capacity(num_columns);
        for _ in 0..num_columns {
            column_offsets.push(u64::from_le_bytes(data[pos..pos+8].try_into()?));
            pos += 8;
        }

        let column_data_start = pos;

        // 列読み込み（列プルーニング対応）
        let target_columns = columns.unwrap_or(&(0..num_columns).collect::<Vec<_>>());
        let mut decoded_columns = Vec::with_capacity(target_columns.len());

        for &col_idx in target_columns {
            let offset = column_offsets[col_idx] as usize;
            let col_pos = column_data_start + offset;

            // 列ヘッダ
            let encoding = EncodingV2::from_byte(data[col_pos])?;
            let compression = CompressionV2::from_byte(data[col_pos + 1])?;
            let uncompressed_size = u64::from_le_bytes(
                data[col_pos+2..col_pos+10].try_into()?
            );
            let compressed_size = u64::from_le_bytes(
                data[col_pos+10..col_pos+18].try_into()?
            ) as usize;

            let col_data = &data[col_pos+18..col_pos+18+compressed_size];

            decoded_columns.push(EncodedColumn {
                encoding,
                compression,
                data: col_data.to_vec(),
                uncompressed_size,
            });
        }

        Ok(ColumnSegmentV2 {
            meta: SegmentMetaV2 {
                version,
                schema,
                num_rows,
                created_at: 0,
                uncompressed_size: 0,
                compressed_size: 0,
                row_groups: vec![],
            },
            columns: decoded_columns,
            statistics,
        })
    }
}
```

---

## 9. 性能最適化

### 9.1 並列処理

```rust
/// 並列実行エンジン
pub struct ParallelExecutor {
    /// スレッドプール
    pool: rayon::ThreadPool,
    /// 並列度
    parallelism: usize,
}

impl ParallelExecutor {
    pub fn new(parallelism: usize) -> Self {
        let pool = rayon::ThreadPoolBuilder::new()
            .num_threads(parallelism)
            .build()
            .unwrap();

        Self { pool, parallelism }
    }

    /// 並列スキャン
    pub fn parallel_scan<F, T>(
        &self,
        segments: Vec<SegmentId>,
        scan_fn: F,
    ) -> Vec<T>
    where
        F: Fn(SegmentId) -> T + Sync,
        T: Send,
    {
        self.pool.install(|| {
            segments.par_iter()
                .map(|&seg_id| scan_fn(seg_id))
                .collect()
        })
    }

    /// 並列ハッシュ集約
    pub fn parallel_hash_aggregate(
        &self,
        batches: Vec<RecordBatch>,
        group_exprs: &[PhysicalExpr],
        aggr_exprs: &[AggregateExpr],
    ) -> Result<RecordBatch> {
        // Phase 1: パーティション別ローカル集約
        let local_results: Vec<HashMap<GroupKey, AccumulatorSet>> = self.pool.install(|| {
            batches.par_iter()
                .map(|batch| {
                    let mut local_map = HashMap::new();
                    for row_idx in 0..batch.num_rows() {
                        let key = extract_group_key(batch, row_idx, group_exprs);
                        let accumulators = local_map.entry(key)
                            .or_insert_with(|| AccumulatorSet::new(aggr_exprs));
                        accumulators.update(batch, row_idx);
                    }
                    local_map
                })
                .collect()
        });

        // Phase 2: グローバルマージ
        let mut global_map: HashMap<GroupKey, AccumulatorSet> = HashMap::new();
        for local_map in local_results {
            for (key, local_accum) in local_map {
                global_map.entry(key)
                    .or_insert_with(|| AccumulatorSet::new(aggr_exprs))
                    .merge(local_accum);
            }
        }

        // Phase 3: 結果RecordBatch構築
        build_aggregate_result(global_map, group_exprs, aggr_exprs)
    }
}
```

### 9.2 メモリ管理

```rust
/// メモリプール（再利用可能なバッファ）
pub struct MemoryPool {
    /// 利用可能バッファ
    available: Mutex<Vec<Vec<u8>>>,
    /// 最大バッファサイズ
    max_buffer_size: usize,
    /// 最大プールサイズ
    max_pool_size: usize,
    /// 現在の使用量
    current_usage: AtomicUsize,
}

impl MemoryPool {
    pub fn new(max_pool_size: usize, max_buffer_size: usize) -> Self {
        Self {
            available: Mutex::new(Vec::new()),
            max_buffer_size,
            max_pool_size,
            current_usage: AtomicUsize::new(0),
        }
    }

    /// バッファ取得
    pub fn acquire(&self, size: usize) -> PooledBuffer {
        if size > self.max_buffer_size {
            return PooledBuffer::new(vec![0u8; size], None);
        }

        let mut available = self.available.lock().unwrap();
        if let Some(mut buf) = available.pop() {
            buf.resize(size, 0);
            return PooledBuffer::new(buf, Some(self));
        }
        drop(available);

        self.current_usage.fetch_add(size, Ordering::Relaxed);
        PooledBuffer::new(vec![0u8; size], Some(self))
    }

    /// バッファ返却
    fn release(&self, mut buf: Vec<u8>) {
        if buf.capacity() <= self.max_buffer_size {
            let mut available = self.available.lock().unwrap();
            if available.len() < self.max_pool_size {
                buf.clear();
                available.push(buf);
                return;
            }
        }
        self.current_usage.fetch_sub(buf.capacity(), Ordering::Relaxed);
    }
}

/// プール管理バッファ
pub struct PooledBuffer<'a> {
    data: Vec<u8>,
    pool: Option<&'a MemoryPool>,
}

impl<'a> Drop for PooledBuffer<'a> {
    fn drop(&mut self) {
        if let Some(pool) = self.pool {
            pool.release(std::mem::take(&mut self.data));
        }
    }
}
```

### 9.3 キャッシュ戦略

```rust
/// セグメントキャッシュ（LRU）
pub struct SegmentCache {
    /// キャッシュエントリ
    entries: Mutex<LruCache<CacheKey, CachedSegment>>,
    /// 最大サイズ（バイト）
    max_size: usize,
    /// 現在のサイズ
    current_size: AtomicUsize,
    /// ヒット統計
    hits: AtomicU64,
    misses: AtomicU64,
}

#[derive(Hash, Eq, PartialEq, Clone)]
struct CacheKey {
    table_id: TableId,
    segment_id: SegmentId,
    columns: Vec<usize>,
}

struct CachedSegment {
    batches: Vec<RecordBatch>,
    size: usize,
}

impl SegmentCache {
    pub fn new(max_size: usize) -> Self {
        Self {
            entries: Mutex::new(LruCache::new(
                NonZeroUsize::new(10000).unwrap()
            )),
            max_size,
            current_size: AtomicUsize::new(0),
            hits: AtomicU64::new(0),
            misses: AtomicU64::new(0),
        }
    }

    pub fn get(
        &self,
        table_id: TableId,
        segment_id: SegmentId,
        columns: &[usize],
    ) -> Option<Vec<RecordBatch>> {
        let key = CacheKey {
            table_id,
            segment_id,
            columns: columns.to_vec(),
        };

        let mut entries = self.entries.lock().unwrap();
        if let Some(cached) = entries.get(&key) {
            self.hits.fetch_add(1, Ordering::Relaxed);
            return Some(cached.batches.clone());
        }

        self.misses.fetch_add(1, Ordering::Relaxed);
        None
    }

    pub fn put(
        &self,
        table_id: TableId,
        segment_id: SegmentId,
        columns: &[usize],
        batches: Vec<RecordBatch>,
    ) {
        let size = batches.iter()
            .map(|b| b.get_array_memory_size())
            .sum();

        // サイズ制限チェック
        while self.current_size.load(Ordering::Relaxed) + size > self.max_size {
            let mut entries = self.entries.lock().unwrap();
            if let Some((_, evicted)) = entries.pop_lru() {
                self.current_size.fetch_sub(evicted.size, Ordering::Relaxed);
            } else {
                break;
            }
        }

        let key = CacheKey {
            table_id,
            segment_id,
            columns: columns.to_vec(),
        };

        let cached = CachedSegment { batches, size };

        let mut entries = self.entries.lock().unwrap();
        entries.put(key, cached);
        self.current_size.fetch_add(size, Ordering::Relaxed);
    }

    pub fn hit_rate(&self) -> f64 {
        let hits = self.hits.load(Ordering::Relaxed);
        let misses = self.misses.load(Ordering::Relaxed);
        let total = hits + misses;
        if total == 0 {
            0.0
        } else {
            hits as f64 / total as f64
        }
    }
}
```

---

## 10. 設定とチューニング

### 10.1 設定パラメータ

```rust
/// カラムナエンジン設定
#[derive(Clone, Debug)]
pub struct ColumnarConfig {
    // ストレージ
    /// 圧縮レベル
    pub compression_level: CompressionLevel,
    /// RowGroupサイズ（行数）
    pub row_group_size: usize,
    /// セグメント最大サイズ（バイト）
    pub segment_max_size: usize,

    // 実行
    /// 並列度（0 = 自動）
    pub parallelism: usize,
    /// バッチサイズ
    pub batch_size: usize,
    /// メモリ制限（バイト）
    pub memory_limit: usize,

    // キャッシュ
    /// セグメントキャッシュサイズ（バイト）
    pub cache_size: usize,
    /// 統計キャッシュ有効化
    pub enable_stats_cache: bool,

    // 最適化
    /// Predicate Pushdown有効化
    pub enable_predicate_pushdown: bool,
    /// Projection Pruning有効化
    pub enable_projection_pruning: bool,
    /// 遅延デコード有効化
    pub enable_late_materialization: bool,
}

impl Default for ColumnarConfig {
    fn default() -> Self {
        Self {
            compression_level: CompressionLevel::Balanced,
            row_group_size: 100_000,
            segment_max_size: 256 * 1024 * 1024, // 256MB
            parallelism: 0, // 自動
            batch_size: 8192,
            memory_limit: 1024 * 1024 * 1024, // 1GB
            cache_size: 256 * 1024 * 1024, // 256MB
            enable_stats_cache: true,
            enable_predicate_pushdown: true,
            enable_projection_pruning: true,
            enable_late_materialization: true,
        }
    }
}

/// 設定ビルダー
impl ColumnarConfig {
    pub fn builder() -> ColumnarConfigBuilder {
        ColumnarConfigBuilder::default()
    }

    /// 高圧縮プリセット
    pub fn high_compression() -> Self {
        Self {
            compression_level: CompressionLevel::Maximum,
            row_group_size: 200_000,
            ..Default::default()
        }
    }

    /// 高速アクセスプリセット
    pub fn fast_access() -> Self {
        Self {
            compression_level: CompressionLevel::Fast,
            row_group_size: 50_000,
            batch_size: 16384,
            ..Default::default()
        }
    }

    /// メモリ制約プリセット
    pub fn low_memory() -> Self {
        Self {
            memory_limit: 256 * 1024 * 1024, // 256MB
            cache_size: 64 * 1024 * 1024, // 64MB
            batch_size: 4096,
            ..Default::default()
        }
    }
}
```

### 10.2 性能メトリクス

```rust
/// 性能メトリクス収集
pub struct ColumnarMetrics {
    // クエリ実行
    pub query_count: Counter,
    pub query_latency: Histogram,
    pub rows_scanned: Counter,
    pub bytes_scanned: Counter,

    // 圧縮
    pub compression_ratio: Gauge,
    pub compression_time: Histogram,
    pub decompression_time: Histogram,

    // キャッシュ
    pub cache_hits: Counter,
    pub cache_misses: Counter,
    pub cache_evictions: Counter,

    // I/O
    pub read_bytes: Counter,
    pub write_bytes: Counter,
    pub io_latency: Histogram,
}

impl ColumnarMetrics {
    pub fn register(registry: &Registry) -> Self {
        Self {
            query_count: Counter::new("alopex_columnar_query_total", "Total queries")
                .register(registry),
            query_latency: Histogram::new(
                "alopex_columnar_query_duration_seconds",
                "Query latency",
                vec![0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
            ).register(registry),
            // ... 他のメトリクス
        }
    }
}
```

---

## 11. マイルストーン

### Phase 1: 基盤（v0.8）

| 機能 | 状態 | 備考 |
|------|------|------|
| 既存columnarモジュール統合 | ✅ 完了 | encoding.rs, segment.rs |
| 拡張エンコーディング（Delta, ZigZag） | 🔄 進行中 | |
| Zstd圧縮サポート | 📋 予定 | |
| 基本SQL API | 📋 予定 | |

### Phase 2: クエリエンジン（v0.9）

| 機能 | 状態 | 備考 |
|------|------|------|
| 論理プラン | 📋 予定 | |
| クエリオプティマイザ | 📋 予定 | |
| ベクトル化実行エンジン | 📋 予定 | |
| 並列スキャン | 📋 予定 | |

### Phase 3: DataFrame API（v1.0）

| 機能 | 状態 | 備考 |
|------|------|------|
| Eager DataFrame | 📋 予定 | |
| Lazy DataFrame | 📋 予定 | |
| 式API | 📋 予定 | |
| グループ化・集約 | 📋 予定 | |

### Phase 4: 高度な最適化（v1.1+）

| 機能 | 状態 | 備考 |
|------|------|------|
| 辞書圧縮最適化 | 📋 予定 | |
| SIMD最適化 | 📋 予定 | |
| 外部ソート | 📋 予定 | |
| ストリーミング集約 | 📋 予定 | |

---

## 12. カラムナベースベクトルストア

### 12.1 設計方針

ベクトルストアはランダムアクセスを想定せず、**バッチ追記＋削除**操作で十分であるため、カラムナストレージに完全統合する設計を採用。KVSベースのHot/Coldハイブリッド構成は不採用。

#### アクセスパターン分析

| 操作 | 頻度 | 特性 |
|------|------|------|
| バッチ追記 | 低〜中 | 大量ベクトルを一括挿入 |
| 全文スキャン（検索） | 高 | 全ベクトルをスキャンしてTop-K取得 |
| バッチ削除 | 低 | 論理削除 + 定期コンパクション |
| ランダムアクセス | なし | 個別ベクトル取得は不要 |

#### カラムナ専用設計の優位性

| 指標 | KVSベース | カラムナ専用 |
|------|-----------|-------------|
| スキャン速度 | 1x | 10-15x |
| 圧縮率 | 2-3x | 10-40x |
| メモリ効率 | 低（キー管理オーバーヘッド） | 高（連続メモリ） |
| SIMD最適化 | 困難 | 容易 |
| バッチ操作 | 中程度 | 最適 |

### 12.2 ベクトルセグメントスキーマ

```rust
/// ベクトル専用カラムナセグメント
pub struct VectorSegment {
    /// セグメントID
    pub segment_id: u64,
    /// ベクトル次元数
    pub dimension: usize,
    /// 距離メトリック
    pub metric: Metric,
    /// ベクトル数
    pub num_vectors: u64,
    /// ベクトルデータ（Float32の連続配列）
    pub vectors: EncodedColumn,
    /// キー列（ベクトル識別子）
    pub keys: EncodedColumn,
    /// 削除フラグ（ビットマップ）
    pub deleted: Bitmap,
    /// メタデータ列（オプション）
    pub metadata: Option<Vec<EncodedColumn>>,
    /// 統計情報
    pub statistics: VectorSegmentStatistics,
}

/// ベクトルセグメント統計
#[derive(Clone, Debug)]
pub struct VectorSegmentStatistics {
    /// 有効ベクトル数（削除済み除外）
    pub active_count: u64,
    /// 削除済みベクトル数
    pub deleted_count: u64,
    /// 削除率（コンパクション判定用）
    pub deletion_ratio: f32,
    /// ノルム統計（正規化チェック用）
    pub norm_min: f32,
    pub norm_max: f32,
    /// 作成タイムスタンプ
    pub created_at: u64,
}
```

### 12.3 バッチ追記API

```rust
/// ベクトルストアマネージャ（カラムナ統合）
pub struct VectorStoreManager {
    storage: Arc<ColumnarStorageManager>,
    config: VectorStoreConfig,
}

/// ベクトルストア設定
#[derive(Clone, Debug)]
pub struct VectorStoreConfig {
    /// 次元数
    pub dimension: usize,
    /// 距離メトリック
    pub metric: Metric,
    /// セグメント最大ベクトル数
    pub segment_max_vectors: usize,
    /// コンパクション閾値（削除率）
    pub compaction_threshold: f32,
    /// ベクトルエンコーディング
    pub encoding: VectorEncoding,
}

/// ベクトルエンコーディング
#[derive(Clone, Copy, Debug)]
pub enum VectorEncoding {
    /// Float32生データ
    Plain,
    /// ByteStreamSplit（浮動小数点最適化）
    ByteStreamSplit,
    /// 量子化（将来拡張）
    Quantized { bits: u8 },
}

impl VectorStoreManager {
    /// バッチ追記
    ///
    /// 大量のベクトルを効率的にカラムナセグメントとして追記。
    /// セグメント境界を超える場合は自動分割。
    pub async fn append_batch(
        &self,
        keys: &[Key],
        vectors: &[Vec<f32>],
        metadata: Option<&[RecordBatch]>,
    ) -> Result<AppendResult> {
        // 次元数検証
        for v in vectors {
            if v.len() != self.config.dimension {
                return Err(Error::DimensionMismatch {
                    expected: self.config.dimension,
                    actual: v.len(),
                });
            }
        }

        // ベクトルをカラムナ形式に変換
        let vector_column = self.encode_vectors(vectors)?;
        let key_column = self.encode_keys(keys)?;

        // セグメント分割（必要に応じて）
        let mut segments_created = Vec::new();
        let mut offset = 0;

        while offset < vectors.len() {
            let chunk_size = std::cmp::min(
                self.config.segment_max_vectors,
                vectors.len() - offset,
            );

            let segment = VectorSegment {
                segment_id: self.next_segment_id(),
                dimension: self.config.dimension,
                metric: self.config.metric,
                num_vectors: chunk_size as u64,
                vectors: vector_column.slice(offset, chunk_size),
                keys: key_column.slice(offset, chunk_size),
                deleted: Bitmap::new_zeroed(chunk_size),
                metadata: metadata.map(|m|
                    m.iter().map(|b| b.slice(offset, chunk_size)).collect()
                ),
                statistics: VectorSegmentStatistics {
                    active_count: chunk_size as u64,
                    deleted_count: 0,
                    deletion_ratio: 0.0,
                    norm_min: compute_min_norm(&vectors[offset..offset+chunk_size]),
                    norm_max: compute_max_norm(&vectors[offset..offset+chunk_size]),
                    created_at: current_timestamp(),
                },
            };

            let segment_id = self.write_segment(segment).await?;
            segments_created.push(segment_id);
            offset += chunk_size;
        }

        Ok(AppendResult {
            vectors_added: vectors.len() as u64,
            segments_created,
        })
    }

    /// ベクトルをByteStreamSplit形式でエンコード
    fn encode_vectors(&self, vectors: &[Vec<f32>]) -> Result<EncodedColumn> {
        let total_floats = vectors.len() * self.config.dimension;
        let mut flat: Vec<f32> = Vec::with_capacity(total_floats);

        for v in vectors {
            flat.extend_from_slice(v);
        }

        match self.config.encoding {
            VectorEncoding::Plain => {
                // 生バイト列として保存
                let bytes = bytemuck::cast_slice::<f32, u8>(&flat).to_vec();
                Ok(EncodedColumn {
                    encoding: EncodingV2::Plain,
                    compression: CompressionV2::Lz4,
                    data: self.compress(&bytes)?,
                    uncompressed_size: bytes.len() as u64,
                })
            }
            VectorEncoding::ByteStreamSplit => {
                // 浮動小数点最適化エンコーディング
                let encoded = byte_stream_split_encode(&flat);
                Ok(EncodedColumn {
                    encoding: EncodingV2::ByteStreamSplit,
                    compression: CompressionV2::Zstd,
                    data: self.compress(&encoded)?,
                    uncompressed_size: encoded.len() as u64,
                })
            }
            VectorEncoding::Quantized { bits } => {
                // 将来実装: スカラー量子化
                todo!("Quantized encoding not yet implemented")
            }
        }
    }
}

/// 追記結果
#[derive(Debug)]
pub struct AppendResult {
    pub vectors_added: u64,
    pub segments_created: Vec<u64>,
}
```

### 12.4 バッチ削除API

```rust
impl VectorStoreManager {
    /// バッチ削除（論理削除）
    ///
    /// 指定されたキーのベクトルを論理削除としてマーク。
    /// 物理削除はコンパクション時に実行。
    pub async fn delete_batch(&self, keys: &[Key]) -> Result<DeleteResult> {
        let key_set: HashSet<&Key> = keys.iter().collect();
        let mut deleted_count = 0u64;
        let mut segments_modified = Vec::new();

        // 全セグメントをスキャンして該当キーを論理削除
        let segment_ids = self.list_segments().await?;

        for segment_id in segment_ids {
            let mut segment = self.load_segment_header(segment_id).await?;
            let segment_keys = self.load_segment_keys(segment_id).await?;

            let mut modified = false;
            for (idx, key) in segment_keys.iter().enumerate() {
                if key_set.contains(key) && !segment.deleted.get(idx) {
                    segment.deleted.set(idx, true);
                    deleted_count += 1;
                    modified = true;
                }
            }

            if modified {
                // 統計更新
                segment.statistics.deleted_count += deleted_count;
                segment.statistics.active_count -= deleted_count;
                segment.statistics.deletion_ratio =
                    segment.statistics.deleted_count as f32 /
                    segment.num_vectors as f32;

                // 削除ビットマップと統計を永続化
                self.update_segment_deletion_state(segment_id, &segment).await?;
                segments_modified.push(segment_id);

                // コンパクション判定
                if segment.statistics.deletion_ratio >= self.config.compaction_threshold {
                    self.schedule_compaction(segment_id).await?;
                }
            }
        }

        Ok(DeleteResult {
            vectors_deleted: deleted_count,
            segments_modified,
        })
    }

    /// コンパクション（物理削除）
    ///
    /// 論理削除されたベクトルを物理的に除去し、
    /// セグメントを再構築。
    pub async fn compact_segment(&self, segment_id: u64) -> Result<CompactionResult> {
        let old_segment = self.load_full_segment(segment_id).await?;

        // 有効なベクトルのみ抽出
        let active_indices: Vec<usize> = (0..old_segment.num_vectors as usize)
            .filter(|&i| !old_segment.deleted.get(i))
            .collect();

        if active_indices.is_empty() {
            // 全て削除済み → セグメント削除
            self.delete_segment(segment_id).await?;
            return Ok(CompactionResult {
                old_segment_id: segment_id,
                new_segment_id: None,
                vectors_removed: old_segment.num_vectors,
                space_reclaimed: old_segment.vectors.data.len() as u64,
            });
        }

        // 新セグメント作成（有効ベクトルのみ）
        let new_segment = VectorSegment {
            segment_id: self.next_segment_id(),
            dimension: old_segment.dimension,
            metric: old_segment.metric,
            num_vectors: active_indices.len() as u64,
            vectors: old_segment.vectors.take_indices(&active_indices),
            keys: old_segment.keys.take_indices(&active_indices),
            deleted: Bitmap::new_zeroed(active_indices.len()),
            metadata: old_segment.metadata.map(|cols|
                cols.iter().map(|c| c.take_indices(&active_indices)).collect()
            ),
            statistics: VectorSegmentStatistics {
                active_count: active_indices.len() as u64,
                deleted_count: 0,
                deletion_ratio: 0.0,
                norm_min: old_segment.statistics.norm_min,
                norm_max: old_segment.statistics.norm_max,
                created_at: current_timestamp(),
            },
        };

        let new_segment_id = self.write_segment(new_segment).await?;
        let space_reclaimed = old_segment.vectors.data.len() as u64 -
            self.get_segment_size(new_segment_id).await?;

        // 旧セグメント削除
        self.delete_segment(segment_id).await?;

        Ok(CompactionResult {
            old_segment_id: segment_id,
            new_segment_id: Some(new_segment_id),
            vectors_removed: old_segment.statistics.deleted_count,
            space_reclaimed,
        })
    }
}

/// 削除結果
#[derive(Debug)]
pub struct DeleteResult {
    pub vectors_deleted: u64,
    pub segments_modified: Vec<u64>,
}

/// コンパクション結果
#[derive(Debug)]
pub struct CompactionResult {
    pub old_segment_id: u64,
    pub new_segment_id: Option<u64>,
    pub vectors_removed: u64,
    pub space_reclaimed: u64,
}
```

### 12.5 ベクトル検索（全スキャン）

```rust
impl VectorStoreManager {
    /// ベクトル検索（Flat Scan）
    ///
    /// 全セグメントをスキャンしてTop-K類似ベクトルを取得。
    /// SIMD最適化とセグメント並列処理により高速化。
    pub async fn search(
        &self,
        query: &[f32],
        top_k: usize,
        filter: Option<&Expr>,
    ) -> Result<Vec<ScoredItem>> {
        // 次元数検証
        if query.len() != self.config.dimension {
            return Err(Error::DimensionMismatch {
                expected: self.config.dimension,
                actual: query.len(),
            });
        }

        let segment_ids = self.list_segments().await?;

        // セグメント並列スキャン
        let partial_results: Vec<Vec<ScoredItem>> = self.parallel_executor
            .parallel_scan(segment_ids, |segment_id| {
                self.search_segment(segment_id, query, top_k, filter)
            })
            .await?;

        // 結果マージ（Top-K）
        let mut merged: Vec<ScoredItem> = partial_results
            .into_iter()
            .flatten()
            .collect();

        // スコア降順、キー昇順でソート
        merged.sort_by(|a, b| {
            b.score.total_cmp(&a.score)
                .then_with(|| a.key.cmp(&b.key))
        });

        merged.truncate(top_k);
        Ok(merged)
    }

    /// 単一セグメント内検索
    fn search_segment(
        &self,
        segment_id: u64,
        query: &[f32],
        top_k: usize,
        filter: Option<&Expr>,
    ) -> Result<Vec<ScoredItem>> {
        let segment = self.load_full_segment(segment_id).await?;
        let vectors = self.decode_vectors(&segment.vectors)?;
        let keys = self.decode_keys(&segment.keys)?;

        let mut results = Vec::with_capacity(top_k);

        // SIMD最適化スコアリング
        for i in 0..segment.num_vectors as usize {
            // 削除チェック
            if segment.deleted.get(i) {
                continue;
            }

            // フィルタ適用（メタデータ条件）
            if let Some(f) = filter {
                if !self.evaluate_filter(f, &segment.metadata, i)? {
                    continue;
                }
            }

            let vector = &vectors[i * self.config.dimension..(i + 1) * self.config.dimension];
            let score = self.compute_score_simd(query, vector)?;

            results.push(ScoredItem {
                key: keys[i].clone(),
                score,
            });
        }

        // セグメント内Top-K
        results.sort_by(|a, b| b.score.total_cmp(&a.score));
        results.truncate(top_k);

        Ok(results)
    }

    /// SIMD最適化スコア計算
    #[cfg(target_arch = "x86_64")]
    fn compute_score_simd(&self, query: &[f32], vector: &[f32]) -> Result<f32> {
        use std::arch::x86_64::*;

        match self.config.metric {
            Metric::Cosine => {
                // AVX2/AVX-512でベクトル化
                let (dot, q_norm, v_norm) = unsafe {
                    self.dot_and_norms_avx2(query, vector)
                };
                if q_norm == 0.0 || v_norm == 0.0 {
                    Ok(0.0)
                } else {
                    Ok(dot / (q_norm.sqrt() * v_norm.sqrt()))
                }
            }
            Metric::L2 => {
                // 負のL2距離（大きいほど近い）
                let dist_sq = unsafe { self.l2_distance_sq_avx2(query, vector) };
                Ok(-dist_sq.sqrt())
            }
            Metric::InnerProduct => {
                let dot = unsafe { self.dot_product_avx2(query, vector) };
                Ok(dot)
            }
        }
    }

    #[cfg(target_arch = "x86_64")]
    #[target_feature(enable = "avx2")]
    unsafe fn dot_product_avx2(&self, a: &[f32], b: &[f32]) -> f32 {
        let mut sum = _mm256_setzero_ps();
        let chunks = a.len() / 8;

        for i in 0..chunks {
            let offset = i * 8;
            let va = _mm256_loadu_ps(a.as_ptr().add(offset));
            let vb = _mm256_loadu_ps(b.as_ptr().add(offset));
            sum = _mm256_fmadd_ps(va, vb, sum);
        }

        // 水平加算
        let mut result = [0f32; 8];
        _mm256_storeu_ps(result.as_mut_ptr(), sum);
        let mut dot: f32 = result.iter().sum();

        // 残り要素
        for i in (chunks * 8)..a.len() {
            dot += a[i] * b[i];
        }

        dot
    }
}
```

### 12.6 KVSキーレイアウト（ベクトルセグメント）

```rust
/// ベクトルセグメント用KVSキー設計
pub mod vector_key_layout {
    /// プレフィックス定義
    pub const PREFIX_VECTOR_META: u8 = 0x20;
    pub const PREFIX_VECTOR_DATA: u8 = 0x21;
    pub const PREFIX_VECTOR_KEYS: u8 = 0x22;
    pub const PREFIX_VECTOR_DELETED: u8 = 0x23;
    pub const PREFIX_VECTOR_STATS: u8 = 0x24;
    pub const PREFIX_VECTOR_INDEX: u8 = 0x25;

    /// ベクトルコレクションメタデータキー
    /// Format: [PREFIX_VECTOR_META][collection_name_len:u16][collection_name:bytes]
    pub fn collection_meta_key(collection_name: &str) -> Vec<u8> {
        let mut key = Vec::with_capacity(3 + collection_name.len());
        key.push(PREFIX_VECTOR_META);
        key.extend_from_slice(&(collection_name.len() as u16).to_le_bytes());
        key.extend_from_slice(collection_name.as_bytes());
        key
    }

    /// ベクトルデータキー
    /// Format: [PREFIX_VECTOR_DATA][collection_id:u32][segment_id:u64]
    pub fn vector_data_key(collection_id: u32, segment_id: u64) -> Vec<u8> {
        let mut key = Vec::with_capacity(13);
        key.push(PREFIX_VECTOR_DATA);
        key.extend_from_slice(&collection_id.to_le_bytes());
        key.extend_from_slice(&segment_id.to_le_bytes());
        key
    }

    /// キーデータキー
    /// Format: [PREFIX_VECTOR_KEYS][collection_id:u32][segment_id:u64]
    pub fn keys_data_key(collection_id: u32, segment_id: u64) -> Vec<u8> {
        let mut key = Vec::with_capacity(13);
        key.push(PREFIX_VECTOR_KEYS);
        key.extend_from_slice(&collection_id.to_le_bytes());
        key.extend_from_slice(&segment_id.to_le_bytes());
        key
    }

    /// 削除ビットマップキー
    /// Format: [PREFIX_VECTOR_DELETED][collection_id:u32][segment_id:u64]
    pub fn deleted_bitmap_key(collection_id: u32, segment_id: u64) -> Vec<u8> {
        let mut key = Vec::with_capacity(13);
        key.push(PREFIX_VECTOR_DELETED);
        key.extend_from_slice(&collection_id.to_le_bytes());
        key.extend_from_slice(&segment_id.to_le_bytes());
        key
    }

    /// セグメントインデックスキー
    /// Format: [PREFIX_VECTOR_INDEX][collection_id:u32]
    pub fn segment_index_key(collection_id: u32) -> Vec<u8> {
        let mut key = Vec::with_capacity(5);
        key.push(PREFIX_VECTOR_INDEX);
        key.extend_from_slice(&collection_id.to_le_bytes());
        key
    }
}
```

### 12.7 インメモリモード

インメモリモードでは永続化のオーバーヘッドを排除し、ネイティブなデータ構造を直接利用する。

#### モード選択基準

| 条件 | 推奨モード | 理由 |
|------|-----------|------|
| データサイズ < 利用可能メモリ | インメモリ | オーバーヘッドなし、最高速 |
| 永続性不要（一時的分析） | インメモリ | I/O不要 |
| データサイズ > メモリ | 永続カラムナ | ディスクスピル対応 |
| 耐障害性必要 | 永続カラムナ | WAL + チェックポイント |
| 高頻度更新 | インメモリ + 定期フラッシュ | 書き込み性能優先 |

#### インメモリベクトルストア

```rust
/// インメモリベクトルストア（ネイティブ配列、エンコードなし）
pub struct InMemoryVectorStore {
    /// 次元数
    dimension: usize,
    /// 距離メトリック
    metric: Metric,
    /// ベクトルデータ（連続メモリ、生Float32）
    vectors: Vec<f32>,
    /// キー配列
    keys: Vec<Key>,
    /// 削除済みインデックス（Setで高速lookup）
    deleted: HashSet<usize>,
    /// キー→インデックスマップ（削除用）
    key_index: HashMap<Key, usize>,
}

impl InMemoryVectorStore {
    pub fn new(dimension: usize, metric: Metric) -> Self {
        Self {
            dimension,
            metric,
            vectors: Vec::new(),
            keys: Vec::new(),
            deleted: HashSet::new(),
            key_index: HashMap::new(),
        }
    }

    /// 追記（即座にメモリに反映、エンコードなし）
    pub fn append(&mut self, key: Key, vector: Vec<f32>) -> Result<()> {
        if vector.len() != self.dimension {
            return Err(Error::DimensionMismatch {
                expected: self.dimension,
                actual: vector.len(),
            });
        }
        let index = self.keys.len();
        self.key_index.insert(key.clone(), index);
        self.keys.push(key);
        self.vectors.extend(vector);
        Ok(())
    }

    /// バッチ追記
    pub fn append_batch(&mut self, keys: &[Key], vectors: &[Vec<f32>]) -> Result<()> {
        self.vectors.reserve(keys.len() * self.dimension);
        self.keys.reserve(keys.len());
        for (key, vector) in keys.iter().zip(vectors.iter()) {
            self.append(key.clone(), vector.clone())?;
        }
        Ok(())
    }

    /// 削除（論理削除）
    pub fn delete(&mut self, key: &Key) -> bool {
        if let Some(&index) = self.key_index.get(key) {
            self.deleted.insert(index);
            self.key_index.remove(key);
            true
        } else {
            false
        }
    }

    /// 検索（SIMD最適化、削除済みスキップ）
    pub fn search(&self, query: &[f32], top_k: usize) -> Result<Vec<ScoredItem>> {
        let mut results = Vec::with_capacity(self.keys.len() - self.deleted.len());
        for i in 0..self.keys.len() {
            if self.deleted.contains(&i) {
                continue;
            }
            let start = i * self.dimension;
            let vector = &self.vectors[start..start + self.dimension];
            let s = score(self.metric, query, vector)?;
            results.push(ScoredItem { key: self.keys[i].clone(), score: s });
        }
        results.sort_by(|a, b| b.score.total_cmp(&a.score));
        results.truncate(top_k);
        Ok(results)
    }

    /// コンパクション（削除済みを物理削除してメモリ回収）
    pub fn compact(&mut self) {
        if self.deleted.is_empty() { return; }
        let mut new_vectors = Vec::with_capacity(
            (self.keys.len() - self.deleted.len()) * self.dimension
        );
        let mut new_keys = Vec::new();
        let mut new_key_index = HashMap::new();

        for (i, key) in self.keys.iter().enumerate() {
            if !self.deleted.contains(&i) {
                let start = i * self.dimension;
                new_key_index.insert(key.clone(), new_keys.len());
                new_keys.push(key.clone());
                new_vectors.extend_from_slice(&self.vectors[start..start + self.dimension]);
            }
        }
        self.vectors = new_vectors;
        self.keys = new_keys;
        self.key_index = new_key_index;
        self.deleted.clear();
    }

    /// 永続カラムナモードへフラッシュ
    pub async fn flush_to_columnar(&self, store: &VectorStoreManager) -> Result<AppendResult> {
        let active: Vec<usize> = (0..self.keys.len())
            .filter(|i| !self.deleted.contains(i))
            .collect();
        let keys: Vec<Key> = active.iter().map(|&i| self.keys[i].clone()).collect();
        let vectors: Vec<Vec<f32>> = active.iter().map(|&i| {
            let start = i * self.dimension;
            self.vectors[start..start + self.dimension].to_vec()
        }).collect();
        store.append_batch(&keys, &vectors, None).await
    }

    /// メモリ使用量（バイト）
    pub fn memory_usage(&self) -> usize {
        self.vectors.len() * 4 + self.keys.iter().map(|k| k.len()).sum::<usize>()
    }
}
```

#### インメモリカラムナテーブル

```rust
/// インメモリカラムナテーブル（Arrow RecordBatch互換、エンコードなし）
pub struct InMemoryTable {
    schema: Arc<Schema>,
    batches: Vec<RecordBatch>,
    num_rows: usize,
}

impl InMemoryTable {
    pub fn new(schema: Schema) -> Self {
        Self { schema: Arc::new(schema), batches: Vec::new(), num_rows: 0 }
    }

    /// バッチ追記（即座にメモリに反映）
    pub fn append_batch(&mut self, batch: RecordBatch) -> Result<()> {
        self.num_rows += batch.num_rows();
        self.batches.push(batch);
        Ok(())
    }

    /// クエリ実行（ベクトル化、インメモリ最適化）
    pub fn query(&self, plan: &LogicalPlan) -> Result<DataFrame> {
        let optimized = optimize(plan)?;
        let physical = plan_to_physical_in_memory(&optimized)?;
        execute_in_memory(physical, &self.batches)
    }

    /// 永続カラムナモードへフラッシュ
    pub async fn flush_to_columnar(
        &self,
        storage: &ColumnarStorageManager,
        table_id: TableId,
    ) -> Result<SegmentId> {
        storage.write_segment(table_id, self.batches.clone()).await
    }
}
```

#### ハイブリッドモード（自動フラッシュ）

```rust
/// ハイブリッドストア（インメモリ + 自動フラッシュ）
pub struct HybridVectorStore {
    memory: InMemoryVectorStore,
    persistent: Arc<VectorStoreManager>,
    flush_threshold: usize,  // バイト
}

impl HybridVectorStore {
    /// 追記（メモリに蓄積、閾値超過で自動フラッシュ）
    pub async fn append(&mut self, key: Key, vector: Vec<f32>) -> Result<()> {
        self.memory.append(key, vector)?;
        if self.memory.memory_usage() >= self.flush_threshold {
            self.flush().await?;
        }
        Ok(())
    }

    /// 検索（メモリ + 永続を統合）
    pub async fn search(&self, query: &[f32], top_k: usize) -> Result<Vec<ScoredItem>> {
        let mem_results = self.memory.search(query, top_k)?;
        let persistent_results = self.persistent.search(query, top_k, None).await?;

        let mut merged = mem_results;
        merged.extend(persistent_results);
        merged.sort_by(|a, b| b.score.total_cmp(&a.score));
        merged.truncate(top_k);
        Ok(merged)
    }

    /// 手動フラッシュ
    pub async fn flush(&mut self) -> Result<()> {
        if self.memory.keys.is_empty() { return Ok(()); }
        self.memory.flush_to_columnar(&self.persistent).await?;
        self.memory = InMemoryVectorStore::new(
            self.memory.dimension,
            self.memory.metric,
        );
        Ok(())
    }
}
```

---

### 12.8 ベクトルストア設定

```rust
impl ColumnarConfig {
    /// ベクトルストア最適化プリセット（永続モード）
    pub fn vector_store(dimension: usize, metric: Metric) -> Self {
        Self {
            compression_level: CompressionLevel::Balanced,
            row_group_size: 100_000,
            segment_max_size: 512 * 1024 * 1024,
            parallelism: 0,
            batch_size: 1024,
            memory_limit: 2 * 1024 * 1024 * 1024,
            cache_size: 512 * 1024 * 1024,
            enable_stats_cache: true,
            enable_predicate_pushdown: true,
            enable_projection_pruning: true,
            enable_late_materialization: false,
        }
    }

    /// インメモリモードプリセット（永続化なし）
    pub fn in_memory() -> Self {
        Self {
            compression_level: CompressionLevel::Fast, // 未使用だが念のため
            row_group_size: usize::MAX,
            segment_max_size: usize::MAX,
            parallelism: 0,
            batch_size: 8192,  // 大きめバッチで効率化
            memory_limit: usize::MAX,
            cache_size: 0,  // キャッシュ不要（全てメモリ上）
            enable_stats_cache: false,
            enable_predicate_pushdown: false,  // インメモリでは不要
            enable_projection_pruning: false,
            enable_late_materialization: false,
        }
    }
}

/// ベクトルストア固有設定
impl VectorStoreConfig {
    /// 高スループットプリセット
    pub fn high_throughput(dimension: usize) -> Self {
        Self {
            dimension,
            metric: Metric::Cosine,
            segment_max_vectors: 1_000_000,
            compaction_threshold: 0.3,
            encoding: VectorEncoding::ByteStreamSplit,
        }
    }

    /// 高圧縮プリセット
    pub fn high_compression(dimension: usize) -> Self {
        Self {
            dimension,
            metric: Metric::Cosine,
            segment_max_vectors: 500_000,
            compaction_threshold: 0.2,
            encoding: VectorEncoding::ByteStreamSplit,
        }
    }
}
```

---

## 13. 参考資料

### 13.1 参考プロジェクト

| プロジェクト | 参考ポイント |
|-------------|-------------|
| DuckDB | SQL API、ベクトル化実行 |
| Polars | DataFrame API、Lazy評価 |
| DataFusion | クエリオプティマイザ、物理プラン |
| InfluxDB 3 | FDAPスタック、時系列最適化 |
| Arrow/Parquet | カラムナフォーマット、エンコーディング |

### 13.2 関連ドキュメント

- [design-spec.md](design-spec.md) - 全体設計
- [columnar-db-research.md](columnar-db-research.md) - カラムナDB調査資料
- [file-format-comparison.md](file-format-comparison.md) - ファイル形式比較

---

*最終更新: 2025-12-05*
