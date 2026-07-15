# Rust製カラムナDB調査資料

## 概要

本資料では、Rust言語で実装された主要なカラムナ（列指向）データベースおよび関連ライブラリについて調査した結果をまとめる。

## 調査対象一覧

| プロジェクト | 種別 | 主な用途 | ライセンス |
|-------------|------|---------|-----------|
| InfluxDB 3 | 時系列DB | IoT, 監視, メトリクス | MIT/Apache 2.0 |
| DuckDB | 組み込みOLAP DB | 分析クエリ | MIT |
| Polars | DataFrame | データ分析, ETL | MIT |
| DataFusion | クエリエンジン | SQL処理, 分析基盤 | Apache 2.0 |
| arrow-rs | カラムナフォーマット | メモリ表現, 相互運用 | Apache 2.0 |

---

## 1. InfluxDB 3

### 概要

InfluxData社が開発する時系列データベースの第3世代。Goで実装されていた前バージョンから、Rustで完全に書き直された。

### FDAPスタック

InfluxDB 3は「FDAPスタック」と呼ばれるApacheプロジェクト群を基盤として構築されている：

| コンポーネント | 役割 |
|---------------|------|
| **F**light | 高効率なネットワークデータ転送 |
| **D**ataFusion | SQLオプティマイザ・実行エンジン |
| **A**rrow | 効率的なメモリ表現・高速計算 |
| **P**arquet | 高圧縮・高性能ストレージ |

※ 今後Apache Icebergが追加され「FIDAP」スタックになる予定

### 技術的特徴

- **言語**: Rust
- **カーディナリティ制限なし**: 前バージョンの制限を撤廃
- **SQLサポート**: 標準SQLでのクエリが可能
- **コンピュート/ストレージ分離**: オブジェクトストレージ活用
- **クエリ性能**:
  - Last-valueクエリ: 10ms未満
  - 1時間範囲クエリ: 50ms未満

### Rustを選択した理由

1. **パフォーマンス**: Go比で優れた実行速度
2. **メモリ安全性**: ガベージコレクションなしでの安全なメモリ管理
3. **Fearless Concurrency**: 並行処理の安全な実装
4. **DataFusionとの親和性**: 同じRustで書かれたDataFusionへの貢献が容易

### 参考リンク

- [InfluxDB 3 アーキテクチャ解説 (InfoQ)](https://www.infoq.com/articles/timeseries-db-rust/)
- [FDAPスタックについて (InfluxData)](https://www.influxdata.com/blog/flight-datafusion-arrow-parquet-fdap-architecture-influxdb/)
- [Rust採用の理由 (The New Stack)](https://thenewstack.io/influxdb-v3-why-rust-beat-go-for-time-series-database/)

---

## 2. DuckDB

### 概要

オランダのCWI（Centrum Wiskunde & Informatica）で開発された組み込み型OLAPデータベース。「SQLiteのOLAP版」として位置づけられる。

### 技術的特徴

- **言語**: C++（コア）、Rustバインディングあり
- **アーキテクチャ**: 組み込み型、プロセス内実行
- **カラムナストレージ**: 分析クエリに最適化
- **ベクトル化実行**: SIMD活用による高速処理
- **ゼロコピー**: Arrow形式との相互運用

### Rustバインディング (duckdb-rs)

公式Rustクライアントとして`duckdb-rs`が提供されている。

```toml
[dependencies]
duckdb = { version = "1.4.1", features = ["bundled"] }
```

#### 主要機能フラグ

| フラグ | 説明 |
|-------|------|
| `bundled` | DuckDBソースをバンドルしてビルド |
| `vtab` | カスタムテーブル関数のサポート |
| `vtab-arrow` | Arrow RecordBatchとの相互変換 |
| `vscalar` | カスタムスカラー関数 |
| `vscalar-arrow` | ベクトル化スカラー関数 |
| `modern-full` | chrono, serde_json, polars等の統合 |

#### 使用例

```rust
use duckdb::{Connection, Result};

fn main() -> Result<()> {
    let conn = Connection::open_in_memory()?;

    conn.execute_batch(
        "CREATE TABLE test (id INTEGER, name VARCHAR);
         INSERT INTO test VALUES (1, 'Alice'), (2, 'Bob');"
    )?;

    let mut stmt = conn.prepare("SELECT * FROM test WHERE id = ?")?;
    let rows = stmt.query_map([1], |row| {
        Ok((row.get::<_, i32>(0)?, row.get::<_, String>(1)?))
    })?;

    for row in rows {
        println!("{:?}", row?);
    }
    Ok(())
}
```

### 参考リンク

- [DuckDB公式](https://duckdb.org/)
- [duckdb-rs (GitHub)](https://github.com/duckdb/duckdb-rs)
- [DuckDB Ecosystem (MotherDuck)](https://motherduck.com/blog/duckdb-ecosystem-newsletter-november-2025/)

---

## 3. Polars

### 概要

Rustで書かれた高速DataFrameライブラリ。Pythonバインディングが広く使われているが、コアはRust実装。

### 技術的特徴

- **言語**: Rust
- **メモリモデル**: Apache Arrow
- **実行モデル**:
  - Eager API（即時実行）
  - Lazy API（遅延実行・クエリ最適化）
- **並列処理**: Rayonによるマルチスレッド実行
- **SIMD最適化**: ベクトル化演算

### パフォーマンス（2025年5月ベンチマーク）

AWS c7a.24xlarge（96 vCPU / 192GB）での計測結果：

| 比較対象 | Polarsの優位性 |
|---------|---------------|
| Pandas | 最大30倍以上高速 |
| Dask | 1桁以上高速 |
| PySpark | 1桁以上高速 |

#### 操作別パフォーマンス（vs Pandas）

| 操作 | 高速化率 |
|-----|---------|
| Join | 13.75倍 |
| Select | 10.90倍 |
| Sort | 11.7倍 |

### 新ストリーミングエンジン

2025年のアップデートで導入された新ストリーミングエンジンにより、インメモリエンジン比で3〜7倍の高速化を達成。

### Rustでの使用例

```rust
use polars::prelude::*;

fn main() -> Result<(), PolarsError> {
    let df = df! [
        "name" => ["Alice", "Bob", "Charlie"],
        "age" => [25, 30, 35],
        "score" => [85.5, 90.0, 78.5]
    ]?;

    // Lazy API でクエリ最適化
    let result = df.lazy()
        .filter(col("age").gt(lit(25)))
        .select([col("name"), col("score")])
        .collect()?;

    println!("{}", result);
    Ok(())
}
```

### 参考リンク

- [Polars公式](https://pola.rs/)
- [Polarsベンチマーク結果](https://pola.rs/posts/benchmarks/)
- [pola-rs (GitHub)](https://github.com/pola-rs/polars)

---

## 4. Apache DataFusion

### 概要

Apache Arrow上に構築されたRust製クエリエンジン。SQL/DataFrame APIを提供し、拡張性に優れる。

### 技術的特徴

- **言語**: Rust
- **実行モデル**: ストリーミング・マルチスレッド・ベクトル化
- **クエリ言語**: SQL、DataFrame API
- **データソース**: CSV, Parquet, JSON, Avro, カスタム
- **プランフォーマット**: Substrait対応

### アーキテクチャ

```
┌─────────────────────────────────────────────────┐
│                   SQL / DataFrame API            │
├─────────────────────────────────────────────────┤
│              Query Planner & Optimizer           │
├─────────────────────────────────────────────────┤
│           Execution Engine (Streaming)           │
├─────────────────────────────────────────────────┤
│                  Apache Arrow                    │
├─────────────────────────────────────────────────┤
│         Data Sources (Parquet, CSV, etc.)        │
└─────────────────────────────────────────────────┘
```

### 拡張ポイント

| 拡張機能 | 説明 |
|---------|------|
| TableProvider | カスタムデータソース |
| UDF | ユーザー定義スカラー関数 |
| UDAF | ユーザー定義集約関数 |
| UDWF | ユーザー定義ウィンドウ関数 |
| OptimizerRule | カスタム最適化ルール |
| ExecutionPlan | カスタム実行プラン |

### 関連プロジェクト

| プロジェクト | 説明 |
|-------------|------|
| DataFusion Python | Pythonバインディング |
| DataFusion Ray | Ray上での分散実行 |
| DataFusion Comet | Apache Sparkアクセラレータ |
| DataFusion Ballista | 分散クエリエンジン |

### 使用例

```rust
use datafusion::prelude::*;

#[tokio::main]
async fn main() -> datafusion::error::Result<()> {
    let ctx = SessionContext::new();

    // Parquetファイルをテーブルとして登録
    ctx.register_parquet("users", "users.parquet", ParquetReadOptions::default()).await?;

    // SQLクエリ実行
    let df = ctx.sql("SELECT name, age FROM users WHERE age > 25").await?;
    df.show().await?;

    Ok(())
}
```

### 参考リンク

- [DataFusion公式](https://datafusion.apache.org/)
- [DataFusion (GitHub)](https://github.com/apache/datafusion)
- [SIGMOD 2024 論文](https://dl.acm.org/doi/10.1145/3626246.3653368)

---

## 5. Apache Arrow (arrow-rs)

### 概要

Apache Arrowの公式Rust実装。カラムナフォーマットのメモリ表現とそれに対する操作を提供する。

### 技術的特徴

- **言語**: Rust
- **目的**: カラムナデータの低レベル操作
- **リリースサイクル**: 約1ヶ月ごと
- **最新バージョン**: v57.0.0（2025年10月）

### クレート構成

| クレート | 説明 |
|---------|------|
| `arrow` | Arrowカラムナフォーマット実装 |
| `parquet` | Parquetファイル読み書き |
| `arrow-flight` | Arrow Flightプロトコル |
| `arrow-avro` | Avroフォーマット対応（新規追加） |
| `parquet-variant` | Variant型サポート |

### 配列型

Arrow Columnar Formatで定義されるすべての配列型を静的型付きで実装：

```rust
use arrow::array::{Int32Array, StringArray, Float64Array};

// 数値配列
let int_array = Int32Array::from(vec![1, 2, 3, 4, 5]);

// 文字列配列（Nullable）
let str_array = StringArray::from(vec![Some("hello"), None, Some("world")]);

// 浮動小数点配列
let float_array = Float64Array::from(vec![1.0, 2.5, 3.14]);
```

### v57.0.0の新機能（2025年10月）

1. **arrow-avro クレート**: Avroデータを直接Arrowカラムナ形式に変換
2. **Variant型サポート**: Parquetの新しい半構造化データ型
3. **Thriftパーサー高速化**: Parquetメタデータパース4倍高速化

### 参考リンク

- [arrow-rs (GitHub)](https://github.com/apache/arrow-rs)
- [arrow-rs ドキュメント](https://arrow.apache.org/rust/arrow/index.html)
- [v57.0.0 リリースノート](https://arrow.apache.org/blog/2025/10/30/arrow-rs-57.0.0/)

---

## 6. その他のライブラリ

### columnar

Frank McSherry氏による高スループットカラムナシリアライゼーションライブラリ。

- **目的**: ベクトルの「転置」（Struct of Arrays変換）
- **特徴**: パディングなしのメモリ再パック、可変長整数圧縮
- **リポジトリ**: [frankmcsherry/columnar](https://github.com/frankmcsherry/columnar)

### column-rs

ベクトルをカラムナ形式で表現するためのライブラリ。

- **目的**: 大量要素のイテレーションで一部フィールドのみ参照する場合に有効
- **リポジトリ**: [antiguru/column-rs](https://github.com/antiguru/column-rs)

---

## alopex-dbへの示唆

### 採用候補技術

| 用途 | 推奨技術 | 理由 |
|-----|---------|------|
| メモリ表現 | arrow-rs | 標準的なカラムナフォーマット、エコシステムとの互換性 |
| ファイルフォーマット | parquet | 圧縮効率、分析クエリ性能 |
| クエリエンジン | DataFusion | 拡張性、Rustネイティブ |
| 分析クエリ | DuckDB (バインディング) | 成熟したOLAPエンジン |

### 設計上の考慮事項

1. **FDAPスタックの参考**: InfluxDB 3のアーキテクチャは時系列DBの設計として参考になる
2. **ストリーミング実行**: DataFusionのストリーミング実行モデルは大規模データ処理に有効
3. **拡張性**: DataFusionの拡張ポイント（TableProvider, UDF等）は柔軟な設計を可能にする
4. **Arrowの活用**: ゼロコピーでのデータ共有、他システムとの相互運用性

---

## 参考文献

1. [Engineering a Time Series Database Using Open Source (InfoQ)](https://www.infoq.com/articles/timeseries-db-rust/)
2. [FDAP Architecture (InfluxData)](https://www.influxdata.com/blog/flight-datafusion-arrow-parquet-fdap-architecture-influxdb/)
3. [Polars Benchmarks 2025](https://pola.rs/posts/benchmarks/)
4. [DataFusion SIGMOD 2024](https://dl.acm.org/doi/10.1145/3626246.3653368)
5. [arrow-rs v57.0.0](https://arrow.apache.org/blog/2025/10/30/arrow-rs-57.0.0/)
6. [DuckDB Ecosystem (MotherDuck)](https://motherduck.com/blog/duckdb-ecosystem-newsletter-november-2025/)

---

*最終更新: 2025年12月*
