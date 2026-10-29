# 公開パッケージのリリース確認レポート

`vX.Y.Z.md` / `vX.Y.Z.json` は、そのバージョンで最後に実行した全シナリオの結果です。
各ステップの説明、実測ログ、成功・失敗・未完了、公開タグのソースSHA、
検証スクリプトのSHA、実行runとattemptを記録します。

`vX.Y.Z/run-RUN-ATTEMPT.md` / `.json` は、実行ごとに保存する変更不可の原本です。
同じパスに異なる内容が来た場合は取り込みを拒否します。
インストール確認だけの結果は、全シナリオのレポートとして掲載しません。

## 自動保存

Alopexの `Public release verification` は、公開パッケージを検証して
JSONとMarkdownの組を `report/verify-release-vX.Y.Z-RUN-ATTEMPT` ブランチへ保存します。
このリポジトリの `Publish release verification report` が15分間隔で取り込み、
docs側の `GITHUB_TOKEN` でmainへ保存します。リポジトリ間の書き込み用PATは不要です。
`workflow_dispatch` の `version` を指定すれば、対象バージョンだけを即時取り込めます。

取り込みでは、レポート以外の変更がないこと、JSONとMarkdownの結果とステップ、
run/attempt、公開PythonタグのソースSHA、検証コードのSHAを確認します。レポートだけの保存ブランチでは、生成元Actions runのソースSHAと照合します。
保存後に両ファイルのSHA-256を確認します。入力ブランチのコードは実行しません。

保存失敗時は `report/verify-release-failure-vX.Y.Z-RUN-PUBLISH_ATTEMPT` から
独立した `alopex-report-publication/v1` のJSON/Markdownを受信します。
失敗段階と公開attemptを記録し、元の検証結果が取得できればその原本も変更せず保存します。
原本が取得できない場合は未取得と明示します。原本のハッシュ、run/attempt、
解決済みの公開タグ、全ファイルの衝突を検査してから書き込みます。
この経路から全シナリオの正式レポートへ昇格することはありません。

検証結果と保存処理の成否は別の記録です。過去の `*-publication-failure.*` は
保存処理の障害記録であり、パッケージのシナリオが失敗したことを示しません。
元のActions runの結論は履歴として残します。
旧publisherが作ったMarkdownのみのブランチも履歴として取り込みますが、
新しい全シナリオのJSON/Markdown組として扱ったり、正式版に昇格させたりしません。

正式Markdownは読みやすさのための表示です。旧テンプレートの説明に誤解を招く表現がある場合は、
測定値・判定・JSONを変えずに表示を補正します。実行ごとの原本Markdownは変更しません。
たとえばRustの公開crateはcargoでコンパイルするため、旧表記の「ソースビルドなし」は
「作業コピーの製品コードを使用しない」という取得経路が分かる表記へ補正します。
