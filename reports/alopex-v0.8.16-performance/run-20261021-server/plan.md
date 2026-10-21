# PostgreSQL比較の訂正とserver/client再測定

Codexは旧runのembedded Alopex対PostgreSQL serverという比較を無効と判定する。Codexは旧rawを保持し、0.051倍を性能評価から除外する。

| 契約 | 所有ケース | 実行と期待結果 | 依存・出力予算 |
|---|---|---|---|
| 公開server | crates.io `alopex-server==0.8.16` | locked release install、versionとbinary digestを保存 | Rust1.96.0、jobs2、incremental0。予定target12GB以下、所有target20GBで停止、合計40GB未満を運用予算とする |
| server/client境界 | 既存PostgreSQL curatedケース | Alopex RemoteDatabaseとpsycopgの両方がloopback serverへ接続する。embedded fallbackを拒否 | 公開Python wheel0.8.16、psycopg3.2.10、PostgreSQL16.14。venv100MB程度 |
| 結果とrollback | 同ケースの小規模preflight | RETURNING・MERGE・DDL rollback・sequenceと全結果を計測外で照合 | 最小行数、専用DB、case出力10MB未満 |
| 比較測定 | `sql-postgresql-curated` | 同じ34,250行・3 warmups・21samples・3trials、製品順交代、同じSQLを全消費。接続生成とfixture投入は計測外 | 両serverは同じホストの同じ媒体、fsync有効、TLSなし、認証なし、接続再利用。server CPU0/client CPU1、数値thread1。DB予算各1GB未満 |
| 証跡 | docsの既存レポート | raw・結果checksum・製品identity・条件・新相対値・旧比較の無効判定を併記 | 旧runは上書きしない。PostgreSQLだけを再測定し、他製品の値は変更しない |

Codexは公開crateからserverをビルドし、製品ソースを変更しない。Codexは既存比較ハーネスへ明示的にRemoteDatabaseを渡し、操作列を再実装しない。両serverは専用の永続化領域を使い、server/clientの設定差・プロトコル差はレポートに記載する。性能値はclientから見た完全なrequest/responseの所要時間であり、純粋なengine演算時間ではない。

Codexはbuildと計測を直列に実行する。Codexはbuild後の再生成可能なtargetを回収してから計測し、終了後に所有server・PostgreSQL container・DB・venv・取得crate/wheel・作業worktreeを回収する。Codexは公開証跡と再実行手順だけを保持する。
