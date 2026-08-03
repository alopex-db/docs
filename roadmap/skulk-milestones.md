# Alopex Skulk マイルストーン

Alopex Skulk（時系列データベース）のバージョン系列と機能マッピング。

> **本系列は Alopex DB 本体とは独立している。** Skulk は独立したワークスペース・独立したリポジトリ（`alopex-db/alopex-skulk`）で開発され、`alopex-core` / `alopex-sql` 等の本体 Rust クレートに依存しない。バージョン系列も本体と無関係に進行する。ただし optional な SQL-TS / PromQL text frontend は、Alopex が所有する Nim parser の versioned ABI と target 別成果物を利用する。この build/release dependency は Rust crate dependency と分けて明記する。本体クレートの割り付けは [crate-version-feature-allocation.md](crate-version-feature-allocation.md)、本体のマイルストーンは [alopex-milestones.md](alopex-milestones.md) を参照。
>
> **Note (2026-08-03)**: **Skulk v0.4.0 は 2026-07-30 にリリース済み**。Alopex v0.8.2 と v0.8.3 は parser contract `0.3.0` のまま既にリリースされ、`CREATE CONTINUOUS AGGREGATE` は含まない。Skulk v0.5 はこの新 statement を含む **Alopex v0.8.4 / parser contract `0.4.0`** の完全な先行リリースを開始ゲートとする。詳細は [Skulk v0.5 SQL パーサー準備状況](../reports/skulk-v0.5-sql-parser-readiness.md) を参照。
>
> **Note (2026-07-29)**: v0.3.0 リリース後、ingest スループットと p99 レイテンシの固定目標が未達のまま open であることを受け、**v0.3.1 を緊急パッチとして割り込ませ、同日にリリースした**。これにより v0.4 の依存は v0.3.0 から v0.3.1 へ変更となった。
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
| **v0.3.1** | Skulk v0.3.0 | **ingest スループット / p99 レイテンシ改善**（API・オンディスク形式は不変） | ✅ **リリース済**（2026-07-29） |
| **v0.4.0** | Skulk v0.3.1 / Alopex parser contract `0.2.0` | Query（PromQL、SQL-TS、クエリ実行エンジン + predicate pushdown） | ✅ **リリース済**（2026-07-30） |
| v0.5 | Skulk v0.4.0 / Alopex v0.8.4 parser contract `0.4.0` | Downsampling（Downsampler、Continuous Query） | ⏳ parser 先行リリース待ち |
| v0.6 | Skulk v0.5 | Server（HTTP API、Prometheus 互換エンドポイント、Self-monitoring） | ⏳ 予定 |
| v0.7 | Skulk v0.6 | Alert | ⏳ 予定 |
| v0.8 | Skulk v0.7 / Chirps v0.3 | Distributed | ⏳ 予定 |
| v0.9 | Skulk v0.8 / Chirps v0.6 | Replication | ⏳ 予定 |
| v1.0 | Skulk v0.9 | Stable | ⏳ 予定 |

Rust crate としての外部プロジェクト依存は Chirps（合意・通信・メンバーシップ基盤）のみで、v0.8 以降の分散機能で利用する。v0.7 までは単一ノードで完結する。Alopex Nim parser は optional text frontend の build/release dependency であり、contract と成果物を release gate で固定する。

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

## v0.3.1 スループット緊急対応（2026-07-29 リリース済み）

v0.3.0 の未達を調査し、オンディスク形式を変えず LP→WAL ACK 約4.9倍、
Remote Write→WAL ACK 約3.9倍を達成してリリースした。LP 500K points/s と
p99 <10ms の固定目標は緩和せず、Known Limitation として後続へ持ち越している。
実測と完了内容は
[Skulk v0.3.1 ingest performance](../reports/skulk-v0.3.1-ingest-performance.md)
を参照。

### v0.3.0 の出発点

10,000 points / 100 series / 単一ライタ / ACK 前 fsync の条件で計測。

| 経路 | 固定目標 | 実測 | 判定 |
|---|---:|---:|:---:|
| Line Protocol decode | 500K points/s | 118.85–147.41K/s | FAIL |
| Remote Write v1 decode | 100K samples/s | 201.48–217.88K/s | PASS |
| Line Protocol → WAL ACK | 500K points/s | 34.141–37.760K/s | FAIL |
| Remote Write v1 → WAL ACK | 100K samples/s | 34.112–39.819K/s | FAIL |

耐久性を含めると、両プロトコルとも 35–40K/s に収束する。ストレージ側も同様に未達である（Parquet durable 260–406K points/s、WAL + flush 22.3–33.7K points/s）。いずれも p99 10ms 未満の目標には到達していない。

### 完了内容と持ち越し

1. [x] 真因のプロファイル取得と段階 PoC
2. [x] 行表現の見直しと Line Protocol 高速パス
3. [x] WAL の借用バッチ append と checkpoint ストリーム化
4. [x] 共通検証の単一走査化
5. [ ] p99 <10ms と LP 500K points/s の固定目標（後続へ持ち越し）

### 受け入れ条件

**固定目標は緩和しない。** 計測記録の FAIL を PASS に変える計測結果を証跡として要求する。

### スコープ

公開 API とオンディスク形式は変更しない。v0.3.0 のデータルートはそのまま読める。

---

## v0.4 以降

### v0.4.0 Query（2026-07-30 リリース済み）

- [x] PromQL パーサー / AST（range vector、関数、集約、label matcher）
- [x] SQL-TS 拡張（`TIME_BUCKET` / `RATE` / `DELTA` / `FIRST` / `LAST` 等の関数と型推論）
- [x] クエリ実行エンジン（Parquet スキャン + tag predicate pushdown、downsample 自動選択、集約 / 演算子パイプライン）

DataFusion を採用せず、自前 Planner/Executor で実装した（TDR#13）。parser の tokenizer/parser/wire AST は Alopex Nim parser contract `0.2.0`、Skulk Rust は mapping 以降を担当する。v0.4 の resolution catalog は raw のみを登録し、v0.5 の rollup 登録に備えた coverage/capability 選択境界を実装済みである。

### v0.5 Downsampling（Skulk v0.4.0 / Alopex v0.8.4 parser 依存）

**実装開始ゲート**:

1. `.spec-workflow/specs/skulk-v0-5-0/` の Requirements で canonical grammar、AST、target matrix、percentile 入力モデルを固定する
2. Alopex Nim parser に `CREATE CONTINUOUS AGGREGATE` と wire contract `0.4.0` を実装する
3. 失敗を非ゼロ終了で伝播する Nim test harness を含む Ubuntu/Windows release gate を完走し、Alopex v0.8.4 と target 別 parser 成果物・checksum manifest を全て先行リリースする
4. Skulk が release asset と contract を exact pin し、consumer fixture を通してから parser-dependent task を開始する

parser PR を Alopex main に未リリースのまま置かない。merge は Alopex
リリース列への投入として扱い、tag/crates/Python/GitHub Release/parser
asset の公開完了を dependency gate とする。

- Downsampler（集約ルール、raw → rollup 生成、保持期間ポリシー）
- Continuous Query（スケジューラ、再計算 / 遅延データ対応、冪等実行）
- typed percentile（p50/p99）と rollup schema

parser と Skulk の過不足、責任分界、release gate の詳細は
[Skulk v0.5 SQL パーサー準備状況](../reports/skulk-v0.5-sql-parser-readiness.md)
を参照。

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
- [Skulk v0.5 SQL パーサー準備状況](../reports/skulk-v0.5-sql-parser-readiness.md) — parser/意味層/実行層の gap と先行リリース gate
- [alopex-trail 構想提案](../design/alopex-trail-proposal.md) — Skulk の追記機構を流用する派生製品の提案（Proposal）
- [Alopex / Chirps マイルストーン対応表](alopex-milestones.md) — 本体の系列
