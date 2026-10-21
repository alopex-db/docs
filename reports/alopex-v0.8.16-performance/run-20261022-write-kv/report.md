# v0.8.16：書込・ランダムアクセス・KVとDataFrame区分別評価

追加測定日は2026年10月22日（JST）。本レポートは参照製品を1とする時間比を示す。時間比はAlopex / 参照で小さいほど速く、処理量比は同じ操作数に対する逆数で大きいほど高い。Codexは全108 process・2,268 measured samplesの入力・結果一致とrawからの相対値を確認した。

**今回の主要な差**：SQL random DELETE＋commitはPostgreSQLの50.053倍、KV random get hitはLMDBの6.700倍、範囲走査は17.538倍の時間だった。一方、KV単件PUT＋commitは0.466倍だった。DataFrameの計算区分はPolarsの1.645倍で、旧複合ケースの0.135倍を計算性能の優位とは読めない。

## SQL：server/client API対PostgreSQL

| ケース | 時間比 ↓ | 処理量比 ↑ | trial別時間比の範囲 |
|---|---:|---:|---:|
| 単件INSERT＋commit | 2.145 | 0.466 | 2.036–2.350 |
| 100行INSERT＋commit | 3.347 | 0.299 | 3.128–3.679 |
| random get hit（100回） | 2.472 | 0.404 | 2.450–2.487 |
| random get miss（100回） | 2.643 | 0.378 | 2.277–2.664 |
| random UPDATE＋commit | 2.524 | 0.396 | 2.485–2.613 |
| random DELETE＋commit | 50.053 | 0.020 | 46.869–55.228 |

SQLの入力は10,000行、INTEGER主キーと32文字TEXT。公開RemoteDatabase 0.8.16対psycopg 3.2.10 / PostgreSQL 16.14を、server CPU0・client CPU1で比較した。Codexは接続とfixture投入・検証を計測外に置き、明示beginからcommit完了までをwrite時間に含めた。random readは1 sampleに100回の独立したpoint SELECTを含む。Codexは毎sampleの返却値・更新後状態と、新しいclient接続からの最終全件を照合した。SQLserverを再起動した耐久性試験ではない。

## KV：embedded Python API対LMDB

| ケース | 時間比 ↓ | 処理量比 ↑ | trial別時間比の範囲 |
|---|---:|---:|---:|
| 単件PUT＋commit | 0.466 | 2.146 | 0.413–0.653 |
| 順次100件PUT＋commit | 0.778 | 1.285 | 0.680–0.877 |
| 投入順shuffle・100件PUT＋commit | 0.782 | 1.279 | 0.782–0.811 |
| random get hit（100回） | 6.700 | 0.149 | 6.258–7.390 |
| random get miss（100回） | 1.334 | 0.750 | 1.125–1.803 |
| random overwrite＋commit | 0.415 | 2.412 | 0.385–0.473 |
| random DELETE＋commit | 0.455 | 2.196 | 0.435–0.501 |
| 範囲走査1,000件・全値取得 | 17.538 | 0.057 | 16.034–18.979 |

KVの入力は10,000件、既存LSMベンチに合わせた10byte key（k:＋u64 big-endian）と、memory_vs_diskベンチの大きさに合わせた32byte value。公開Alopex 0.8.16対py-lmdb 2.0.0 / LMDB 0.9.35を、CPU0上のnative Python APIで比較した。両群とも永続commitまで計測し、読み出しはコピー済みbytesで揃えた。Alopex commitのWAL force-syncを公開実装で確認し、LMDBはsync/metasync有効、writemap/map_async無効、buffers=Falseを明示した。Codexはfixture投入・flush・最初のclose/reopenを計測外に置き、毎sampleと最後のclose/reopen後の全key/value・順序を検証した。

書込のseedは42、point読取とrangeは7。random-batch-putは連続100新規keyの投入順だけをshuffleし、既存key空間へのuniform random writeはrandom-overwrite-commitで測る。getは100回それぞれread transactionを開始・終了し、rangeは1つのsnapshotで1,000件を全消費する。deleteの復元は次sample前の計測外で行い、最後のdeleteは復元せず再オープン後の欠落も照合した。

## DataFrame：構築・計算・変換の分離

| ケース | 時間比 ↓ | 処理量比 ↑ | trial別時間比の範囲 |
|---|---:|---:|---:|
| 構築：事前生成Pythonデータ→DataFrame | 0.033 | 30.502 | 0.030–0.033 |
| 計算：構築済みDataFrame→12列collect | 1.645 | 0.608 | 1.627–1.766 |
| 変換：計算済み12列→Python dict | 0.987 | 1.014 | 0.959–1.032 |
| 全体：構築＋全中間結果・最終結果の具体化 | 0.277 | 3.614 | 0.269–0.278 |

DataFrameの入力は旧比較と同じ34,250行（id Int64、label nullable String、items List(String)に対応する論理型）。両群のPython入力生成は原則計測外で、completeだけは旧ケースと同じitemsリスト生成を計測内に含める。ファイル読込は全4区分とも含まない。各区分の比較は同一入力・API境界であり、構築とPython変換を計算時間へ混ぜない。

Codexは全warmup/sampleで、入力全列・next_id・explode全行・1入力concat全行・最終12列を独立Python oracleと比較し、Python値の型・NULL・順序まで照合した。computeでは最終selectに不要なnext_idが最適化で省略され得るが、completeでは同列も計測内で具体化する。filterは全行通過の既存条件であり、選択性の高いfilterや一般的なDataFrame全機能の性能を代表しない。Python変換の比率幅は1をまたぐため優劣を断定しない。

旧0.135倍の比率計算と最終12列の正しさは独立監査で再確認した。両製品とも旧計測にはDataFrame構築・計算・explode・concat・Python変換が含まれたが、旧中間検証は一部の件数だけで、計測前後の最終結果だけをhash化していた。新completeは中間結果の具体化範囲が広いため、旧0.135倍を新0.277倍で同じ仕事量の再測定値として置き換えない。旧値は限定された旧複合ケースの履歴として残す。

## 共通条件と解釈

- Codexは各engine/case/trialを独立client processで直列実行し、3 warmups・21 samples・3 trialsと交互の実行順を使った。全ケースはwarm cacheであり、物理ディスクのcold random I/O、並行負荷、メモリ超過規模の性能を測った結果ではない。
- SQLの両serverは同じhost filesystemのdiskを使い、PostgreSQLはfsync/synchronous_commit有効、並列query無効、TLS/authなし、接続再利用、自動prepared statement無効とした。SQLfixtureは各processでリセットし、server自体は同一run中で再利用した。
- KVとDataFrameはSQLserver停止後に実行した。DataFrameはPOLARS_MAX_THREADS=1と数値thread1を明示し、同設定の独立runtime確認でもPolars thread poolは1だった。内部の物理表現を同一とは主張しない。
- 時間比は各sampleの所要時間の中央値をprocess代表値とし、3 trialsの中央値同士を割った。同数の100要求や1,000行走査をまとめたsampleは、個々の要求のp50ではない。ケース間やSQL/KV間の数値を混ぜて総合倍率にはしない。
- 既知のDROP SEQUENCE不具合は既定で除外し、今回の行列では実行していない。独立ケースの比較を同不具合の修正待ちにはしない。
- rawのKV peak RSSはprocess全体の最大値で、初期化と全件照合を含む。store logical/allocated bytesも別々に保存した。Codexはこれらを純粋なengine内部メモリやSQLserver全体と同一視しない。

## 証跡と再実行

[条件と事前計画](plan.md)、[公開パッケージ照合](packages.json)、[機能回帰・旧DataFrame監査](verification.json)、[raw再計算](result-verification.json)、[相対値CSV](relative.csv)を参照する。各familyのrelative.jsonとcaseごとのstatus/result/raw/stdout/stderrは失敗を含め上書きせず保持する。

再実行者は公開Pythonパッケージalopex 0.8.16、psycopg/binary 3.2.10、lmdb 2.0.0、polars/runtime 1.43.2を隔離venvへ導入する。SQL再実行者は公開alopex-server 0.8.16とPostgreSQL 16.14を上記条件で起動し、ALOPEX_PERF_SERVER_URLとALOPEX_PERF_POSTGRES_DSNを設定する。再実行者は新しい出力directoryと専用DBを用い、各familyを直列に実行する。

```bash
rtk proxy python -B scripts/performance/write-kv-v0816.py --family sql --output <new-run>/sql --data <temporary-data>/sql
# 再実行者はSQL両serverを停止してから、次を実行する。
rtk proxy python -B scripts/performance/write-kv-v0816.py --family kv --output <new-run>/kv --data <temporary-data>/kv
rtk proxy python -B scripts/performance/write-kv-v0816.py --family dataframe --output <new-run>/dataframe --data <temporary-data>/dataframe
```

[runner](../../../scripts/performance/write-kv-v0816.py)は既存のprocess保存・相対集計を再利用する。KVケースの基礎は公開ソースd9ff8783の[lsm_kv_bench.rs](https://github.com/alopex-db/alopex/blob/d9ff8783b8d18a63d167204e55902ea6cd90dcd1/crates/alopex-core/benches/lsm_kv_bench.rs)と[memory_vs_disk.rs](https://github.com/alopex-db/alopex/blob/d9ff8783b8d18a63d167204e55902ea6cd90dcd1/crates/alopex-embedded/benches/memory_vs_disk.rs)。新規比較adapterは公開Python APIを呼び、製品コードを変更していない。
