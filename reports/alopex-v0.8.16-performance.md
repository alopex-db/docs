# Alopex v0.8.16 性能比較

本レポートは、v0.8.16の公開Python wheelを既存の製品比較ハーネスで再測定し、参照製品・ライブラリを1とする相対値を示す。初回測定日は2026年10月21日、書込・KV・DataFrame区分別の追加測定日は10月22日（JST）。対象は単一ホストのPython APIであり、Rust APIや分散処理の比較は含まない。

## 再測定の結果

全45 worker processは正常終了し、DataFrame / SQLの全6ケースで製品間・trial間の結果checksumが一致した。これらの成功は実行と結果照合を示すが、PostgreSQLとの比較成立を示さない。PostgreSQL比較はAlopex embeddedとPostgreSQL serverで実行境界が異なるため無効とし、両製品のserver/client APIによる再測定では、Alopex serverが既存の複合ケースの`DROP SEQUENCE`を拒否した。この複合ケースは未成立だが、独立した読取SQLは比較できる。HNSWの全45設定点もrecall 0.99以上を満たした。

Alopexの所要時間は、SQLite curatedで参照の**9.551倍**、DataFusion SQL streamingで**46.522倍**だった。旧Polars複合操作列の**0.135倍**は構築・計算・Python変換を含み、計算だけの速度比ではない。追加の区分別測定では、構築はPolarsの**0.033倍**だが、計算は**1.645倍**だった。HNSWはrecall≥0.99の最速点で、hnswlibの**3.015倍**、Faiss HNSWの**2.683倍**の検索時間だった。今回の固定ケースでは、SQL streamingとSQLite curatedが相対的に大きな差として表れた。

以下の「時間比」は **Alopex / 参照**で、小さいほど速い。「処理量比」は同じ仕事量に対する **Alopex / 参照**で、大きいほど高い。参照製品をすべて1.000とする。

独立したserver/client SQL比較では、Alopexの時間比はPostgreSQLに対してCOUNTが**13.501倍**、16行SELECTが**27.132倍**、17,125行の全結果取得が**5.715倍**だった。読取3ケースは全て比較が成立した。INSERT＋rollbackの時間比は**1.794倍**だった。Codexは既知の`DROP SEQUENCE`不具合を既定でスキップし、これらの性能集計から除外する。

### DataFrame / SQL

| 既存ケース | 比較対象 | 時間比 ↓ | 処理量比 ↑ | trial別時間比の範囲 |
|---|---|---:|---:|---:|
| 旧DataFrame複合操作（構築込み） | Polars | 0.135 | 7.380 | 0.107–0.162 |
| CSV streaming 全消費 | Polars | 2.301 | 0.435 | 1.329–2.853 |
| Parquet streaming 全消費 | Polars | 1.039 | 0.962 | 0.674–1.160 |
| SQL curated 複合操作 | SQLite | 9.551 | 0.105 | 8.505–11.051 |
| SQL curated 複合操作 | PostgreSQL | この複合ケースは不成立（server実装漏れ） | — | — |
| SQL streaming 全消費 | DataFusion | 46.522 | 0.021 | 45.569–48.608 |

Parquetの時間比は1をまたぐ幅があり、この3 trialsから優劣を断定しない。PostgreSQL行は、server/client APIを揃えた事前検証の失敗により比較不成立とする。旧時間比0.051倍はAlopexの性能優位を示す結論から除外する。

### HNSW：recall基準を満たす最速点

各製品について、測定した5つのefからrecall基準を全3 trialsで満たす最大QPSの点を選んだ。0.95と0.99の両基準で、全製品の選択点はef=16だった。

| 比較対象 | recall基準 | Alopex ef / 参照 ef | 時間比 ↓ | QPS比 ↑ | Alopex recall / 参照 recall（最小値） |
|---|---:|---:|---:|---:|---:|
| hnswlib | ≥0.95 | 16 / 16 | 3.015 | 0.383 | 0.9975 / 0.9980 |
| hnswlib | ≥0.99 | 16 / 16 | 3.015 | 0.383 | 0.9975 / 0.9980 |
| faiss-hnsw | ≥0.95 | 16 / 16 | 2.683 | 0.419 | 0.9975 / 0.9965 |
| faiss-hnsw | ≥0.99 | 16 / 16 | 2.683 | 0.419 | 0.9975 / 0.9965 |

時間比は検索1回のp50の比、QPS比は各trialの実測queries/secondの中央値の比である。QPSは全呼び出し時間とloop overheadも含むため、p50比の逆数とは一致しない。

### HNSW：同じefでの比較

| 比較対象 | ef | 時間比 ↓ | QPS比 ↑ | trial別時間比の範囲 | Alopex recall / 参照 recall（最小値） |
|---|---:|---:|---:|---:|---:|
| hnswlib | 16 | 3.015 | 0.383 | 2.808–3.341 | 0.9975 / 0.9980 |
| hnswlib | 32 | 2.630 | 0.434 | 2.365–2.761 | 0.9990 / 0.9990 |
| hnswlib | 64 | 2.585 | 0.400 | 2.408–2.585 | 0.9995 / 0.9995 |
| hnswlib | 128 | 2.662 | 0.356 | 2.206–2.737 | 0.9995 / 0.9995 |
| hnswlib | 256 | 2.278 | 0.462 | 2.029–2.476 | 0.9995 / 0.9995 |
| faiss-hnsw | 16 | 2.683 | 0.419 | 2.439–3.551 | 0.9975 / 0.9965 |
| faiss-hnsw | 32 | 2.596 | 0.392 | 2.399–2.667 | 0.9990 / 0.9985 |
| faiss-hnsw | 64 | 2.367 | 0.430 | 2.311–2.872 | 0.9995 / 0.9995 |
| faiss-hnsw | 128 | 2.383 | 0.403 | 2.285–2.832 | 0.9995 / 0.9995 |
| faiss-hnsw | 256 | 2.022 | 0.513 | 2.003–2.486 | 0.9995 / 0.9995 |

## 追加評価：書込・ランダムアクセス・KV

CodexはSQLの耐久write・random point readを6ケース、embedded KVをLMDBと比較する8ケース、DataFrameの区分別比較を4ケース追加した。全108 process・2,268 samplesは成功し、各ケースの入力と完全な結果が製品間・全3 trialsで一致した。以下は主な結果であり、[全18ケースの表・条件・再実行手順](alopex-v0.8.16-performance/run-20261022-write-kv/report.md)に全数値と証跡をまとめる。

| API境界・ケース | 比較対象 | 時間比 ↓ |
|---|---|---:|
| SQL server/client・単件INSERT＋commit | PostgreSQL | 2.145 |
| SQL server/client・100行INSERT＋commit | PostgreSQL | 3.347 |
| SQL server/client・random get hit | PostgreSQL | 2.472 |
| SQL server/client・random get miss | PostgreSQL | 2.643 |
| SQL server/client・random UPDATE＋commit | PostgreSQL | 2.524 |
| SQL server/client・random DELETE＋commit | PostgreSQL | 50.053 |
| embedded KV・単件PUT＋commit | LMDB | 0.466 |
| embedded KV・順次100件PUT＋commit | LMDB | 0.778 |
| embedded KV・100件の投入順shuffle＋commit | LMDB | 0.782 |
| embedded KV・random get hit | LMDB | 6.700 |
| embedded KV・random get miss | LMDB | 1.334 |
| embedded KV・random overwrite＋commit | LMDB | 0.415 |
| embedded KV・random DELETE＋commit | LMDB | 0.455 |
| embedded KV・範囲1,000件の全値取得 | LMDB | 17.538 |

Codexは初期10,000件の専用データを使い、writeは明示beginから永続commit完了までを計測した。KVは10byte key・32byte value、read transactionの開始・終了も含み、最後のclose/reopen後に全key/valueを照合した。SQLは32文字TEXTとINTEGER主キーで、各sampleと新しいclient接続からの最終全件を照合した。SQLserver再起動による耐久性試験は行っていない。両群は同じhost filesystemを使い、KVはAlopexのWAL force-syncとLMDBのsync/metasync有効を確認した。

今回のrandomアクセスはwarm cacheでのAPI応答性能であり、cold disk I/O、並行負荷、メモリを超える規模の評価ではない。SQLとKVはそれぞれ同じ責務の製品と比較し、両API境界の倍率を混ぜない。既知のDROP SEQUENCEは実行していない。SQL random DELETEとKV point read/rangeの差は[性能改善Issue #712](https://github.com/alopex-db/alopex/issues/712)の調査対象とする。

## Polars互換：DataFrameを明示構築しない入口

Codexはトップレベル関数・Series演算と、CSV／ParquetからのLazy実行も評価対象に追加した。**公開Alopex v0.8.16は、今回確認した6つの入口・操作でPolars互換を満たしていない。** moduleのselect／scan_csv／scan_parquet、Series直接構築・加算、LazyFrame直接構築が未対応だった。先行のDataFrame構築経由の測定だけを根拠に、これらの互換APIも比較済みとは扱わない。

Codexは利用できるLazyFrameのstatic scanとPolarsのトップレベルscanから、DataFrameの明示構築を挟まずに同じ計算を実行した。この比較はファイル読み込みを含み、全sampleで全値・Python型・NULL・列順・行順を照合する。Parquetの文字列連結はUtf8／LargeUtf8の型不一致で失敗したため倍率を与えず、数値のみの独立ケースを比較した。同名入口の不足と、この別名経路の機能・性能比較は分けて判定する。

Codexは[入口別の不足・Lazy計算の相対値・証跡](alopex-v0.8.16-performance/run-20261022-polars-entrypoints/report.md)を追加した。Polars互換という目標は維持し、Codexは未対応の入口を評価対象から除外しない。

最終確認runでの時間比は、CSVの12列計算＋collectがPolarsの1.916倍、全batch取得が1.945倍だった。Parquetの数値等11列ではcollectが0.819倍、全batch取得が0.857倍だった。全24性能process・504測定sampleは成功したが、Parquetの文字列計算は別途機能失敗として保持し、成功した数値計算と混ぜない。

## DataFrame：旧0.135倍と計算性能の区別

旧比較は、**両製品ともメモリ上のデータからDataFrameを構築する時間を含む**。ファイルからのデータロードは含まない。Codexは旧最終12列と返却tupleを独立Python oracleから再生成し、保存された全6 processのchecksumと一致することを確認した。旧計測は空結果や未評価planだけを測ったものではないが、explode/concatは件数だけ、next_idは未使用、全sampleの中間値は未照合だった。

Codexは同じ34,250行について構築・計算・Python変換を分離し、全warmup/sampleで入力全列・next_id・explode・concat・最終12列の型、NULL、順序、全値を独立oracleへ照合した。

| 新しい比較区分（Polars=1） | 時間比 ↓ | trial別時間比の範囲 |
|---|---:|---:|
| 事前生成PythonデータからのDataFrame構築 | 0.033 | 0.030–0.033 |
| 構築済みDataFrameからの12列計算・collect | 1.645 | 1.627–1.766 |
| 計算済み結果のPython dictへの変換 | 0.987 | 0.959–1.032 |
| 構築＋全中間結果・最終結果の具体化 | 0.277 | 0.269–0.278 |

**構築はAlopexが速い一方、今回の計算区分はPolarsが速い。旧0.135倍から計算性能の優位を主張しない。** Python変換の幅は1をまたぐため優劣を断定しない。新しい全体区分は旧ケースより多くの結果を具体化するので、0.135→0.277を同じ仕事量での改善・退行とは扱わない。Codexは両製品の論理型の対応を確認したが、内部の物理表現を同一とは主張しない。filterは全行通過の固定ケースであり、一般的な全DataFrame演算への優位は主張しない。

[区分ごとの厳密な計測範囲と再実行](alopex-v0.8.16-performance/run-20261022-write-kv/report.md)と[機能回帰・旧比較の監査記録](alopex-v0.8.16-performance/run-20261022-write-kv/verification.json)を参照する。

## PostgreSQL：独立した読取・書込ケース

Codexは既存ハーネスのfixtureとSQLを使い、読取3ケースとINSERT＋rollbackを個別に再測定した。両製品のAPIはserver/client境界で揃えた。機能が成立するケースの比較は、既存の複合ケースにある`DROP SEQUENCE`の修正を待つ必要がない。

| 独立ケース | PostgreSQLを1とする時間比 ↓ | 処理量比 ↑ | trial別時間比の範囲 |
|---|---:|---:|---:|
| COUNT、enabled=trueの17,125行を集計 | 13.501 | 0.074 | 12.862–15.265 |
| ORDER BY id LIMIT 16 | 27.132 | 0.037 | 25.378–31.539 |
| 偶数IDの17,125行を全結果取得 | 5.715 | 0.175 | 4.454–6.082 |
| begin・INSERT RETURNING・rollback | 1.794 | 0.557 | 1.282–1.884 |

全24 performance processと504 samplesは成功し、各ケースの全3 trials・製品間で結果checksumが一致した。Codexは値・型を照合し、順序付きSELECTは順序、全結果取得は重複も含めた全行を計測外で検証した。時間比は各processのp50を3 trialsで中央値にした値の比率であり、複数SQLケースをまとめた総合倍率ではない。

| 条件 | 設定 |
|---|---|
| 製品・クライアント | 公開alopex-server 0.8.16＋公開alopex 0.8.16のRemoteDatabase対PostgreSQL 16.14＋psycopg 3.2.10 |
| API境界 | Alopex execute_sql対PostgreSQL execute＋fetchall。両群とも列名付きPython行を全取得し、既存接続を再利用 |
| 入力 | 読取は既存34,250行fixture。書込は既存curatedの1行perf_items fixtureに対するINSERT RETURNING＋rollback |
| 実行 | 同一ホストloopback、server CPU0 / client CPU1、数値thread1、TLS/authなし、3 warmups / 21 samples / 3 trials |
| 設定 | 両serverは同じhost filesystemへ永続化。PostgreSQLはfsync / synchronous_commit有効、並列query無効、クライアントの自動prepared statement化を無効 |
| 計測範囲 | 接続生成・fixture投入・結果照合は計測外。request/responseと全結果取得を計測内。書込ケースはtransaction begin/rollbackも計測内 |
| 既知不具合 | runnerはDROP SEQUENCEを既定でスキップ。再実行者が明示的に--case drop-sequenceを指定した場合だけ診断として実行 |

全結果取得のSQLは既存`SQL_STREAM_QUERY`だが、この比較はbufferedなexecute_sql/fetchallによるもので、streaming API同士の比較ではない。書込ケースは永続commitを測定していない。HTTPとPostgreSQL wireの違いも時間に含むため、今回の数値はクライアントから見たSQL応答性能であり、engine内部だけの差ではない。rawのclient RSSはserverを含まず、製品全体のメモリ比較には使わない。

Codexは[相対値](alopex-v0.8.16-performance/run-20261021-sql-isolated/relative.json)、[raw照合結果](alopex-v0.8.16-performance/run-20261021-sql-isolated/result-verification.json)、[実行環境](alopex-v0.8.16-performance/run-20261021-sql-isolated/environment.json)、[サーバー識別・設定](alopex-v0.8.16-performance/run-20261021-sql-isolated/packages.json)、[公開wheel照合](alopex-v0.8.16-performance/run-20261021-sql-isolated/client-package.json)を保存した。Codexはスキップ指示前に実行した既知DDLの診断を監査用に保持するが、性能集計には含めず、再試行もしない。Codexは以前のrunとrawを変更しない。

再実行者は公開ソース`d9ff8783b8d18a63d167204e55902ea6cd90dcd1`と公開クライアントを用意し、上記条件で両serverを起動する。再実行者は`ALOPEX_PERF_SERVER_URL`と`ALOPEX_PERF_POSTGRES_DSN`を設定し、[server-sql-isolated-v0816.py](../scripts/performance/server-sql-isolated-v0816.py)を実行する。今回の独立ケースは元ソースのfixture生成・SQL定数を使い、harness.patchは必要としない。ordered SELECTのCOALESCE列には、両APIで列名を揃えるためAS valueを追加した。

```bash
rtk proxy python -B scripts/performance/server-sql-isolated-v0816.py --harness-root <alopex-checkout> --output <new-run-directory>
```

[事前計画と測定中の指示変更](alopex-v0.8.16-performance/run-20261021-sql-isolated/plan.md)と[回帰検証](alopex-v0.8.16-performance/run-20261021-sql-isolated/harness-verification.json)は、条件・既定スキップ・失敗履歴を記録する。再実行者は新しいrun directoryを使い、既存結果を上書きしない。

### 既存複合ケースの訂正履歴

Codexは、Alopex embedded対PostgreSQL serverの旧時間比**0.051倍を撤回する**。CodexはAlopexも公開サーバーと`alopex.RemoteDatabase`で起動し、PostgreSQLの`psycopg`と同じ既存操作列を実行した。Alopex server v0.8.16はfixture準備の`DROP SEQUENCE IF EXISTS perf_sequence`を`unsupported query plan: DropSequence`で拒否した。PostgreSQL 16.14は同じ事前検証の6項目を通過した。

この結果は**server側SQL実行経路の実装漏れによる比較不成立**であり、性能の合否や倍率ではない。この複合ケースではCodexは時間測定を開始しておらず、未実行のSQL操作の対応状況も断定しない。[不具合Issue #720](https://github.com/alopex-db/alopex/issues/720)はサーバー側の機能修正と回帰検証を所有する。[性能改善Issue #712](https://github.com/alopex-db/alopex/issues/712)は元の4対象の性能改善を所有し、この機能修正を受入条件に含めない。評価担当者はこの複合ケースの機能同等性を確認してから同ケースの時間比を測定する。独立した読取SQLの比較はこの修正を前提にしない。

| 再評価の条件 | 設定 |
|---|---|
| Alopex server | 公開`alopex-server 0.8.16` crate、`cargo install --locked`のrelease profile、製品コード変更なし |
| クライアント | 公開`alopex==0.8.16`の`RemoteDatabase`（HTTP、keep-alive有効）対`psycopg==3.2.10`（PostgreSQL wire、既存接続を再利用） |
| 配置 | 同一ホストのloopback、server CPU0 / client CPU1、TLS・認証なし |
| 永続化 | 両製品とも同じホストfilesystemのdisk。PostgreSQLはfsync / synchronous_commit有効、並列query無効。Alopexは標準の永続ストレージ設定 |
| 予定した計測 | 接続生成・fixture投入は計測外。request/response、結果の完全消費、transaction begin/rollbackは計測内。34,250行、3 warmups / 21 samples、3 trials |
| 実行結果 | Alopex事前検証失敗、PostgreSQL事前検証成功、時間測定0件、相対値なし |

HTTPとPostgreSQL wireは異なるprotocolであり、この境界を揃えた場合でも結果はクライアントから見た応答性能となる。Codexは純粋なengine演算時間とは区別する。

Codexの[事前計画](alopex-v0.8.16-performance/run-20261021-server/plan.md)、[判定](alopex-v0.8.16-performance/run-20261021-server/comparison-status.json)、[Alopex診断](alopex-v0.8.16-performance/run-20261021-server/preflight-alopex-server-trial0.stderr.txt)、[PostgreSQL検証](alopex-v0.8.16-performance/run-20261021-server/postgresql-preflight-reference.json)、[サーバーパッケージ識別](alopex-v0.8.16-performance/run-20261021-server/server-package.json)は失敗を含めて保持する。

再実行者は既存`harness.patch`に続いて[server-connection.patch](alopex-v0.8.16-performance/run-20261021-server/server-connection.patch)を適用し、両サーバーを上記条件で起動する。[server-compare-v0816.py](../scripts/performance/server-compare-v0816.py)はembeddedへのフォールバックを拒否し、事前検証が成功した場合だけ既存ケースを測定する。再実行者は`ALOPEX_PERF_SERVER_URL`と`ALOPEX_PERF_POSTGRES_DSN`を設定し、次を実行する。

```bash
rtk proxy python -B scripts/performance/server-compare-v0816.py --harness-root <alopex-checkout> --output <new-run-directory>
```

## 元runの比較条件

| 項目 | 条件 |
|---|---|
| Alopex | PyPI `alopex==0.8.16`、公開ソース `d9ff8783b8d18a63d167204e55902ea6cd90dcd1` |
| ホスト | AMD Ryzen 5 3500U、Linux x86_64 / WSL2、論理8 CPU |
| CPU・スレッド | 各workerをCPU0に固定、数値ライブラリを1threadに制限。PostgreSQL serverもCPU0 |
| Python | 3.11.11 |
| DataFrame参照 | Polars 1.43.2 |
| SQL参照 | SQLite 3.46.1（pysqlite3-binary 0.5.4）、PostgreSQL 16.14、DataFusion 50.0.0 |
| ANN参照 | hnswlib 0.8.0、Faiss CPU 1.15.0 |
| 反復 | engine/case/trialごとfresh process、3 trials、製品順を交代。全caseを直列実行 |

Codexは公開wheelのSHA-256と導入済みパッケージ12ファイルの一致を確認した。[package.json](alopex-v0.8.16-performance/run-20261021/package.json)はwheelの識別情報、[environment.json](alopex-v0.8.16-performance/run-20261021/environment.json)と[依存一覧](alopex-v0.8.16-performance/run-20261021/requirements-freeze.txt)は実行環境を記録する。ホストは共有環境であり、CPU固定は他プロセスを排除する専有割当ではない。

## 既存ケースと測定境界

DataFrame / SQLの元ハーネスは [`parity_v0811_measure.py`](https://github.com/alopex-db/alopex/blob/d9ff8783b8d18a63d167204e55902ea6cd90dcd1/scripts/performance/parity_v0811_measure.py)。ファイル名のv0811は既存ハーネスの識別子であり、今回の測定対象は公開版v0.8.16である。

| ケース | 固定入力と計測範囲 |
|---|---|
| DataFrame eager | 34,250行、数値/文字列/リスト列。構築・変換・演算・explode・concat・結果のPython変換を含む既存複合操作列 |
| CSV / Parquet streaming | 同じ34,250行、8,192行batch。scan開始から全batchの消費まで。warm cache、各processで3 warmups / 21 samples |
| SQLite curated | 同じ34,250行のcount・並び順付きSELECT・transaction・savepoint・prepared query・制約付きINSERTの複合操作列 |
| PostgreSQL curated（旧比較は無効） | 同じ34,250行を準備し、EXPLAIN・RETURNING・UPSERT・sequence・transactional DDL・MERGE・joined DML・catalog queryを含む既存操作列。旧runはAlopex embedded API対PostgreSQL client/server APIで、PostgreSQL側のみ既存接続上のrequest/response往復を含んだ。接続生成は計測外 |
| SQL streaming | 同じ34,250行から偶数IDの17,125行を返すSELECT。開始から全結果を消費するまで |
| HNSW search | 固定Amazonデータの9,171×128 float32、seed42、200 query vectors、cosine。M16 / efConstruction200、efSearch16/32/64/128/256。各trial・設定で最低10,000 queriesかつ最低2秒、全queryのwarmup後に測定 |

HNSWの元ハーネスは [`hnsw_v0811_contract.py`](https://github.com/alopex-db/alopex/blob/d9ff8783b8d18a63d167204e55902ea6cd90dcd1/scripts/performance/hnsw_v0811_contract.py)。Codexは既存のembedding生成・oracle・engine builder・`measure_setting`をそのまま使い、各engineを独立processで実行した。検索時間はPython呼び出しとtop-10のID取得までを含む。構築時間は検索の相対値に含めない。

Polars eagerのケースはメモリ上のデータ構築・変換・演算を測り、永続データの読取・書込を含まない。一方、CSV / Parquet streamingはファイル読取と全結果消費を含む。PostgreSQL比較でも、独立した読取SQLの計測に書込やDDLの実行成功を要求する必要はない。

## 結果の照合とハーネス補正

既存SQLハーネスには、SQLite側だけがsavepointを実行し、参照製品側のSELECT / RETURNING結果を全消費しない差があった。CodexはAlopexの既存Transaction APIにも同じsavepoint操作を追加し、参照製品のcursorを全消費した。製品コードは変更していない。

Codexは計測外でDataFrameの全結果checksum、SQL streamingの全値、SQLの初期データとrollback後の状態を確認した。各製品対・trial間のchecksum一致も確認する。SQLのRETURNINGは全消費の対象であり、個々の返却値の網羅的互換性試験は今回の計測範囲に含まない。HNSWのrecallは同じ入力の独立したexact oracleに対するtop-10の一致率である。

[harness.patch](alopex-v0.8.16-performance/run-20261021/harness.patch)はこの補正、raw sample保存、回帰試験をまとめた差分である。補正の新規6テストと既存16テスト、実wheelの20行・6ケースの比較確認は成功した。初回回帰の4失敗と既存test adapterの1エラーは補正で解消し、[検証記録](alopex-v0.8.16-performance/run-20261021/harness-verification.json)に保持した。

## 解釈できる範囲

- 相対時間は各processの中央値を3 trialsで再度中央値にした値の比率。trialごとの比率幅も示す。統計的有意差や本番SLOを認定する試験ではない。
- DataFrame eager / curated SQLのthroughputは既存の複合操作列の周回速度。単独SQLのQPSや一般的な全APIの性能を表さない。
- PostgreSQLの旧比較は実行境界が異なるため無効であり、優劣の判断に使わない。CodexはAlopexもserver/client APIへそろえて実行したが、Alopex server側の実装漏れにより、この複合ケースの性能測定へ進めなかった。
- SQL streamingはAlopexがPython行、DataFusionがArrow batchを返す。完全消費時間には各APIの返却形式のコストが含まれる。最初の1行と最初の1batchの到着時間は別の境界なので相対表に含めない。
- HNSWの構築・更新・削除はAlopexの永続transactionと参照ライブラリのmemory indexで責務が異なる。保存サイズも割当disk blocksとserialized bytesの違いがあるため、これらの直接倍率を性能結論に使わない。
- rawのRSSはprocess全体の最大値で、初期化・結果照合も含む。PostgreSQL clientの値はserverを含まない。raw保存によるI/Oもあるため、`temporary_io_bytes`を製品I/Oの比較に使わない。
- 本レポートは1つの固定データ規模・1ホスト・公開Python APIの測定である。旧v0.8.11/v0.8.12や開発途中コミットの数値は今回の表へ混ぜていない。v0.8.15からの無劣化、全製品との機能同等性、全データ規模への一般化は主張しない。

## 再実行と証跡

Codexの[シナリオ表](alopex-v0.8.16-performance/run-20261021/plan.md)は測定前に対象・期待結果・依存・出力予算を定めた。[reproduce-v0816.py](../scripts/performance/reproduce-v0816.py)は既存ケースを直列に起動し、[render-v0816.py](../scripts/performance/render-v0816.py)は保存結果・sample数・checksum・recallを検査して相対値を導く。

再実行者は、上記の公開ソースを別checkoutへ取得し、`git apply --unidiff-zero harness.patch`で補正を適用する。再実行者は隔離venvへ依存一覧と公開wheelを導入し、[元workflow](https://github.com/alopex-db/alopex/blob/d9ff8783b8d18a63d167204e55902ea6cd90dcd1/.github/workflows/parity-performance.yml)のchecksum固定Amazon archiveを入力directory内の`amazon`へ展開する。PostgreSQL 16.14は専用DBで起動し、`ALOPEX_PERF_POSTGRES_DSN`を設定する。以下の手順は旧runを再現するものであり、PostgreSQLのserver/client比較には対応していない。以下のplaceholderは各再実行者の配置先に置き換える。

```bash
rtk proxy python -B scripts/performance/reproduce-v0816.py --harness-root <alopex-checkout> --data <temporary-input-directory> --output <new-run-directory> --phase prepare
rtk proxy python -B scripts/performance/reproduce-v0816.py --harness-root <alopex-checkout> --data <temporary-input-directory> --output <new-run-directory> --phase hnsw
rtk proxy python -B scripts/performance/reproduce-v0816.py --harness-root <alopex-checkout> --data <temporary-input-directory> --output <new-run-directory> --phase tabular
rtk proxy python -B scripts/performance/render-v0816.py <new-run-directory>
```

各caseの`.status.json`は終了状態、`.json`は元ハーネスの数値、`.raw.ndjson`はtabularの各sample、`.stderr.txt`は失敗を含む診断を保持する。HNSWの各JSONは設定別・trial別の検索回数・recall・分位点を保持する。[relative.json](alopex-v0.8.16-performance/run-20261021/relative.json)は旧runの相対値を保持する。Codexは監査用に旧rawとrelative.jsonを変更せず残すが、同JSONのPostgreSQL行は無効な比較として扱う。再実行者は失敗したrun directoryを上書きせず、新しいrun identityへ結果を保存する。

[公開パッケージの機能・導入確認レポート](release-verification/v0.8.16.md)は別の責務を持つ。そこにあるbuild時間やシナリオ時間は、本性能比較の数値として扱っていない。
