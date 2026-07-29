# Alopex Skulk マイルストーン

Alopex Skulk（時系列データベース）のバージョン系列と機能マッピング。

> **本系列は Alopex DB 本体とは独立している。** Skulk は独立したワークスペース・独立したリポジトリ（`alopex-db/alopex-skulk`）で開発され、`alopex-core` / `alopex-sql` 等の本体クレートに依存しない。バージョン系列も本体と無関係に進行する（本体 v0.7.4 に対し Skulk v0.3.0）。本体クレートの割り付けは [crate-version-feature-allocation.md](crate-version-feature-allocation.md)、本体のマイルストーンは [alopex-milestones.md](alopex-milestones.md) を参照。
>
> **Note (2026-07-29)**: v0.3.0 リリース後、ingest スループットと p99 レイテンシの固定目標が未達のまま open であることを受け、**v0.3.1 を緊急パッチとして割り込ませる**。これにより v0.4 の依存は v0.3.0 から v0.3.1 へ変更となる。
>
> **Note (2026-07-28)**: **Skulk v0.3.0 リリース済み**（crates.io 公開）。ストレージエンジンを自前 TSM/Gorilla から Arrow + Parquet の wide/columnar へ破壊的刷新した。v0.2 のオンディスク形式との互換性はない。
>
> **Note (2026-07-27)**: ストレージ刷新の技術決定（TDR#13）を最終確定。Arrow + Parquet(BROTLI q5) を採用し、**DataFusion は不採用**（自前クエリエンジン）。詳細は [技術仕様](../specs/alopex-skulk-technical-spec.md) を参照。

## バージョン対応表

| Skulk | 依存 | 主な機能 | 状態 |
|-------|------|----------|------|
| v0.1 | - | 基盤ストレージ（TSM v1、Gorilla 圧縮、WAL、MemTable） | ✅ リリース済 |
| v0.2 | Skulk v0.1 | Lifecycle（Retention/TTL、時刻パーティション、TSM Compaction、WAL truncate 連動） | ✅ リリース済 |
| **v0.3.0** | Skulk v0.2 | **ストレージ刷新（Arrow + Parquet wide/columnar）+ Ingest 3 プロトコル** | ✅ **リリース済**（2026-07-28、破壊的変更） |
| **v0.3.1** | Skulk v0.3.0 | **ingest スループット / p99 レイテンシ改善**（API・オンディスク形式は不変） | 🔴 緊急パッチ |
| v0.4 | Skulk v0.3.1 | Query（PromQL、SQL-TS、クエリ実行エンジン + predicate pushdown） | ⏳ 予定 |
| v0.5 | Skulk v0.4 | Downsampling（Downsampler、Continuous Query） | ⏳ 予定 |
| v0.6 | Skulk v0.5 | Server（HTTP API、Prometheus 互換エンドポイント、Self-monitoring） | ⏳ 予定 |
| v0.7 | Skulk v0.6 | Alert | ⏳ 予定 |
| v0.8 | Skulk v0.7 / Chirps v0.3 | Distributed | ⏳ 予定 |
| v0.9 | Skulk v0.8 / Chirps v0.6 | Replication | ⏳ 予定 |
| v1.0 | Skulk v0.9 | Stable | ⏳ 予定 |

外部依存は Chirps（合意・通信・メンバーシップ基盤）のみで、v0.8 以降の分散機能で利用する。v0.7 までは単一ノードで完結する。

---

## v0.3.0 ストレージ刷新（リリース済）

TDR#13 に基づき、ストレージエンジンを破壊的に刷新した。

### 変更の要点

| 項目 | v0.2 | v0.3.0 |
|---|---|---|
| データモデル | 単値 narrow（1 series = metric + tags → 単一 f64） | wide/multi-field（measurement = table、series key = tags、field = 独立列） |
| in-memory | 自前 TimeSeriesMemTable | Arrow RecordBatch |
| on-disk | 自前 TSM v3（`.skulk`） | Parquet |
| 圧縮 | 自前 Gorilla（DoD + XOR） | BROTLI 品質 5（純 Rust） |
| 索引 | 専用 Series Index Block + Bloom Filter | row group / page の min/max 統計による枝刈り |
| 耐久性 | WAL + TSM | WAL + Parquet + manifest の 3 層 |

### 受け入れ結果

達成した項目:

- **圧縮率** — 繰り返し値ワークロードで v0.2 Gorilla 比 7.149 倍、揮発ゲージで 1.553 倍の削減
- **フットプリント** — release バイナリ 3,664,464 bytes、C 依存クレートゼロ（純 Rust）
- **耐久性** — Ack 前永続化、原子的なファイル可視化、クラッシュ回復、単一ライタ排他

未達の項目（v0.3.1 へ）:

- **ingest スループット** — 固定目標に対し全経路で未達
- **p99 レイテンシ** — 専用の計測ハーネスが未整備で、目標の達成が確立していない

### 互換性

v0.2 のオンディスク形式（TSM / WAL）は読み込まれず、明示的に拒否される。インプレースの移行ツールは提供しない。v0.2 でエクスポートし、新しい v0.3 データルートへ再取り込みする必要がある。

---

## v0.3.1 スループット緊急対応（緊急パッチ）

v0.3.0 は機能・耐久性・圧縮・フットプリントの受け入れ条件を満たしてリリースしたが、ingest スループットと p99 レイテンシの固定目標が未達のまま open である。**目標を緩和せず据え置いた結果として open になっている**ため、緊急パッチとして割り込ませる。

### 未達の実測値

10,000 points / 100 series / 単一ライタ / ACK 前 fsync の条件で計測。

| 経路 | 固定目標 | 実測 | 判定 |
|---|---:|---:|:---:|
| Line Protocol decode | 500K points/s | 118.85–147.41K/s | FAIL |
| Remote Write v1 decode | 100K samples/s | 201.48–217.88K/s | PASS |
| Line Protocol → WAL ACK | 500K points/s | 34.141–37.760K/s | FAIL |
| Remote Write v1 → WAL ACK | 100K samples/s | 34.112–39.819K/s | FAIL |

耐久性を含めると、両プロトコルとも 35–40K/s に収束する。ストレージ側も同様に未達である（Parquet durable 260–406K points/s、WAL + flush 22.3–33.7K points/s）。いずれも p99 10ms 未満の目標には到達していない。

### 作業項目

1. **真因のプロファイル取得（先行必須）** — 被疑箇所はコードの静的読解と計測記録に基づく仮説であり、着手前に計測で確定させる。決め打ちで最適化を始めない
2. 行表現の見直し — 行ごとの owned string / map 構築のコスト削減
3. WAL 書き込みパスの見直し — フレームエンコードとバッチ append
4. 共通検証の見直し — 行単位バリデーション
5. p99 専用レイテンシハーネスの追加

### 受け入れ条件

**固定目標は緩和しない。** 計測記録の FAIL を PASS に変える計測結果を証跡として要求する。

### スコープ

公開 API とオンディスク形式は変更しない。v0.3.0 のデータルートはそのまま読める。

---

## v0.4 以降

### v0.4 Query（Skulk v0.3.1 依存）

- PromQL パーサー / AST（range vector、関数、集約、label matcher）
- SQL-TS 拡張（`TIME_BUCKET` / `RATE` / `DELTA` / `FIRST` / `LAST` 等の関数と型推論）
- クエリ実行エンジン（Parquet スキャン + tag predicate pushdown、downsample 自動選択、集約 / 演算子パイプライン）

v0.3.0 のリーダーは書き込み検証に必要な最小限の実装に留めており、述語プッシュダウンと列プロジェクションを含むフルクエリ実装は v0.4 で行う。**DataFusion は採用せず、自前で実装する**（TDR#13）。

### v0.5 Downsampling（Skulk v0.4 依存）

- Downsampler（集約ルール、raw → rollup 生成、保持期間ポリシー）
- Continuous Query（スケジューラ、再計算 / 遅延データ対応、冪等実行）

### v0.6 Server（Skulk v0.5 依存）

- HTTP API サーバー（ingest / query ルーティング、設定 / ログ、CORS / 認証方針）
- Prometheus 互換エンドポイント（`/api/v1/write`、`/api/v1/query`、`/api/v1/query_range`）
- Self-monitoring（内部メトリクス、ヘルス / ready、トレース / ログ相関）

### v0.7 Alert / v0.8 Distributed / v0.9 Replication / v1.0 Stable

v0.8 以降は Chirps（v0.3 / v0.6）に依存する。

---

## 関連ドキュメント

- [Alopex Skulk 技術仕様](../specs/alopex-skulk-technical-spec.md) — ストレージ設計の変遷と現行仕様
- [Alopex Skulk 要求仕様](../concepts/alopex-skulk-requirements.md)
- [Alopex Skulk 設計仕様](../concepts/alopex-skulk-design-spec.md)
- [alopex-trail 構想提案](../design/alopex-trail-proposal.md) — Skulk の追記機構を流用する派生製品の提案（Proposal）
- [Alopex / Chirps マイルストーン対応表](alopex-milestones.md) — 本体の系列
