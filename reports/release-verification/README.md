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
run/attempt、公開PythonタグのソースSHA、検証スクリプトの親コミットを確認します。
保存後に両ファイルのSHA-256を確認します。入力ブランチのコードは実行しません。

検証結果と保存処理の成否は別の記録です。過去の `*-publication-failure.*` は
保存処理の障害記録であり、パッケージのシナリオが失敗したことを示しません。
元のActions runの結論は履歴として残します。
