# Alopex OTel コンセプト — OpenTelemetry ネイティブのオブザーバビリティ基盤

**バージョン**: 1.0
**作成日**: 2026-07-29
**ステータス**: Concept（設計公開。実装着手の承認前）

---

## 1. 何を作るか

**Alopex OTel** は、Alopex DB・Skulk・Trail を Chirps クラスタ基盤上で統合した、OpenTelemetry ネイティブのオブザーバビリティプラットフォームである。

Metrics、Traces、Logs の収集・処理・保存・検索・相関・可視化・アラート・SLO・クラスタ管理を一体で提供する。単一プロセスの組み込み構成から複数ノードの分散クラスタまで、**同一の API、データモデル、ストレージ形式**を使う。

> 組み込みからクラスタまで、構成を作り直さずに成長できる OpenTelemetry プラットフォーム。

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

## 3. Signal の配分 — 適材適所

Alopex OTel の設計上の中核は、**Signal の性質に応じてストレージを使い分けつつ、利用者には一つに見せる**点にある。

| Signal | ストレージ | なぜそこか |
|---|---|---|
| **Metrics** | [Skulk](alopex-skulk-design-spec.md) | 数値時系列そのもの。series が事前に定まり型も安定。列指向の圧縮とダウンサンプリングが直接効く |
| **Traces** | [Trail](../design/alopex-trail-proposal.md) | Span は時系列ではなく構造化イベント。attributes は任意、events は入れ子 |
| **Logs** | Trail | 同上。加えて時刻欠損の許容と body の任意性 |
| メタデータ・索引・関係 | Alopex DB | 高選択度検索、SQL、グラフ、認可 |

### 3.1 なぜ Traces と Logs に late-bound schema が要るのか

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

## 8. 現在地 — 何が揃っていて、何が要るか

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

つまり **§6 のスケールアウト／シュリンクは、現時点ではどの製品でも動かない**。これは北極星として掲げる目標であり、達成済みの機能ではない。

一方で、**Metrics に限れば今日から作れる**。Skulk v0.3.0 は Prometheus Remote Write を受信でき、Parquet 列圧縮と TTL を持つ。MVP はここから始める。

---

## 9. MVP

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

## 10. ロードマップ

| フェーズ | 内容 | 前提 |
|---|---|---|
| M0 | 仕様と境界の固定 | — |
| M1 | Metrics 縦切り | Skulk v0.3.1 |
| M2 | PromQL、Rollup | Skulk v0.4 / v0.5 |
| M3 | Traces 縦切り | **Trail v0.2** |
| M4 | Logs 縦切り | **Trail v0.2** |
| M5 | Signal 横断クエリ | Trail v0.3 |
| M6 | Chirps 統合 | **Skulk v0.8** |
| M7 | スケールアウト／シュリンク | Skulk v0.9 |
| M8 | 分散クエリ | M7 |
| M9 | 運用機能（Alert / SLO / RBAC / Backup） | — |
| M10 | 互換性拡張（Prometheus Query API / Grafana / Jaeger / TraceQL / LogQL） | — |

---

## 11. 未確定事項

設計を固める前に決めるべきことを、隠さず挙げる。

1. **Traces を Trail に置く判断** — Span を「時系列」と見るか「イベント」と見るかで分かれる。保持期間管理とダウンサンプリングは Skulk の lifecycle が適する面もあり、実装フェーズで再評価する
2. **Trail の Chirps 対応** — Trail のロードマップに分散が入っていない。本企画が要求するなら Trail 側に追加が要る
3. **Skulk と Trail のコード共有形態** — Trail 提案の未決事項。OTel が両方を使う以上、この決定は OTel にも影響する
4. **Span の集約メトリクス** — RED メトリクスを Span から派生させて Skulk に置くか、都度 Trail で集約するか
5. **着手時期** — 依存が揃うまで待つか、Metrics のみで先行するか

これらに意見がある場合は、[GitHub Discussions](https://github.com/alopex-db/alopex/discussions) へ。**API が固まる前が、最も反映しやすい。**

---

## 12. 関連ドキュメント

- [Alopex Skulk 技術仕様](../specs/alopex-skulk-technical-spec.md) — Metrics ストレージ
- [alopex-trail 構想提案](../design/alopex-trail-proposal.md) — Traces / Logs ストレージ
- [Alopex Skulk 要求仕様](alopex-skulk-requirements.md)
- [Skulk マイルストーン](../roadmap/skulk-milestones.md)
