# 通常のPolars操作を確認する差分テスト計画

Codexは#722の6ケースだけでは通常操作の互換性を判断できないため、公開alopex 0.8.16と実Polars 1.43.2へ同じコード・入力を渡す機能auditを追加する。Polars互換という製品目標は維持する。Codexは製品機能の実装や性能の再測定を今回の作業に含めない。

| シナリオ | 所有する確認・コマンド | 期待結果 | 依存・生成予算 |
|---|---|---|---|
| 構築、型、列取得、eager/lazy選択・更新・filter | scripts/reference_tests/polars_common_v0816.py --output <new-run> --data <temporary-data> | 同じ公開APIの実行成否、全値・Python型・NULL・列順・行順・schema/dtypeを比較 | 公開wheel2製品、Rustビルドなし、venv含め1GB以下 |
| Expr/Series、集約・group、sort・join・concat、欠損・cast | 同runnerの独立ケース | 未実装・異なる結果・契約未検証を不合格として保存 | 各engine/caseを独立process、時間計測なし |
| 文字列・日時・list、形状変換・window、CSV/Parquet read/scan/write、batch境界 | 同runner、1023/1024/1025行も使用 | 全batchの全値を比較。参照だけ失敗したケースは無効でありAlopex不具合と数えない | 小fixture、一時ファイルはケース単位で削除、公開証跡20MB以下 |
| schema欠落、Python値型、NULL、列/行順、期待した例外、参照エラー分類 | python -B -m unittest discover -s scripts/reference_tests -p test_polars_common.py | 契約判定の回帰確認。dtype不明の値一致を互換成功にしない | 標準ライブラリのみ、生成物なし |

Codexは参照Polarsが先に有効に実行できることを確認する。Codexは普通の演算子とメソッド、eagerとlazy、非default引数を別ケースとして扱う。CodexはAlopexだけ別入口・別構文へ書き換えない。順序が未保証の操作はmaintain_orderやsortを両製品へ同じように指定する。

CodexはAPI一覧の静的な未実装数と実行結果を区別する。台帳の999項目を通常操作の分母や互換率にしない。Codexは今回のケースもPolars全機能の網羅とは主張しない。実装済み項目だけへ評価を狭めたり、未対応をskip/xfailして合格と数えたりしない。

Codexは開始時のworkspaceと保持server合計を約1.24GBと確認した。Codexは一時環境1GB・証跡20MBを上限に見積もり、40GBの運用予算に余裕を持たせる。Codexは作業後にvenv・fixture・worktreeを削除し、公開証跡を保持する。

Codexは独立レビューを受け、既存Seriesの独立診断、空/全NULL集約、all選択、非default option、0行collect/batch、空batch区間filterとNULL式を追加した。最終行列は149ケース・13分類で、実Polarsの事前確認は全件有効だった。初回の事前確認はDataFrame.implodeという誤った参照を1件検出したため、Codexは正しいExpr.implodeへ修正した。初回証跡を保存し、Alopexの不具合に数えない。

Codexはテストを製品repo scripts/reference_testsへ置き、docs repoには証跡と報告だけを保存する。Codexは候補wheelにも同じ行列を実行できるよう、subject-versionを明示して導入済みversionを検査する。測定ソースcommitは02bb9f9ef5007408f9001bb9c8e8a4ef6d8f28d1。

Codexは既存alopex-py workflowのexact Polars jobへ同じauditと判定unit testsを追加し、失敗時も証跡をuploadする。担当者は既知の製品不合格を無視してmainへ統合しない。Codexは製品側PRをDraftとし、今回の作業では製品の互換性や候補CIの成功を宣言しない。CI変更の最小確認は、同じ149ケースのローカル実行、5判定tests、実行可能YAML parserによるworkflow構文確認とする。Rust製品コードを変更しないため、Codexは無関係なworkspaceビルドをローカルで実行しない。
