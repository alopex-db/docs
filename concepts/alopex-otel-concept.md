# Alopex OTel コンセプト — OpenTelemetry ネイティブのオブザーバビリティ基盤

**バージョン**: 1.0
**作成日**: 2026-07-29
**ステータス**: Concept（設計公開。実装着手の承認前）

---

## 1. 何を作るか

**Alopex OTel** は、Alopex DB・Skulk・Trail を Chirps クラスタ基盤上で統合した、OpenTelemetry ネイティブのオブザーバビリティプラットフォームである。

> 組み込みからクラスタまで、構成を作り直さずに成長できる OpenTelemetry プラットフォーム。

### 1.1 コアバリュー

**ダッシュボードとストレージが一体である。**

収集して保存するだけの製品ではない。**見るところまでが一つの製品に含まれる。** 可視化サーバーを別途立てる必要も、データソース設定を接続先ごとに管理する必要もない。ダッシュボードは自分のストレージを直接読む。

**その一体のまま、全スケールで動く。**

組み込みの 1 プロセスから N ノードクラスタまで、**同じ画面・同じ API・同じクエリ・同じダッシュボード定義**が使える。変わるのは応答時間と扱えるデータ量だけである。

ノートPCで作ったダッシュボードは本番クラスタでそのまま動き、逆にクラスタで使っていたものをエッジの 1 ノードへ持っていくこともできる。

この 2 点が本製品の存在理由である。Metrics / Traces / Logs の収集・処理・保存・検索・相関・可視化・アラート・SLO・クラスタ管理は、そのために一体で提供される。

なお、一体であることは**閉じることを意味しない**。Prometheus Query API 互換により、既存の Grafana からも同じデータを見られる（§8）。

---

## 2. 解く問題

OpenTelemetry は Metrics / Traces / Logs を生成し標準プロトコルで転送する仕様として普及した。しかし**永続ストレージ・検索・可視化・アラートを提供しない**。そのため実運用では複数のバックエンドを組み合わせることになる。

```text
Application → OTel SDK → OTel Collector
    ├── Prometheus / Mimir      (Metrics)
    ├── Tempo / Jaeger          (Traces)
    ├── Loki / Elasticsearch    (Logs)
    └── Grafana                 (可視化)
```

この構成が生む課題は5つある。

| 課題 | 内容 |
|---|---|
| 構成要素が多い | Signal ごとに異なるストレージ・クエリ言語・保持設定・運用 |
| 導入負担が大きい | 一つのアプリを観測するだけで Collector・保存先・可視化を別々に準備 |
| 開発と本番の分断 | ローカル構成をそのまま本番クラスタへ拡張できない |
| Signal 間の統合が弱い | 同じ障害を別々のシステムに保存するため横断分析が難しい |
| 拡縮が複雑 | Metrics / Trace / Log それぞれのクラスタを個別に拡張・縮小 |

Alopex OTel はこれらを単一の統合基盤として提供する。最小構成と大規模構成の違いは**製品構成ではなく、参加するノード数だけ**である。

---

## 3. Signal の配分 — 時系列とイベントを分ける

Alopex OTel の設計上の中核は、**Signal の性質に応じてストレージを使い分けつつ、利用者には一つに見せる**点にある。

### 3.0 分類基準

時系列とイベントを分ける基準は、**到着タイミングが決まっているか**である。

| 分類 | 定義 |
|---|---|
| **時系列** | 一定周期で到着する前提のデータ。多少のずれは許容するが、次がいつ来るかは既知 |
| **イベント** | 発生タイミングが決まらない。事象が起きたときに起きる |

この基準で配分は一意に決まる。

| Signal | 分類 | ストレージ | 理由 |
|---|---|---|---|
| **Metrics** | 時系列 | [Skulk](alopex-skulk-design-spec.md) | 収集周期が決まっている。列指向の圧縮とダウンサンプリングが直接効く |
| **Traces** | イベント | [Trail](../design/alopex-trail-proposal.md) | リクエストが来たときに発生し、周期がない |
| **Logs** | イベント | Trail | 何かが起きたときに発生する |
| メタデータ・索引・関係 | — | Alopex DB | 高選択度検索、SQL、グラフ、認可 |

周期を前提とした機構——固定間隔のパーティション、ダウンサンプリング、欠損補間——は、イベントに対しては意味を持たない。逆に、任意属性の列展開や型シャドーイングは、周期の定まった数値時系列には過剰である。

Span から派生させた RED メトリクスは、派生した時点で収集周期が定まるため**時系列**となり、Skulk 側へ置く。

### 3.1 イベントに late-bound schema が要る理由

**late-bound schema** はプログラミング言語の *late binding*（遅延束縛）から借りた語で、スキーマの束縛を読み取り時まで先送りする方式を指す。事前に宣言するスキーマが無く、後から定義する工程も無い。列は属性が到着した時点で生え、型は問い合わせた時点で決まる。

OTel の LogRecord と Span の `attributes` は任意の `AnyValue` である。送信側のライブラリ差やバージョン差で、**同じキーの型が変わることが日常的に起きる**。

```jsonl
{"service":"payment","http.status_code":500}
{"service":"payment","http.status_code":"upstream_timeout"}
```

厳格なスキーマを持つストレージにこれを入れると、**その瞬間に取り込みが止まる**。深夜に一つのサービスがデプロイされただけで、オブザーバビリティ基盤が落ちるということである。

Trail は型シャドーイングでこれを吸収する。物理列は `http.status_code@i64` と `http.status_code@str` に分かれ、読み取り時に coalesce される。**取り込みは決して止まらない。**

### 3.2 利用者からは一つに見える

保存先が分かれていても、クエリは統合される。

```sql
SELECT t.trace_id, t.duration, l.body, m.cpu_usage
FROM otel.traces t
LEFT JOIN otel.logs l ON t.trace_id = l.trace_id
LEFT JOIN otel.metrics m
    ON t.service_instance_id = m.service_instance_id
   AND m.time BETWEEN t.start_time AND t.end_time
WHERE t.status = 'ERROR';
```

Traces と Logs はいずれも Trail に載るため、この JOIN の大半は**同一ストレージ内で完結する**。

---

## 4. アーキテクチャ

```text
                         Alopex OTel
┌─────────────────────────────────────────────────────────────┐
│ OTLP / Pipeline / Query / Observe / Alert / SLO             │
├─────────────────────────────────────────────────────────────┤
│ Telemetry Coordination                                      │
│ Routing / Indexing / Correlation / Query Federation         │
├──────────────┬──────────────────┬───────────────────────────┤
│ Alopex DB    │ Alopex Skulk     │ Alopex Trail              │
│ Metadata     │ Metrics          │ Traces / Logs             │
│ Index / Graph│ Time / TTL       │ Late-bound schema         │
├──────────────┴──────────────────┴───────────────────────────┤
│ Alopex Chirps                                               │
│ Membership / Routing / Placement / Replication / Consensus  │
└─────────────────────────────────────────────────────────────┘
```

### 4.1 一つの分散アーキテクチャ

組み込み専用・単一ノード専用・分散専用のエンジンを**別々に実装しない**。すべての構成は同じアーキテクチャの配置差である。

```text
1プロセス → 2ノード → 3ノード以上 → 2ノード → 1ノード
```

組み込み構成でも Chirps の論理ルーティングを使う。ただし通信先が同一プロセスならネットワークを経由せず、ローカル高速経路へ最適化する。

```text
Chirps Logical Router
    ├── Local  → In-process call
    └── Remote → QUIC transport
```

これにより、組み込みからクラスタへ移行しても処理経路とデータモデルが変わらない。

### 4.2 三つのストレージは同一クラスタを共有する

Alopex DB / Skulk / Trail がそれぞれ独立したクラスタ管理を持つ構成にはしない。Chirps が単一の Control Plane として、全ストレージの配置・複製・移動を統合的に扱う。

---

## 5. 配置プロファイル

実装は一つだが、利用形態に応じたプロファイルを定義する。

| プロファイル | 用途 |
|---|---|
| **Embedded** | デスクトップ、CLI、エッジ、ローカル AI、開発環境、Alopex 製品の自己観測 |
| **Local Server** | 一つのサーバーで複数アプリを観測 |
| **Sidecar** | アプリ近傍でバッファ・秘匿化・初段サンプリング、中央へ転送 |
| **Compact Cluster** | 2〜3 ノードの Converged Node |
| **Scale-out Cluster** | Converged Node を必要数追加 |
| **Role-separated** | 同一バイナリに Role 制約（gateway / storage / query / observe） |

Role 分離は別アーキテクチャではなく**配置制約**である。

---

## 6. スケールアウトとシュリンク

ノードを追加すれば Ingest / Storage / Indexing / Query / Compaction / Tail Sampling / Replication が同時に増える。

```bash
alopex-otel node join --cluster observe-prod --seed node-1:7443
```

縮小時は Drain によって安全に離脱する。

```bash
alopex-otel node leave --drain
```

いずれも書き込み・読み取りを止めず、Query API も変わらない。**一ノードまで縮小できる**ことを要件に含める。

---

## 7. 自己観測

Alopex DB、Skulk、Trail、Chirps を導入すると、外部の監視製品を準備しなくても内部状態を閲覧できる。

- **Alopex DB**: query latency、transaction、WAL、MemTable、flush、compaction、cache、vector index、graph query、Raft、replication lag
- **Skulk**: ingest、partition write、compression、compaction、TTL deletion、downsampling、range scan、series cardinality
- **Trail**: ingest、column union、type shadowing 発生率、manifest 枝刈り効率
- **Chirps**: membership、SWIM probing、route resolution、QUIC connection、Raft election、placement update、rebalance

---

## 8. Alopex Observe — 一体であることの中身

### 8.1 分離構成で払っているコスト

ストレージと可視化が別製品であるとき、次のコストが常に発生する。一体構成ではこれらが**存在しない**。

| 分離構成のコスト | 一体構成 |
|---|---|
| 可視化サーバーを別途立て、認証・TLS・アップグレードを個別に運用する | Observe はストレージと同じプロセス／同じバイナリ |
| データソース設定を接続先ごとに管理し、URL・認証情報を同期する | Observe は自分のストレージを直接読む |
| ストレージのスキーマ変更を可視化側へ手で反映する | Trail のカタログから列集合を直接引く |
| 開発環境では可視化を諦め、ログを直接読む | 組み込み構成でも同じ UI が付いてくる |
| Signal ごとに別画面へ移動する | 同一 UI 内で辿れる |

### 8.2 マルチスケール — 画面は変わらない

Observe は配置プロファイル（§5）のすべてに付属する。

```text
Embedded（アプリプロセス内）  → localhost で Observe が開く。外部プロセスなし
Local Server（単一プロセス）  → 同じ画面。データ量だけが増える
Compact Cluster（2〜3 ノード） → 同じ画面。どのノードに繋いでも全体が見える
Scale-out Cluster（N ノード）  → 同じ画面。Query Federation が透過的に分散実行する
```

**画面・API・クエリ言語・ダッシュボード定義のいずれも、スケールによって変わらない。**

### 8.3 Signal 横断の導線

一体であることが最も効くのは、障害調査の動線である。

```text
Metrics でエラー率の跳ねを見る
  → その時間帯の Exemplar から Trace へ
  → 失敗 Span から、同じ trace_id の Log へ
  → Log の属性から、同じ service の他の Trace へ
```

分離構成では、この各矢印が「別画面を開いて条件を手で入力し直す」作業になる。一体構成ではリンクである。Traces と Logs が同じ Trail に載るため、**この導線の大半は同一ストレージ内で完結する**。

### 8.4 画面

Overview / Services / Metrics / Traces / Logs / Alerts / SLO / Cluster / Alopex Internal

UI の静的アセットはバイナリへ埋め込み、外部 Node.js ランタイムを必須としない。これにより組み込み構成でも UI が付いてくる。

---

## 9. 閉じないこと — Grafana からも見える

Observe を内蔵することと、既存のツールから使えることは両立する。

### 9.1 プラグインを書かずに Grafana から接続できる

**Prometheus Query API を実装する。** Grafana の組み込み Prometheus データソースは、Prometheus 以外の互換実装にも接続できることが公式に文書化されている。

> The Prometheus data source also works with other projects that implement the Prometheus querying API, including Grafana Mimir and Thanos.
> — Grafana 公式ドキュメント

これが決定的である理由は、Grafana のダッシュボード JSON が**パネルごとにデータソース種別を文字列で直書きする**ためである。

```json
"datasource": { "type": "prometheus", "uid": "$ds" }
```

独自のプラグイン ID を名乗ると、既存のダッシュボード資産がすべて使えなくなる。**Prometheus API を実装して組み込みデータソースから接続させれば、世に存在する Prometheus 向けダッシュボードがそのまま動く。**

### 9.2 最小実装で足りる

Grafana の互換性一覧表によれば、Thanos は Metadata API・Exemplars・Native histograms のいずれも未対応のまま「Prometheus 互換データソース」として成立している。`/api/v1/status/buildinfo` も 404 で正しくフォールバックする。

| エンドポイント | 要否 |
|---|---|
| `/api/v1/query` / `/api/v1/query_range` | 必須 |
| `/api/v1/labels` / `/api/v1/label/<name>/values` / `/api/v1/series` | 必須 |
| `/api/v1/query_exemplars` / `/api/v1/metadata` / `/api/v1/status/buildinfo` | 任意 |

いずれも **POST 受け付けが必須**である（Grafana のプラグイン定義が POST で登録している）。

### 9.3 ダッシュボード定義を出荷する

Grafana 向けのダッシュボード JSON を Alopex 自身の mixin として提供する。

Grafana のダッシュボードスキーマは `schemaVersion` を持ち、**13 以上であれば自動マイグレーションにより新しい Grafana でも読み込める**（現行は 42）。実証として、Tempo の mixin はリポジトリ内に schemaVersion 14 / 40 / 41 を混在させたまま運用している。**一度書けば長期間バージョン非依存で持つ。**

### 9.4 Traces / Logs も Grafana 互換とする

**全 Signal で Grafana 互換を目指す。**

| Signal | 互換対象 | Grafana 側 |
|---|---|---|
| Metrics | Prometheus Query API | 組み込み Prometheus |
| Traces | Tempo HTTP API + TraceQL | Tempo |
| Logs | Loki HTTP API + LogQL | Loki |

Traces / Logs の互換は Trail のクエリ層が担う。Trail は内部言語（Signal 横断 JOIN を持つ集計特化 DSL）を正典とし、TraceQL / LogQL は**共通論理プランへ desugar する互換フロントエンド**として実装する。

#### Prometheus との違い

Traces / Logs には、Prometheus のような「互換実装でも動く」という明文の保証が Grafana ドキュメントに**見つからない**。また Grafana 本体からデータソース実装が外部リポジトリへ切り出されており、要求される正確なエンドポイント集合を追跡しにくい。

一方で契約の実態は明確である。**Grafana は生の TraceQL / LogQL 文字列をそのまま転送する**（`GET /api/search?q={...}`）。したがって互換の要件は、

1. 彼らの文法を受理するパーサ
2. クエリパラメータとレスポンス JSON の形

の 2 点に尽きる。中間表現の互換は要求されない。

**文法のサブセット実装で実用に足る。** Grafana 自身が「Builder mode は一部の複雑なクエリをサポートしない」と認めており、複雑なクエリは Code mode に落ちる。

#### 順序

Prometheus 互換を先行させる。Metrics は Skulk v0.3.0 が既に Remote Write を持ち、OTel の MVP が Metrics から始まるためである。TraceQL / LogQL 互換は Trail v0.6 で追加する。

---

## 10. 現在地 — 何が揃っていて、何が要るか

**この企画は、複数製品の未実装マイルストーンの上に成立している。** 実装状況を正確に示す。

| 前提 | 現状 | 必要なマイルストーン |
|---|---|---|
| Metrics ストレージ | ✅ Skulk v0.3.0 で利用可能 | — |
| Prometheus Remote Write 受信 | ✅ Skulk v0.3.0 に実装済み | — |
| Skulk のクエリ | ❌ v0.3 は書き込みのみ | Skulk v0.4 |
| Trail（Traces / Logs） | ❌ 設計公開のみ、未実装 | Trail v0.1〜v0.3 |
| Skulk の Chirps 対応 | ❌ 依存ゼロ | Skulk v0.8 / v0.9 |
| Alopex DB の分散実行 | ❌ v0.7 は single-node compatible | Alopex DB v0.8 以降 |
| Trail の Chirps 対応 | ❌ 未計画 | 本企画で新規定義が必要 |

つまり **§6 のスケールアウト／シュリンクは、現時点ではどの製品でも動かない**。§8 の Observe も同様に未実装である。これは北極星として掲げる目標であり、達成済みの機能ではない。

一方で、**Metrics に限れば今日から作れる**。Skulk v0.3.0 は Prometheus Remote Write を受信でき、Parquet 列圧縮と TTL を持つ。MVP はここから始める。

---

## 11. MVP

依存の現状を踏まえ、動く範囲に絞る。

```text
OTLP/HTTP Receiver → Telemetry Pipeline → Telemetry Coordinator
    ├── Skulk      Metrics storage
    └── Alopex DB  Metadata / Index
→ Query → Alopex Observe
```

**対象**: Metrics のみ、OTLP/HTTP、Embedded / Local Server Profile、Resource / Service Catalog、SQL query、Metrics chart、TTL、一ノード構成

**見送る**: Traces / Logs（Trail v0.1 待ち）、Chirps 経由のルーティング（Skulk v0.8 待ち）、分散構成、PromQL（Skulk v0.4 待ち）、Profiles、TraceQL / LogQL、高度な Alert、SLO

---

## 12. ロードマップ

| フェーズ | 内容 | 前提 |
|---|---|---|
| M0 | 仕様と境界の固定 | — |
| M1 | Metrics 縦切り | Skulk v0.3.1 |
| M2 | PromQL、Rollup、**Prometheus Query API 互換 + Grafana ダッシュボード出荷** | Skulk v0.4 / v0.5 |
| M3 | Traces 縦切り | **Trail v0.2** |
| M4 | Logs 縦切り | **Trail v0.2** |
| M5 | Signal 横断クエリ | Trail v0.3 |
| M6 | Chirps 統合 | **Skulk v0.8** |
| M7 | スケールアウト／シュリンク | Skulk v0.9 |
| M8 | 分散クエリ | M7 |
| M9 | 運用機能（Alert / SLO / RBAC / Backup） | — |
| M10 | 互換性拡張（Prometheus Query API / Grafana / Jaeger / TraceQL / LogQL） | — |

---

## 13. 未確定事項

設計を固める前に決めるべきことを、隠さず挙げる。

1. **Trail の Chirps 対応** — Trail のロードマップに分散が入っていない。本企画が要求するなら Trail 側に追加が要る
2. **Skulk と Trail のコード共有形態** — Trail 提案の未決事項。OTel が両方を使う以上、この決定は OTel にも影響する
3. **Span の集約メトリクス** — RED メトリクスを事前に派生させて Skulk へ書くか、クエリ時に Trail から集約するか。派生先が Skulk であることは決まっており、生成タイミングのみ未決
4. **Trace の保持期間管理** — イベントには周期ベースのダウンサンプリングを適用できない。Trail の retention でどう表現するか
5. **着手時期** — 依存が揃うまで待つか、Metrics のみで先行するか

これらに意見がある場合は、[GitHub Discussions](https://github.com/alopex-db/alopex/discussions) へ。**API が固まる前が、最も反映しやすい。**

---

## 14. 関連ドキュメント

- [Alopex Skulk 技術仕様](../specs/alopex-skulk-technical-spec.md) — Metrics ストレージ
- [alopex-trail 構想提案](../design/alopex-trail-proposal.md) — Traces / Logs ストレージ
- [Alopex Skulk 要求仕様](alopex-skulk-requirements.md)
- [Skulk マイルストーン](../roadmap/skulk-milestones.md)
