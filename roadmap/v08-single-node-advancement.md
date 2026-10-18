# 単一ノードで成立する機能はv0.8系で先行する

更新日: 2026-09-27。実行トラッカー: [alopex#499](https://github.com/alopex-db/alopex/issues/499)。

既存ロードマップの予定版にかかわらず、クラスタ基盤なしで実装・受入検証できる機能はv0.8系へ前倒しする。SQLの関数・型・構文・実行最適化、認証と公開API、ストレージ、フォーマット移行、S3、単体サーバーの配備、実行時メモリ管理を含む。Chirpsの開発待ちでこれらを止めない。

本書は、従来の「v1.xの順番が来るまで着手しない」「分散協調が完了してからS3やruntimeへ進む」という版に基づく順序を置き換える。必要な技術依存と受入条件は維持する。実装済みとは扱わず、各Issueの証跡で完了を判断する。

## 実装テーマと公開版を分ける

v0.8.16の進行中の修正範囲は維持する。以下のv0.8.xマイルストーンは、前倒しする実装範囲を管理するためのテーマであり、全件を一度に出荷する条件ではない。具体的なv0.8.Nは、互換性と利用価値がまとまり、受入検証を終えた機能単位で確定する。内部の実装段階ごとに公開版を増やさない。

| 実装テーマ | 担当と到達点 | 移動した既存Issue |
| --- | --- | --- |
| [SQL・Server](https://github.com/alopex-db/alopex/milestone/27) | sql/coreの型・言語・実行、embedded/server/cli/pyの共通APIと認証 | #175, #176, #193, #194, #355, #438, #225, #226, #228, #269–#273, #445, #446 |
| [Storage Foundation](https://github.com/alopex-db/alopex/milestone/28) | coreのfilesystem access、WAL、artifact identity、atomic publish、dispatcher | #183, #237–#240, #253–#255 |
| [Format Migration](https://github.com/alopex-db/alopex/milestone/29) | coreのmanifest、capability、open判定、移行計画・実行・復旧 | #185, #188, #257–#264 |
| [Portable Backends](https://github.com/alopex-db/alopex/milestone/30) | core/serverのS3互換backendと単体サーバー配備 | #190, #241–#245 |
| [Runtime Residency](https://github.com/alopex-db/alopex/milestone/31) | core/sqlのHNSW・vector・columnar表現とメモリ管理、serverのHTTP QUERY | #199, #205–#209, #212–#224, #229–#231, #276–#278 |
| [Local Integration](https://github.com/alopex-db/alopex/milestone/32) | embedded/server間のartifact互換性とlocal migration・S3移行のE2E | #265, #268 |

表の番号はすべて`alopex-db/alopex`のIssueを指す。#177、#184、#186、#189、#191、#200のように単一ノードと分散の両方を集約する親Issueは、子Issueの完了まで追跡を続ける。親に旧版のmilestoneが付いていても、v0.8へ移した子Issueの着手・出荷を妨げない。

## SQLの将来計画も前倒しする

| 機能 | v0.8系の受入範囲 | 分散側の追跡 |
| --- | --- | --- |
| [INET/CIDR・ネットワーク関数 #175](https://github.com/alopex-db/alopex/issues/175) | HOST、NETWORK、NETMASK、MASKLEN、BROADCAST。型・比較・包含・index・保存・FFI・公開APIまで検証する | #500でdistributed round-tripとmixed-node互換性 |
| [PIVOT / UNPIVOT / UNION BY NAME #176](https://github.com/alopex-db/alopex/issues/176) | NULL、重複列、型統一、出力schema、列数・メモリ上限、全公開surface | #174/#500のcapability分類とparity |
| [階層テーブル名 #193](https://github.com/alopex-db/alopex/issues/193)、[CTE・alias #194](https://github.com/alopex-db/alopex/issues/194) | parser/FFI、名前解決、catalog、保存・再読込、全SQL名付け位置。KV keyはopaque bytesのまま | #500でdistributed descriptor/routingのidentity保持 |
| [ユーザーmetadata #355](https://github.com/alopex-db/alopex/issues/355) | table/column/row metadata、安定RowID、transaction原子性、compactionと保存形式互換性 | #500で対象データと同じowner/replication経路 |
| [Query Optimizer #502](https://github.com/alopex-db/alopex/issues/502) | 統計情報、scan/index選択、JOIN順序・方式、EXPLAIN、正確性と性能の比較 | 分散cost modelの完成は前提にしない |
| [単一ノードwildcard FROM #503](https://github.com/alopex-db/alopex/issues/503) | catalog snapshot、権限・schema、全体集約、AVGの正しいmerge、上限・cancel・EXPLAIN | 元の#195がremote scatter/shuffle/retry/parityを所有 |

日時、JSON、配列、統計集約、window、transaction、COPYなどの#137–#173はIssue上では完了済みである。古いロードマップの予定表記だけを根拠に再実装しない。実利用で判明した不足は#460/#467配下などv0.8.16の個別Issueで修正する。#225のcommit barrierにも既存実装があり、未充足の受入条件だけを補う。

SQL-TS固有の意味論は引き続きSkulkが所有する。WASMのように製品対象が異なる計画や、方式・利用要件が未確定の研究項目まで、クラスタ非依存という理由だけで単体サーバーの出荷条件へ加えない。

## 混在していた要件には別の実装ownerを置く

| 元Issue | v0.8で先行するIssue | 元Issueに残す要件 |
| --- | --- | --- |
| #275 commit結果不明・retry | [#504](https://github.com/alopex-db/alopex/issues/504): 単一serverの要求ID、durable dedup、結果照会、disconnect/restart | leader交代、別replicaへのretry、分散dedup |
| #191、#246–#251 Kubernetes | [#505](https://github.com/alopex-db/alopex/issues/505): 単体serverのService/volume/readiness/drain/Secret/TLS/restore/manifests | cluster join、membership/epoch、mixed-version rolling upgrade、cluster配備 |
| #267 migration E2E | [#506](https://github.com/alopex-db/alopex/issues/506): process crash、local ownership、resume、rollback、reader-safe reclaim | 分散lease喪失/failover、node間finalize、Chirps coordination |
| #481 Phase 1/2 | [#507](https://github.com/alopex-db/alopex/issues/507): CommitDelta、基本演算、JOIN/集約、derived stateの復旧・visibility | distributed delta propagationとnode frontier |
| #481 Phase 3 | [#509](https://github.com/alopex-db/alopex/issues/509): 単体cost selection、state共有、eviction、local version migration | cluster version migration、研究段階のhigher-order/recursive IVM等 |
| #441 Changefeed | [#508](https://github.com/alopex-db/alopex/issues/508): 単一DBのcommit順CDC、resume、retention、backpressure | Multi-Raft range stream統合、Chirps Durable、Iggy連携 |

既存Issueの受入条件のうち、実クラスタを使うSQLの型・名前・metadata検証は[#500](https://github.com/alopex-db/alopex/issues/500)、runtime/backendのcluster parityは[#501](https://github.com/alopex-db/alopex/issues/501)へ移す。元の分散要件を削除したり、単一ノードの成功で分散対応を完了扱いしたりしない。

## 待つのは技術依存だけにする

- transaction/API: #225 → #226 → #269–#272 → #273。Python #272は#270にも依存する。#480のsavepoint修正と重複実装しない。
- HTTP: #276 → #277/#278 → #231。cache/validator #230は#226を前提とする。
- storage: #237 → #238/#239、#237/#239 → #240。#253 → #254 → #255。分散backend境界 #256をdispatcherの単体実装の完了条件にしない。
- format/migration: #253 → #257 → #258 → #259。その契約でfixture #260とmigration #261 → #262 → #263 → #264を進める。cluster-wide negotiation #187はlocal capability判定とlocal executorの前提ではない。
- S3: #253/#254 → #241 → #242 → #243/#244 → #245。#265はlocal artifact互換性、#268はlocal migrationとS3実装を前提とする。
- memory/runtime: #212 → #213 → #214、#215 → #216 → #217、#218 → #219 → #220、#221 → #222、#223 → #224。新しい永続segmentはformat/migration contractへ接続する。
- incremental/CDC: #507のcommit delta生成・durability → #508。CDCはincremental JOINの完成を待たない。#509は#507と共通memory budgetに依存する。

v0.9に残すのは、#174/#500の分散SQL適合性、#440の実Multi-Raft接続、#441の分散Changefeed、#187のnode間capability/epoch/migration協調、#274/#275の分散visibility/retryである。#266/#267/#501のcluster E2Eも実クラスタの準備を必要とする。これらとv0.8の単体機能は、依存のない範囲で並行して進める。

Chirpsはv0.6.3まで公開済みで、Multi-Raft/TSOは実装されている。一方、Alopex mainの任意依存は0.5.2である。依存更新・adapter統合と、Chirps v0.7 Durableやcompatibility coordinationの未完了を分けて追跡する。公開版が存在するだけでAlopex側の統合完了とは扱わない。

## 出荷時の要件は維持する

各機能はparserだけで終わらせず、対象となるAST/FFI/planner/executor/storage/public APIと文書・デモまで揃える。保存形式を変える機能には旧データの読み込み、再起動、失敗時の復旧を要求する。性能改善は固定workloadで正確性と性能を別々に測る。

v2.0の全体受入は[#184](https://github.com/alopex-db/alopex/issues/184)で維持する。単一ノード機能の先行出荷を、分散対応やv2.0の完成と同一視しない。
