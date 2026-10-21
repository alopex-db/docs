# Polars互換：DataFrameを明示構築しない入口の評価計画

## 事前検証後の行列追加

Codexの17行fixture事前検証は、CSVの12列計算で成功した一方、Parquetの12列計算ではcollect/batches両方が`type mismatch: expected Utf8, got LargeUtf8`で失敗した。Codexはこの失敗ケースを行列へ残し、相対値を算出しない。Codexは同じParquet入力から独立した数値・比較・論理11列のcollect/batchesを追加し、文字列の機能不足で他の計算比較を停止しない。今回の性能行列は6ケース、入口probeは4ケースとする。Codexはこの追加を性能測定前に確定した。

Codexは新規testの初回実行でmodule未実装のREDを確認した。実装後の初回3 testsではParquetの2ケースが上記製品エラーで失敗した。Codexは製品の失敗を成功へ変更せず、回帰確認がその型不一致を明示的に検証するようにし、3 testsの成功を確認した。Codexは性能比較のParquet12列を引き続き失敗セルとして出力する。

CodexはPolars互換を受入目標とし、既存のDataFrame構築経由だけでは比較範囲が不足する点を修正する。製品は公開alopex 0.8.16とPolars 1.43.2、対象ソースはd9ff8783b8d18a63d167204e55902ea6cd90dcd1。Codexは製品コードを変更しない。

## シナリオと実行予算

| 契約・ケース | 所有する確認 | コマンド | 期待結果 | 依存・出力予算 |
|---|---|---|---|---|
| module.select・Series直接演算・module.scan_csv・module.scan_parquet | 公開wheelの入口probe | python scripts/performance/polars_entrypoints_v0816.py --output <new-run> --data <temporary-data> | 各製品・入口を個別processで実行。対応なしはcapability-gap、相対値なし | pinned wheel2製品、venv含め1GB以下 |
| CSV/Parquet scan→既存12列表現→collect | 同runner、csv-collect/parquet-collect | 同上 | 全値・Python型・NULL・列順・行順が独立oracleと一致 | 各case/engine/trialを独立process、3 warmups/21 samples/3 trials |
| CSV/Parquet scan→同じ12列→collect_batches全消費 | 同runner、csv-batches/parquet-batches | 同上 | 全batchの全列・全行を結合してoracle一致。件数だけの確認にしない | chunk_size8192、各process直列、fixture各数MB |
| 誤値・NULL・順序・API不足の分類 | test_polars_entrypoints.pyと既存test_dataframe_phases_v0816.py | python -B -m unittest discover -s scripts/performance -p test_polars_entrypoints.py; 続いて同様にtest_dataframe_phases_v0816.py | 最小fixtureの実両APIを検証。既知不足を測定成功に変換しない | ビルドなし、pycache無効、実行後一時fixture削除 |

Codexは34,250行の既存CSV/Parquet fixture形状（id Int64、label nullable String）と既存12列の式を再利用する。比較はCPU0、POLARS_MAX_THREADS=1、数値thread1、warm filesystem cache、固定3 trialsと交互の製品順。主指標は時間の中央値の比Alopex/Polars、参照=1、小さいほど速い。今回の測定は改善実装の合否ではなく追加baselineであり、ノイズで有利な結果を採用する閾値は設けない。

Codexはscan・式構築・ファイル読込・実行を計測内に含め、collectでは全結果DataFrameの生成、batchesでは全batch DataFrameの取得まで計測する。Python dict変換とoracle照合は計測外。CSV/Parquet生成、Python入力生成、wheel導入は計測外。CodexはDataFrameコンストラクタを計測経路に挿入しない。Alopexのstatic scanとPolarsのトップレベルscanは機能比較として明記し、同名API互換の成立と区別する。

Codexは各processのstatus・raw・結果を直ちに保存し、失敗・不一致も残して独立ケースを継続する。欠測・API不足に倍率を与えない。Codexは計測前にfixtureを読みwarm cacheとし、両製品の同じ入力ファイルhashを保存する。Codexは旧CSV/Parquetの件数中心のstreaming比較を上書きせず、今回の式付き全値検証と別ケースとして扱う。

Codexは開始時にworkspace約1.20GB、保持中の公開server約42MBを確認した。Codexは今回の追加一時出力を1GB以下、測定証跡を20MB以下に見積もり、40GBの運用予算に余裕を確保する。Codexは測定後にvenv・fixture・作業worktreeを削除し、公開証跡を保持する。Codexは既存のserverバイナリを今回実行しない。
