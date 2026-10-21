# 通常のPolars操作149ケース：公開Alopex v0.8.16の機能評価

**#722の初回6ケースだけでは、Polars互換という製品ゴールの検証に不足していた。** Codexは通常の操作を13分類・149ケースへ広げ、同じコードを公開Alopex 0.8.16と実Polars 1.43.2へ流した。今回の全契約を満たすケースはなかったため、Polars互換の目標には広い未達が残る。

ただしAlopexは20ケースを実行でき、19ケースでは全値・Python値型・NULL・列順・行順が一致した。20ケースともschemaを取得できず、完全契約の確認には至らなかった。Codexはこの結果を「すべての操作が動かない」とは解釈しない。残る1ケースのbool構築では、PolarsのTrue／Falseに対しAlopexが1／0を返す差があった。

本評価は機能の差分テストであり、速度測定ではない。Codexは既存の性能比を変更しない。[Issue #722](https://github.com/alopex-db/alopex/issues/722)は通常操作の検証・不足修正を所有し、#712は成立した操作の性能改善を所有する。

## 実行・値一致・完全契約を分けた結果

| 判定対象 | 結果 | 解釈 |
|---|---:|---|
| 参照Polars | 通常146ケース成功、期待エラー3ケース成立 | 無効な参照セルは0 |
| Alopexの実行 | 20ケース成功、129ケースで例外 | 例外には期待エラー3件も含み、129個のAPIが未実装という意味ではない |
| Alopexの実行成功20件 | 19件で値一致、1件でbool型の差 | 値一致だけではschema/dtypeの互換を証明しない |
| schema/dtypeの確認 | 成功20件すべて未検証 | 公開schema取得が未対応。内部の型がすべて誤っているという主張ではない |
| 完全契約 | 149ケース不合格 | runnerは終了コード1。skip/xfailによる成功への変換なし |

全298 workerは診断結果を正常に保存した。workerの終了コード0は操作の互換成功ではない。[summary.json](audit/summary.json)は製品の判定を分けて記録し、[matrix.json](audit/matrix.json)は今回の正確な対象を定義する。

| 分類 | ケース数 | Alopex実行成功 | 値一致 | 完全契約合格 |
|---|---:|---:|---:|---:|
| aggregation | 10 | 0 | 0 | 0 |
| batch-boundaries | 10 | 4 | 4 | 0 |
| construction | 14 | 5 | 4 | 0 |
| errors | 3 | 0 | 0 | 0 |
| expression | 21 | 1 | 1 | 0 |
| io | 10 | 0 | 0 | 0 |
| join-concat | 9 | 1 | 1 | 0 |
| namespaces | 14 | 1 | 1 | 0 |
| selection | 20 | 8 | 8 | 0 |
| series | 8 | 0 | 0 | 0 |
| series-diagnostic | 8 | 0 | 0 | 0 |
| table-and-nulls | 12 | 0 | 0 | 0 |
| types-and-shapes | 10 | 0 | 0 | 0 |

149は今回のシナリオ数であり、固有API数でもPolars全機能の分母でもない。既存Seriesを使う8診断は、直接Series構築で停止した演算の可否を独立に調べるためのもので、別の機能が8個実装されているという数え方はしない。

## 基本操作の不足を隠さない比較

Codexは構築、eager/lazyの選択・更新・filter、演算子とメソッド、集約、join/concat、欠損値、文字列・日時・list、cast・形状変換・window、CSV/Parquet I/Oを含めた。Codexは空入力・全NULL・bool・float・Unicode・NULLキー・重複キー・空list・NULL要素・非default引数もケースへ含めた。

batchのテストは0／1023／1024／1025行、先頭区間が空になるfilter、NULL付きの数値・文字列式を使う。Codexは全batchの全値を連結して比較し、件数だけや最初のbatchだけで成功にしない。空batch結果の型情報はplanのcollect_schemaから確認し、取得できなければ未検証とする。

両製品は同じoperationを実行する。CodexはAlopexだけstatic scanや独自namespaceへ置換しない。公開schemaを取得できない場合、判定器は値が一致していても完全契約を不合格とする。例外のテストは例外型名の一致を要求し、存在しない列と不一致の列長では両製品が拒否しても例外型が異なるため不合格だった。strict castのケースはAlopex側のcastがなくAttributeErrorとなった。

[bool構築の完全結果](audit/case-construct-bool.json)は、Alopexの返却値がPython boolではなくintであることを示す。[schema取得](audit/case-schema.json)と[例外契約](audit/case-error-missing-column.json)も個別に確認できる。各caseファイルは参照とAlopexの結果、または例外を保持する。

## 仕様・既存テスト・CIとの関係

製品仕様は、Polarsの主要APIと同じ意味で動くことを目標にし、構築・eager/lazy・集約・I/O・join・欠損値・namespace等を含む。既存のPython差分テストは限定された入力とAPIの確認であり、その成功だけで通常操作全体を保証しない。未対応optionの拒否確認も、Polarsが同じoptionを受け付ける場合は互換成功にならない。

対象ソースd9ff8783の互換台帳は999項目を持ち、966項目を未実装としている。Codexはこの静的な数を実行済みのテスト数や互換率として使わない。また台帳にはトップレベルselect等の不足もあるため、担当者は公開API・製品仕様・実行テストの対応を整える必要がある。

Codexは再利用する[テストコード](https://github.com/alopex-db/alopex/blob/02bb9f9ef5007408f9001bb9c8e8a4ef6d8f28d1/scripts/reference_tests/polars_common_v0816.py)を製品リポジトリのscripts/reference_testsへ置いた。判定器のunit testsは5件成功したが、これは製品の互換性の成功とは別である。既存のexact Polars CIへ同じ行列を組み込み、ソースから構築した候補packageのversionを明示して実行し、失敗時も証跡を残す変更は[Draft PR #724](https://github.com/alopex-db/alopex/pull/724)で管理する。Codexは未確認の候補CIや製品互換性を成功と宣言しない。

今回の149ケースもPolarsの全機能を網羅しない。#722の完了には、仕様・公開API・通常操作の対応表と差分テスト、判明した不足の修正、候補commitでの継続実行が必要となる。担当者は初回6件だけの修正や、未実装を台帳へ登録するだけで親Issueを閉じない。

## 固定した実行と再実行方法

今回のauditコードは製品repoのcommit 02bb9f9ef5007408f9001bb9c8e8a4ef6d8f28d1。製品機能は公開wheelのalopex 0.8.16、参照はPolars／runtime 1.43.2であり、Rust製品コードの変更はない。[環境・コードhash・fixture hash](audit/environment.json)、全case・workerのstdout/stderr/status、[独立照合](verification.json)を保存した。

再実行者は製品repoのテストコードを取得し、隔離環境へrequirements-polars-common.txtを導入する。再実行者は新しい出力・fixture directoryを指定し、公開版の失敗結果を上書きしない。

```bash
python -B -m unittest discover -s scripts/reference_tests -p test_polars_common.py
python -B scripts/reference_tests/polars_common_v0816.py --output <new-run> --data <temporary-fixtures>
```

修正候補を検証する担当者はそのwheelを導入し、`--subject-version <installed-version>`で対象versionを固定する。runnerは完全合格なら0、製品不合格なら1、参照ケースが無効なら2で終了する。Codexは初回参照の誤ったDataFrame.implode呼び出しを検出して正しいExpr.implodeへ修正し、その失敗も[事前確認](reference-preflight-initial.json)へ保持した。最終auditには無効な参照セルを混ぜていない。
