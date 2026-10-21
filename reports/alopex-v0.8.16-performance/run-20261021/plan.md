# v0.8.16 再測定の条件

Codexは、公開wheel `alopex==0.8.16` と、公開ソース `d9ff8783b8d18a63d167204e55902ea6cd90dcd1` の既存比較ハーネスを使う。CodexはSQLの操作列・結果消費と証跡保存のみを補正し、その差分を保存する。製品コードは変更しない。

| シナリオ | 既存の所有ハーネス・ケース | 実行 | 期待する結果 | 依存・生成量上限 |
|---|---|---|---|---|
| DataFrame eager | `parity_v0811_measure.py / polars-eager-api` | 下記runner、34,250行、3 warmups・21 samples | Polarsと完全結果一致、有限で正の時間 | Polars 1.43.2、出力10MB未満 |
| CSV / Parquet streaming | 同 / `polars-csv-streaming`, `polars-parquet-streaming` | 同条件、batch 8,192 | 行数・値の一致、完全消費時間 | 同、PyArrow、fixture20MB未満 |
| SQLite SQL | 同 / `sql-sqlite-curated` | 同条件、同じsavepoint操作・結果全消費 | 結果・rollback後state一致 | SQLite 3.46.1、メモリDB、出力10MB未満 |
| PostgreSQL SQL | 同 / `sql-postgresql-curated` | 同条件、結果全消費 | RETURNING全消費、rollback後state一致 | PostgreSQL 16.14、loopback、所有tmpfs512MB |
| SQL streaming | 同 / `sql-streaming` | 同条件 | 全結果の一致、完全消費時間 | DataFusion 50.0.0、出力10MB未満 |
| HNSW search | `hnsw_v0811_contract.py / build_*`, `measure_setting` | Amazon 9,171×128、seed42、200 queries、M16/efConstruction200、ef16/32/64/128/256、3 trials、各点最低10,000queriesかつ2秒 | recall付きの相対検索時間/QPS。recall未達は不合格として保持 | hnswlib0.8.0、Faiss1.15.0、NumPy2.4.6、dataset/embedding100MB未満、DB2GB未満 |

Codexは `scripts/performance/reproduce-v0816.py` から各engine/case/trialをfresh processで直列実行し、raw・終了状態を各case直後に保存する。全processはCPU0、数値ライブラリは1thread。PostgreSQLもCPU0へ固定する。Codexは各case後に容量を再計測し、所有DB/temporary filesを回収する。

Codexの容量baselineはworkspace約1.20GB。依存venv・fixture・所有DBを含む予定追加量は3GB未満、運用停止値は合計40GB、上限50GiBとする。Codexは他作業のprocess/container/cacheを変更しない。Codexは測定終了後、所有venv・取得wheel・入力・PostgreSQL containerを削除し、レビュー用JSON・raw・補正diffをdocsへ残す。

主表は「Alopex時間 / 参照時間」（小さいほど速い）と「Alopex throughput / 参照throughput」（大きいほど高い）。HNSWは同じefの表とrecallを揃えた表を区別する。HNSW build/update/deleteは永続化責務が違うため相対性能の主張から除く。PostgreSQLのclient RSSとserver全体のRSSを比較しない。SQL streamingのTTFBは行/batchの境界が違うため主表から除く。

Codexは今回の測定を単一ホストの公開Python API比較として扱う。Codexは全API互換、Rust API、分散性能、全ハードウェア、v0.8.15からの無劣化をこの測定から主張しない。性能差を合否に丸めず、失敗・未達と成功を併記する。
