# v0.8.17 SQL streaming固定比較

両製品で全結果をPython行として取得する比較では、候補は公開v0.8.16比17.87%短縮し、既定の改善条件を満たした。修正前との比較はノイズ幅5.86%で保留。DataFusion比7.0481倍の目標未達と、worker RSS約4.8%増加は残る。

[run 42446627765](https://github.com/alopex-db/alopex/actions/runs/42446627765)の24セル、stream504標本と計画504標本を収録した。各stream標本には最初の結果と全消費時間を対で保存している。warmup込み1,152観測区間について、資産・導入実体、入力と返却値、CPU・RSS・I/O、全workerの終了と回収を独立照合した。

## 全消費の結果表現を分ける

| 系統 | Alopex | DataFusion | 値の照合 |
| --- | --- | --- | --- |
| original | Python行iteratorを最後まで進める | Arrow batchを最後まで取得して行数を数える | ケース前後に全値、各標本に返却件数 |
| rows | 全結果をPythonの辞書のlistへ取得する | 全Arrow batchをPythonの辞書のlistへ変換する | 全warmup・標本で型・列順・全値・重複 |

SQLは`SELECT id, value FROM bench WHERE enabled = true`。入力は34,250行、返却は17,125行で、idは偶数、valueはidと同じ数値のfloatである。ORDER BYがないため、全値照合はidでソートして行う。全fixtureのid・value・enabledについても、ケース前後で件数・型・全値を照合した。

originalは既存consumerの比較境界を保持する。Python行の生成とArrow batchの取得は異なる責務なので、その比率をSQL engine内部だけの性能差と解釈しない。rowsは返却結果のPython表現まで揃える比較である。

同じ管理VM上で、公開版・修正前・候補・参照を各系統3試行、fresh processで逐次実行した。各区間は3 warmups・21 samples。対象順は系統・試行ごとに交替し、CPU割当とthread設定、DataFusionのtarget partitions=1を固定した。入力batch作成は元の8,192行単位を維持した。

## 比較資産と計時境界

| 対象 | source commit | wheel SHA256 |
| --- | --- | --- |
| published | `d9ff8783b8d18a63d167204e55902ea6cd90dcd1` | `ac9f4b1fd2fa0e78d634334242de4290ae4b34bf700515b59937ea2c718a98c3` |
| before | `34ce28d5c15377837cb78b15a261cfa2c05757a8` | `7508104cf08ada246cfd0cee832cbc97e50ce9364a26d846e7f0af1f987413c7` |
| candidate | `2ea6befef45fe6019c6976cfd8260371b0a57bde` | `a12adca9c5eb81ffa21d4fc3c2b55740af5b04b7083424831149f8183f810ed6` |

公開版はPyPI v0.8.16 wheel原本。修正前はSQL比較エラー生成、LSM走査、transaction journal等の採用変更前であり、変更群の比較として扱う。単一変更への因果帰属は行わない。候補`337de47da1b04e5e47a39833775f0903b6f46584`の製品crate/Cargoは測定資産のsourceと一致する。

参照はDataFusion 50.0.0、PyArrow 26.0.0、typing-extensions 4.15.0の公式wheelをhashで固定した。製品・参照の元資産と導入済みファイルを実行前後で照合している。source tree、構築run、wheel hashは[manifest.json](manifest.json)に保存した。

計画生成を先に測り、その後にstreamを取得した。元consumerの最初の結果・全消費時計と、close・返却物解放の位置を維持している。結果照合・raw保存・外部資源観測はlatency時計の外に置いた。計画生成は返却物の解放を時計の内側に含む。資源観測区間はconsumerの終了処理やcounter読取りを含むため、latencyと区間CPUの差をそのまま待ち時間とは扱わない。

## 全消費時間の判定

各試行の21標本中央値を求め、3試行の中央値で比較した。比率は候補/比較対象で、小さいほど速い。ノイズ幅は両対象の試行中央値MADの大きい方の3倍とする。baseline中央値の5%超で保留、範囲内で時間比1.05超を退行とした。改善採用は5%以上短縮、差がノイズ幅超、全3組が改善という条件を併用する。

| 系統 | 修正前 ms | 候補 ms | 候補/修正前 | 候補/公開版 | 候補/DataFusion |
| --- | ---: | ---: | ---: | ---: | ---: |
| original | 19.393737 | 16.060978 | 0.8282 | 0.8449 | 37.2287 |
| rows | 18.680030 | 15.198467 | 0.8136 | 0.8213 | 7.0481 |

originalの修正前比17.18%短縮、公開版比15.51%短縮は、ノイズ幅10.70%／10.22%により保留。rowsの修正前比18.64%短縮もノイズ幅5.86%で保留した。rowsの公開版比17.87%短縮はノイズ幅2.31%で改善条件を満たした。

DataFusionの全消費中央値はoriginal 0.431414 ms、rows 2.156403 ms。候補の参照目標は両系統で未達であり、参照比較のノイズ幅も5%を超えている。過去の別runの46.522倍と今回の比率を直接割り算して改善率にはしない。rowsとoriginalも消費処理が異なるので、両者の時間差をengineの改善量へ換算しない。

## 最初の結果・計画生成・資源増加

| 系統 | 最初の結果 修正前 µs | 候補 µs | 候補/修正前 | 判定 |
| --- | ---: | ---: | ---: | --- |
| original | 79.965 | 80.711 | 1.0093 | 既定条件内 |
| rows | 84.094 | 83.168 | 0.9890 | 既定条件内 |

全504 stream標本で、Alopexの最初の取得は1行、DataFusionは8,192行だった。rowsでも最初の取得量は揃わない。再計算JSONに製品間の数値比を残しているが、同じ量の結果を取得する速さの証明には使わない。originalの修正前比+0.93%も保持する。

| 系統 | 計画生成 修正前 µs | 候補 µs | 候補/修正前 | 判定 |
| --- | ---: | ---: | ---: | --- |
| original | 62.422 | 60.694 | 0.9723 | ノイズ超過・保留 |
| rows | 69.640 | 61.692 | 0.8859 | 既定条件内、改善採用は未証明 |

rowsの計画生成は全3組の改善条件を満たさない。公開版との計画比較は両系統ともノイズ超過で保留。AlopexはEXPLAIN JSON、DataFusionはlogical_planであり、この製品間比も同じ責務の性能目標には使わない。JSON中の`improvement_proven`は数値条件の判定であり、異なるAPIの比較可能性までは証明しない。

| 系統 / 区間 | 修正前RSS bytes | 候補RSS bytes | 増減 |
| --- | ---: | ---: | ---: |
| original-stream | 72,269,824 | 75,763,712 | +4.83% |
| rows-stream | 73,519,104 | 77,062,144 | +4.82% |
| original-plan | 72,245,248 | 75,739,136 | +4.84% |
| rows-plan | 72,241,152 | 75,792,384 | +4.92% |

RSSは各区間のkernel high-water観測値を標本内、試行間で集約した値で、import済みmoduleやfixtureを含むworker全体の使用量である。操作単独の追加割当量や正確な割当peakとは区別する。stream区間CPU中央値はoriginal 19.399→16.072 ms、rows 18.764→15.285 msだった。物理I/Oはread/write/cancelledを分けて保存した。全対象の試行別中央値とRSS観測最大値は[comparison.json](comparison.json)に収録している。

試行差を既存標本で照合した。originalの修正前の試行中央値は20.959／18.702／19.394 ms、候補は18.288／15.413／16.061 msで、区間CPUもそれぞれ20.972／18.713／19.399 ms、18.303／15.425／16.072 msと変化していた。rowsの修正前も経過時間21.003／18.680／18.315 msに対しCPU21.110／18.764／18.399 msだった。両系統・修正前/候補の252標本すべてで、物理read/write/cancelledの増分は0 bytesだった。

遅い試行ではCPU時間も増えている。ただし、処理経路の内訳やCPU周波数はこの比較では観測していないため、製品コード・allocator・実行環境のどれが原因かは確定できない。元のノイズ保留を維持し、追加診断は全消費処理のCPU内訳へ絞る。

## 標本と判定を再計算する

Python標準ライブラリのみで次を実行する。

```sh
python3 -B reports/alopex-v0.8.17-performance/run-42446627765/sqlstream_public_report.py
```

4 rawファイルのhash・サイズ・全座標、first/totalの組、返却件数と最初の取得件数、CPU/I/O差分、RSSを検査する。全試行の中央値・MAD・時間比・判定を再計算し、comparison.jsonとの完全一致により`verified`と1,008標本・4ファイルを返す。公開データは比較座標と許可した数値に限定している。

制御commitは`dfcd2c4d66117f3ccba060fe6c9d21febd7d0abd`。原本artifactは`13603523584`、digestは`sha256:db465fbfa44a275f86de57f85381637ebff139b12ee0d1fbb52a2984d5700164`。3行・8セルの事前確認、計時・全行・欠測・参照実体の23テスト、公開処理の7テストが成功した。全24 workerをwaitし、投入資産・venv・fixture・復号一時ファイルを削除した。終了後のmm統計消失2件は実終了をwaitで確認して末尾観測から除外し、生存中の欠測を0補完していない。暗号化原本と監査コードを保持する。

次は既存標本の試行差とRSS増加を処理経路に対応付けて評価する。#712の性能受入、#690の最終資産対応付け・RC認定・正式公開・公開後main統合は未完了である。
