# 独立したserver/client SQLケースの再測定

Codexは既存複合ケースのDROP SEQUENCE失敗をPostgreSQL比較全体の失敗へ拡張しない。Codexは既存ハーネスの固定入力とSQLを再利用し、独立した読取・書込・DDLケースを各processで実行する。

| 契約 | 実行 | 期待結果 | 依存・出力予算 |
|---|---|---|---|
| 公開server | cargo install --locked --version 0.8.16 --root <temporary-install> alopex-server | 公開版release build、version/hash一致 | jobs2、incremental0、target予算12GB、20GBで停止、全体40GB未満 |
| 読取SQL | 既存SQL_AGGREGATE_QUERY、順序付き16行SELECT、既存SQL_STREAM_QUERYを全消費 | 34,250行fixtureから同じ結果、DDLなしで各読取を独立測定 | RemoteDatabase/psycopg、専用diskDB各1GB未満、client CPU1/server CPU0、TLS/authなし |
| 書込SQL | 既存curatedのINSERT RETURNING＋rollback | 同じ返却値・rollback状態 | 各engine/caseを独立process、読取の失敗判定に影響させない。書込は1行fixtureへのINSERT RETURNINGとrollbackで、永続commitを測定しない |
| DDL | 既存curatedのDROP SEQUENCE IF EXISTS | 成功/不具合を個別記録 | 不具合caseでも次のcaseを実行する |
| 反復・証跡 | 3warmups、21samples、3trials、交互順、rawを即時保存 | 同一caseの結果checksum一致後だけ相対値を生成。失敗は保持 | case出力各10MB未満、run上書き禁止 |
| 検証 | samplerとcase継続/集計の実行動作をunit test | 失敗caseが成功caseを遮断せず、失敗の数値を集計しない | python unittest、出力1MB未満 |

Codexは接続生成とfixture投入を計測外、既存接続のrequest/responseと全結果消費を計測内とする。両serverは同じhost filesystemへ永続化し、PostgreSQLはfsync/synchronous_commit有効、並列query無効とする。Codexはbuildと測定を直列に実行し、前回の失敗runとrawを保持する。Codexは測定後に所有server・container・DB・venv・build出力を削除する。

Codexはordered SELECTのCOALESCE列へAS valueを付け、両APIの列名付き結果を揃える。CodexはPostgreSQLにdict_rowを指定し、Alopexのlist[dict]と同じPython表現まで取得する。Codexは全結果取得をstreaming API同士の比較とは呼ばない。各case processは300秒を上限とし、timeoutも失敗として保存して次のcaseへ進む。

Codexはpsycopgのprepare_threshold=Noneを指定し、Alopex RemoteDatabaseと同様に明示prepared statementなしでSQL文字列を送る。両製品の接続は再利用する。
