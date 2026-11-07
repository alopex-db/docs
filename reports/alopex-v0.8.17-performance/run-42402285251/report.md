# v0.8.17候補の固定SQL比較：8ケースは許容範囲内、2ケースは判定保留

候補 `4b88e084` のSQL 10ケースを公開v0.8.16・修正前・PostgreSQLと比較した。公開版と修正前に対して8ケースが事前の許容基準を満たし、`insert-commit` と `random-update-commit` は試行間の変動が大きいため保留した。aggregate・ordered・select-all・random-delete-commitでは改善の採用基準も満たした。

この結果だけではリリースを認定しない。保留2件とSQL以外の受入が残っている。進捗は [alopex #690](https://github.com/alopex-db/alopex/issues/690#issuecomment-6711135321)、性能目標全体は [#712](https://github.com/alopex-db/alopex/issues/712) で管理する。

## 10ケースの比較結果

時間比は「候補の時間 ÷ 比較対象の時間」で、小さいほど速い。判定は公開版・修正前の両方に対する基準による。許容範囲内でも時間が増えたケースは、その増加を残している。

| ケース | 候補/修正前 | 候補/公開版 | 候補/PostgreSQL | 判定 |
| --- | ---: | ---: | ---: | --- |
| aggregate | 0.6065 | 0.6014 | 8.6730 | 許容範囲内・改善基準を達成 |
| ordered | 0.5775 | 0.5548 | 22.8323 | 許容範囲内・改善基準を達成 |
| select-all | 0.8309 | 0.8211 | 0.7129 | 許容範囲内・改善基準を達成 |
| insert-rollback | 0.9786 | 0.9977 | 2.4529 | 許容範囲内 |
| insert-commit | 0.9494 | 0.9803 | 2.3980 | 変動超過・保留 |
| batch-insert-commit | 1.0338 | 1.0380 | 6.6713 | 許容範囲内・時間増加あり |
| random-get-hit | 0.9940 | 0.9943 | 2.7490 | 許容範囲内 |
| random-get-miss | 0.9898 | 1.0060 | 2.9230 | 許容範囲内・公開版から時間増加 |
| random-update-commit | 1.0213 | 1.0456 | 2.4249 | 変動超過・保留 |
| random-delete-commit | 0.0224 | 0.0224 | 1.8384 | 許容範囲内・改善基準を達成 |

`batch-insert-commit` は修正前比で3.38%、公開版比で3.80%遅くなった。`random-get-miss` は公開版比で0.60%遅くなった。5%以内の許容基準を満たすことと、退行が一切ないことは区別する。

PostgreSQLに対する時間比1以下を満たしたのは `select-all`。他の9ケースは参照性能目標に未達で、#712の目標として残る。修正前に対する大幅なDELETE改善も、PostgreSQL以上の性能を意味しない。

## 同一VMで120セル・2520標本を測定した

[実行 42402285251](https://github.com/alopex-db/alopex/actions/runs/42402285251) は、10ケース × 3試行 × 4対象の120セルを同一のnative Linux専用VMで逐次実行した。各セルは準備を終えてから3回のwarmupと21標本を測定し、試行ごとに対象の順序を反転した。通常CIには性能試験を追加していない。

| 対象 | 固定したsource・資産 |
| --- | --- |
| 候補 | [`4b88e0844b0a6cc1dab93a69a9e7bffbd8a1f39c`](https://github.com/alopex-db/alopex/commit/4b88e0844b0a6cc1dab93a69a9e7bffbd8a1f39c)、release profileで構築したserver・wheel |
| SQL修正前 | [`34ce28d5c15377837cb78b15a261cfa2c05757a8`](https://github.com/alopex-db/alopex/commit/34ce28d5c15377837cb78b15a261cfa2c05757a8)、同じ構築条件のserver・wheel |
| 公開v0.8.16 | [`d9ff8783b8d18a63d167204e55902ea6cd90dcd1`](https://github.com/alopex-db/alopex/commit/d9ff8783b8d18a63d167204e55902ea6cd90dcd1)のserverと公開済みwheelの原本 |
| PostgreSQL | 16.14。fsync・synchronous_commitを有効にした構成 |

aggregate・ordered・select-allは34250行、insert-rollbackは初期1行、残る6ケースは10000行を使う。batch-insertとrandom-getは1標本100操作、それ以外は1操作。表の比率は各ケースで同じ単位を比較している。

実行制御は [`566cfbe9`](https://github.com/alopex-db/alopex/commit/566cfbe92edcb1cb33aa2681f0a91cc057fbc2d2)、docsハーネスは [`5c3d068b`](https://github.com/alopex-db/docs/commit/5c3d068b9ce4d60fbc1608924882df13b0a27568)。資産のsource・receipt・hashと結果checksumを照合し、各runの停止・回収・削除、専用daemon停止と保存領域の回収を確認した。CPU配置などの実行パラメータは非公開プロファイルで保持している。

## 判定基準は実行前の定義を維持する

各試行の21標本の中央値を求め、その3個の中央値から対象ごとの代表値を求める。試行中央値の中央値からの絶対偏差の中央値をMADとする。比較対象の代表値をB、候補をC、両者のMADの大きい方の3倍をNとする。

- NがBの5%を超えた場合は変動超過として保留する。
- NがBの5%以内、かつC/Bが1.05以下なら許容範囲内とする。CがBを上回る増加は開示する。
- C/Bが1.05を超える退行は受け入れない。変動が大きくても退行の標識を消さない。
- 改善の採用には、5%以上の短縮、B−CがNを超えること、全3組の試行で候補が速いこと、保留でないことを要求する。

これは運用上の受入基準であり、統計的な同等性の証明ではない。[事前定義](https://github.com/alopex-db/alopex/issues/690#issuecomment-6578203208) と同じ基準を使った。

## 保留2件は原因を特定できていない

`insert-commit` のNは修正前代表値の8.09%、`random-update-commit` は26.93%で、いずれも5%を超えた。中央値が速く見えるINSERTも保留する。UPDATEの時間比は修正前比1.0213、公開版比1.0456であり、この増加も残す。

UPDATEは、全標本で対象ごとのserver書込み量が一定でも遅延が変動した。一方、server CPU統計の分解能は10 msで、約2 msの処理ではCPU差分の中央値が0となる。これをCPU処理がない証拠には使えない。fsync時間やスケジューラ待ちを直接測っていないため、環境起因とも製品起因とも断定できない。

次の検証は、原因を区別する仮説と実行上限を先に固定する。今回の試行を捨てたり、判定基準を緩めたり、合格するまで再実行したりしない。

## 公開データから判定を再計算できる

[comparison.json](comparison.json) に丸め前の比率・中央値・MADと判定、[manifest.json](manifest.json) にsourceと各データファイルのSHA256を保存した。`raw/` の10ファイルには全2520標本の時間と資源観測がある。

CPU・I/Oはプロセス別の区間差分、RSSは区間前後の観測値。RSSを単純合算してserverメモリ量や操作のpeakとは呼ばない。`lifetime_hwm_*` はプロセス生存期間の最大値で、SQL操作単独の最大値ではない。server名は1セル内だけで有効な匿名ラベルとし、OSのPIDや実行パスは公開しない。

このディレクトリで次を実行すると、ファイルhashと2520標本の網羅性を検査し、中央値・時間比・保留・改善判定を再計算できる。Python標準ライブラリだけを使い、DBは実行しない。

```sh
python3 verify_public_sql_report.py
```

元の非公開回収データには、[`3c533076`](https://github.com/alopex-db/alopex/commit/3c53307669311fd381fca7413a768a00d6d633f8) の独立検証を適用した。今回の公開データはその検証後、数値項目の許可リストを通して出力したもの。性能受入全体、RC認定、公開後の確認とmain統合は引き続き未完了である。
