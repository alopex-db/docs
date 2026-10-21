# 書込・ランダムアクセス・KVの追加評価

CodexはSQL server/clientとembedded KVを別の責務として比較する。Codexは既存KVベンチのkey/value生成・固定seed・point操作・順次/ランダムbatch・範囲走査を再利用し、自動flushを抑えた内部ベンチ設定を公開標準設定の数値へ流用しない。

| 契約 | ケースと期待結果 | 依存と正確なコマンド | 出力予算 |
|---|---|---|---|
| 公開server | 公開alopex-server0.8.16 release build、digest保存 | cargo install --locked --version 0.8.16 --root <temporary-install> alopex-server、jobs2・incremental0 | target12GB予定、20GBで停止、全体40GB未満 |
| SQL server/client | insert commit（1/100行）、random point get hit/miss、random update/delete commit。両群とも同じ行・SQL・結果 | 公開RemoteDatabase0.8.16対psycopg3.2.10/PostgreSQL16.14、serverCPU0/clientCPU1、TLS/authなし | 同host filesystem専用DB各1GB未満 |
| embedded KV | sequential/random put commit、random get hit/miss、overwrite/delete commit、range scan。bytes一致・同じtransaction境界 | 公開alopex0.8.16対py-lmdb（導入version固定）、workerCPU0、10byte key/32byte value、書込seed42・KV読取seed7 | 専用DB各1GB未満 |
| fixtureと反復 | 初期10,000件、warm cache、3warmups/21samples/3trials、engine/case/trialごと独立process、交互順 | case選択はrunner。既知DROP SEQUENCEは実行しない | case300秒、raw各10MB未満 |
| 耐久性 | commitの完了まで計測し、close/reopen後の全値・件数照合。両群ともsync有効 | fixture投入・復元・照合は計測外。新規書込は毎sample別key。delete後の復元は計測外 | 1run100MB未満 |
| 検証 | byte生成・固定random・失敗継続・相対集計と実adapter回帰 | python -B -m unittest discover -s scripts/performance -p test_write_kv.py | 1MB未満 |

CodexはSQLをSQLと比較し、raw KVをraw KVと比較する。embedded KVの数値をサーバーAPIの代用にしない。Codexは同期保証をコードと実パッケージで確認してからwrite比較を成立させる。sourceは公開v0.8.16に固定し、前runを上書きしない。Codexはbuildと測定を直列に実行し、所有target・server/container・一時DB/venvを測定後に回収する。

## DataFrameの追加監査と位相別測定

ユーザーは旧0.135倍がDataFrame構築を含むか、計算結果が完全に評価・照合されているかを質問した。独立監査は旧全6processの最終12列と返却tupleを純Python oracleから再構築し、保存SHAと一致させた。一方、旧explode/concatはheightだけ、next_idは未使用、初期to_dictはidだけを具体化し、全sampleの結果照合はなかった。

CodexはPolars1.43.2と公開Alopex0.8.16について、construct・compute・convert・completeを別processで各3trials/3warmups/21samples実行する。入力は旧34,250行、Pythonデータ生成は原則計測外、completeのitems生成は旧ケース同様計測内。constructは構築だけ、computeは事前構築frameから12列collect、convertは事前計算結果のPython変換、completeは入力全列・next_id・explode/concat全行・最終12列を計測内で具体化する。Codexは各sampleを型・NULL・順序・全値の独立oracleへ計測外で照合する。filterは全行通過の固定ケースであり、内部native dtype同一や一般的な計算優位は主張しない。completeは旧ケースより具体化範囲が広く、旧0.135倍と同じ仕事量の結果とは扱わない。追加runはUTC/JST時刻を記録し、測定開始日のJSTに合わせrun-20261022-write-kvを用いる。

Codexは公開v0.8.16のLSM commit_write_setがWAL force_syncを完了することを実装で確認した。NoSyncという設定名だけでcommitが非耐久だとは判断しない。KV random-batch-putは連続する100新規keyの投入順をseed42でshuffleするケースであり、既存key空間への一様random writeはrandom-overwrite-commitで別に評価する。KVはclose/reopenで全値を検証し、SQLはcommit後の新規client接続で全件を照合する。SQLserverの再起動や電源断の耐久試験を実施したとは主張しない。
