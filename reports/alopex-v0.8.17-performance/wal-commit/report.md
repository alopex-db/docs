# WAL commitの費用とspool書込み

spoolの書込み回数は大値KVで36回から19回、SQLで74回から38回に減りました。一方、commit時間の固定比較は4条件ともノイズ保留です。同期順序と復旧の確認は完了していますが、速度改善やメモリ増加の解消は認定していません。

基準版に対する重複同期削減後と、さらにframe/payloadをまとめた#817の2回の比較を収録します。異なるrunの比率差を#817単独の効果とは扱いません。先行結果もそのまま残しています。

## 同じfixtureで書込み回数の削減を確認

各診断はKV/SQL、値16/2048 bytes、基準/比較対象の8 writerと16 readerです。初期1件に2件を追加し、全値とSQL索引を新しい読み手で2回確認しました。最大fixtureは15,693 bytesです。

| 診断run | API / 値bytes | 基準spool書込み | 比較対象spool書込み |
| --- | --- | ---: | ---: |
| [42487505305](https://github.com/alopex-db/alopex/actions/runs/42487505305) | kv / 16 | 4 | 0 |
| [42487505305](https://github.com/alopex-db/alopex/actions/runs/42487505305) | kv / 2048 | 36 | 36 |
| [42487505305](https://github.com/alopex-db/alopex/actions/runs/42487505305) | sql / 16 | 10 | 0 |
| [42487505305](https://github.com/alopex-db/alopex/actions/runs/42487505305) | sql / 2048 | 74 | 74 |
| [42490399767](https://github.com/alopex-db/alopex/actions/runs/42490399767) | kv / 16 | 4 | 0 |
| [42490399767](https://github.com/alopex-db/alopex/actions/runs/42490399767) | kv / 2048 | 36 | 19 |
| [42490399767](https://github.com/alopex-db/alopex/actions/runs/42490399767) | sql / 16 | 10 | 0 |
| [42490399767](https://github.com/alopex-db/alopex/actions/runs/42490399767) | sql / 2048 | 74 | 38 |

小値ではinline経路によりspoolが不要になります。大値の#817はheader/sealのwrite各1回と、KV17回・SQL36回のwritevです。spool fsync→directory fsync→WAL fdatasync各1回を維持しました。traceの所要時間には観測とスケジューリングの影響が入り、性能判定には使いません。

## commit時間は両比較とも4条件がノイズ保留

各runは48 writer・96 reader、4条件を6組ずつ交互の順序で実行しました。初回の1組を除いた各5値で中央値とMAD（中央値からの絶対偏差の中央値）を求めます。`3 × max(MAD_before, MAD_candidate) / baseline_median` が5%を超えるとノイズ保留、それ以外で時間比が1.05を超えると増加調査、それ以外は5%内です。この幅は統計的な信頼区間ではありません。

### [比較42438307642](https://github.com/alopex-db/alopex/actions/runs/42438307642)

| API / 値bytes | 基準 ms | 比較対象 ms | 増減 | ノイズ幅 / 基準 | 判定 | RSS増加 bytes |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| kv / 16 | 0.651093 | 0.098367 | -84.89% | 21.69% | pending_noise | 712,704 |
| kv / 2048 | 0.632868 | 0.706431 | +11.62% | 48.62% | pending_noise | 761,856 |
| sql / 16 | 0.660782 | 0.124166 | -81.21% | 42.60% | pending_noise | 262,144 |
| sql / 2048 | 0.659499 | 0.746866 | +13.25% | 21.75% | pending_noise | 397,312 |

### [比較42490656351](https://github.com/alopex-db/alopex/actions/runs/42490656351)

| API / 値bytes | 基準 ms | 比較対象 ms | 増減 | ノイズ幅 / 基準 | 判定 | RSS増加 bytes |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| kv / 16 | 0.882953 | 0.155910 | -82.34% | 11.46% | pending_noise | 770,048 |
| kv / 2048 | 1.006597 | 0.895127 | -11.07% | 8.58% | pending_noise | 741,376 |
| sql / 16 | 0.830276 | 0.180893 | -78.21% | 10.71% | pending_noise | 299,008 |
| sql / 2048 | 1.030494 | 1.048484 | +1.75% | 28.30% | pending_noise | 348,160 |

今回の大値KV中央値−11.07%、SQL＋1.75%は観測値です。ノイズ保留を性能改善の認定へ置き換えません。小値SQLの比較対象には9.603254 msの標本もあり、除外していません。

## RSS差はcommit前から存在する

RSS増加はwriter全寿命の最大値の中央値差です。import、資産identity検査、DB準備も含み、WAL単体の割当量を表しません。以下は今回の各5標本の中央値です。

| API / 値bytes | import後RSS差 bytes | identity検査後RSS差 bytes | 物理書込み bytes 基準/比較対象 |
| --- | ---: | ---: | --- |
| kv / 16 | 204,800 | 180,224 | 8,192 / 4,096 |
| kv / 2048 | 249,856 | 233,472 | 12,288 / 12,288 |
| sql / 16 | 176,128 | 159,744 | 8,192 / 4,096 |
| sql / 2048 | 217,088 | 200,704 | 16,384 / 16,384 |

今回のtrace診断では8 writer中8件でcommit直前・直後のRSS内訳とsmaps_rollupの差分が0でした。区間内の一時的なpeakや割当ゼロの証明にはなりません。版間のRSS差ではfile-backed領域が大きく、匿名領域の差も残ります。対応するmappingやコード経路は分離していないため、原因は未確定です。PSSはRSSへ加算しません。commit区間のCPU・物理I/O・context switchの各標本はcomparison.jsonに保持しています。

## ソースと原本を固定して再計算する

| 費用比較run | 基準commit | 比較対象commit |
| --- | --- | --- |
| 42438307642 | `d995c550152e734ce821eb3de93180b533aad2f7` | `2ea6befef45fe6019c6976cfd8260371b0a57bde` |
| 42490656351 | `d995c550152e734ce821eb3de93180b533aad2f7` | `635d217d7dda9d42aafcce24aa8076463fa873b3` |

raw.jsonは暗号化原本から許可項目だけを抽出した全標本です。96 writer・192 readerの時間・資源値、16 writerのtrace集計とメモリ境界、製品/制御commit、資産・原本・各標本のhashを収録しました。元のPID、配置、接続設定やtrace中のパスは収録していません。原本の値・索引・再open、資産hash、全プロセスwaitと後片付けは独立監査済みです。この公開データだけで非公開の原本そのものを再監査できるわけではありません。

このディレクトリで次を実行すると、全標本の範囲・順序・型とmanifestを確認し、中央値・MAD・判定・本文を再計算します。

```sh
python3 -B wal_commit_report.py
```

先行するnative全読取りのhash検証によるRSS混入はstream読取りへ訂正済みです。訂正前の大値KV＋16.48%や、訂正後の増加・ノイズ保留も[#682](https://github.com/alopex-db/alopex/issues/682)に保持しています。診断42490399767では終了確認後のreader統計3件を既定の規則で除外しました。両費用比較の末尾除外は0件です。生存中の欠測を0で補完していません。

次はノイズ保留と資源増加を評価し、最終候補・配布資産へ証拠を対応付けます。この報告は#817の統合や#682全体・リリースの受入完了を意味しません。
