# Polars互換APIの入口とLazy実行：v0.8.16

**AlopexDB v0.8.16は、今回確認したDataFrameを明示構築しない6つの入口・操作でPolars互換を満たしていない。** Codexは先行レポートのDataFrame構築経由だけでは比較範囲が不足していた点を訂正する。Polars互換という目標は維持し、Codexは未対応の入口を比較対象から消さず、機能不足として記録する。

Codexはトップレベル関数・Series演算と、CSV／ParquetからのLazy実行の両方を確認した。Alopexには別の入口としてLazyFrameのstatic scanがあるため、Codexは同じ入力・計算・結果表現による機能と性能の比較も実行した。ただし同名関数への置換互換と、別名入口から同じ仕事を行う機能比較は別の判定とする。

最終確認runでは、Alopexの時間比はPolarsに対してCSVのcollectが1.916、全batch取得が1.945だった。Parquetの数値のみではcollectが0.819、全batch取得が0.857だった。一方、Parquetの文字列を含む計算は型不一致で失敗した。CodexはCSVの速度差と、入口・文字列計算の機能不足を別々に扱う。

## 同名入口の6ケースは未対応

| Polarsの呼び出し | Alopex v0.8.16の結果 | Polars 1.43.2の結果 |
|---|---|---|
| `select(lit(2).add(1))` | moduleにselectなし | 全値一致 |
| `Series("id", [0, 1, None])` | Seriesを直接構築できない | 全値・NULL一致 |
| 既存Seriesに対する`series + 1` | 演算子未対応 | 全値・NULL一致 |
| `LazyFrame({"id": [...]})` | LazyFrameを直接構築できない | 全値・NULL一致 |
| `scan_csv(path)` | moduleにscan_csvなし | 全行・全値一致 |
| `scan_parquet(path)` | moduleにscan_parquetなし | 全行・全値一致 |

Codexは各製品・入口を独立processで実行し、[公開wheelによる診断](confirmed-2/capabilities.json)へ例外を保存した。Codexはこれらの不足に速度比を与えない。Series演算の診断だけは、直接構築の不足と切り分けるため、事前にDataFrameから取り出したSeriesで演算を試す。このDataFrame利用は診断だけであり、後述の性能測定には入らない。

公開ソースの[登録関数](https://github.com/alopex-db/alopex/blob/d9ff8783b8d18a63d167204e55902ea6cd90dcd1/crates/alopex-py/src/types/mod.rs)はcol／lit／concat／concat_strを公開している。これらを使った先行比較が成立しても、他のトップレベル関数やSeries演算の互換性を証明したことにはならない。[互換台帳](https://github.com/alopex-db/alopex/blob/d9ff8783b8d18a63d167204e55902ea6cd90dcd1/docs/parity/polars-v1.43.2.json)はSeries・LazyFrame直接構築やトップレベルscanを未実装と記録しているが、トップレベルselectの行はなく、入口一覧にも不足がある。

## Lazy走査はDataFrameの明示構築を挟まず比較

CodexはAlopexの`LazyFrame.scan_csv`／`scan_parquet`とPolarsの`scan_csv`／`scan_parquet`から、同じfilter・数値・比較・論理・文字列式を実行した。計測はscan呼び出し、式の構築、ファイル読み込み、collectまたは全batchの取得までを含む。CodexはPython dict変換と全値検証を計測外に置いた。

| Lazy実行のケース | 時間比 ↓ | 処理量比 ↑ | trial別時間比の範囲 |
|---|---:|---:|---:|
| CSV・12列計算→collect | 1.916 | 0.522 | 1.617–2.023 |
| CSV・12列計算→全batch取得 | 1.945 | 0.514 | 1.853–1.965 |
| Parquet・12列計算→collect | 機能失敗、倍率なし | — | — |
| Parquet・12列計算→全batch取得 | 機能失敗、倍率なし | — | — |
| Parquet・数値等11列→collect | 0.819 | 1.220 | 0.818–0.894 |
| Parquet・数値等11列→全batch取得 | 0.857 | 1.167 | 0.852–0.902 |

Parquetの12列ケースは、Alopexが文字列連結で`type mismatch: expected Utf8, got LargeUtf8`となり失敗した。[初回診断のstderr](case-parquet-collect-alopex-trial0.stderr.txt)はこの失敗を保持する。Codexはこの2ケースを最終確認runの既定行列から除外し、独立した数値・比較・論理11列の比較を別ケースとして残した。数値のみの成功は、Parquet文字列計算の互換性を示さない。

先行の時間比1.645は構築済みメモリ入力からの計算であり、今回のファイル走査とは計測境界が異なる。Codexは両者の比率を混ぜず、旧0.135倍や先行の件数中心streaming比較も上書きしない。

## 全値検証と計測条件

| 条件 | 設定 |
|---|---|
| 公開製品 | alopex 0.8.16、Polars／runtime 1.43.2。製品ソースはd9ff8783、製品コード変更なし |
| 入力 | 既存fixture形状の34,250行。id Int64、label nullable String。同じCSV／Parquetファイルを両製品へ渡す |
| 計算 | 既存12列の算術・比較・論理・文字列式。数値のみは文字列連結を除く11列。filterはid≥0で全行通過 |
| 実行 | 各case／engine／trialを独立processで直列実行。3 warmups・21 samples・3 trials。製品順はtrialごとに交代 |
| CPU／thread | CPU0固定、Polarsと数値threadは1。実Polars thread poolも1。ホストは共有であり専有割当ではない |
| cache | 各workerが同じファイルを計測前に読み、warm filesystem cacheで比較。cold I/O比較ではない |
| 結果 | 全warmup／sampleで全列・全行のPython値・型・NULL・列順・行順を独立Python oracleと照合 |
| batch | chunk_size8192。Codexは全batchを取得してから計測外で全値を照合。一定メモリで処理し続ける試験ではない |

Codexは各processのsample中央値を求め、3 trialsの中央値同士を割って時間比を算出した。参照のPolarsを1とし、小さいほど速い。処理量比は同じ仕事量に対する逆数とする。Codexは[最終確認run](confirmed-2/)の値だけを採用し、[環境・パッケージ内容hash・fixture hash・測定コードhash](confirmed-2/environment.json)、各sampleのrawと終了statusを保存した。

最終確認runは24性能process・504測定sampleが正常終了し、各ケースの入力と全結果のhashが製品間・trial間で一致した。入口probeの12 processも正常終了したが、Alopexの6件は明示的なcapability-gapであり、互換性の成功には数えない。[相対値JSON](confirmed-2/relative.json)と[raw照合](result-verification.json)が採用結果を示す。測定コードの固定commitは017e52996ad4130c6a52064153c4f8d93d08e123とする。

Codexは資源の参考値としてprocess全体のpeak RSSとgetrusageのinput／output block数も保存した。ただし今回のRSSは全workerで同じ値となり、block数も全て0だった。Codexはこれらを製品間の資源比較の有効な証拠とは認定せず、メモリ・I/Oの優劣を未評価とする。両指標はoracle生成・検証・raw保存も含む。block数はbyte数ではなく、warm cacheのblock数0もファイル読み込みがなかったことを意味しない。

Codexは初回run中の文書lint依存導入を理由に、直下の初回速度比を採用しなかった。また最初の確認runは資源取得の環境依存で失敗した。Codexは両runの証跡を保持し、採用値と混ぜない。[事前計画と変更理由](plan.md)、[機能確認と失敗履歴](verification.json)が経緯を記録する。

## 再実行と改善対象

再実行者は隔離環境に`alopex==0.8.16`と`polars==1.43.2`を導入し、新しい出力directoryと一時fixture directoryを指定する。

```bash
rtk proxy python -B scripts/performance/polars_entrypoints_v0816.py --output <new-run> --data <temporary-fixtures>
```

runnerは既知のParquet文字列2ケースを既定でスキップする。再実行者が診断を必要とする場合だけ、`--case parquet-collect`または`--case parquet-batches`を明示する。runnerは既存証跡の上書きを拒否する。

性能担当者は成立したCSV比較などの性能差を[Issue #712](https://github.com/alopex-db/alopex/issues/712)で扱う。互換性担当者は同名入口の不足とParquet文字列の型不一致を機能の問題として扱う。Codexは機能不足を速度比や性能改善の受入条件へ混ぜず、Polars互換という目標の未達事項として残す。
