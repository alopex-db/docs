# Skulk v0.3 公開サーフェス

このページは、Alopex Skulk v0.3.0 で公開されたサーフェスと、v0.3.x
パッチ系列で維持される範囲を記録する。ここにない将来構想を、現行版の
API として扱ってはならない。

Skulk は **Alopex DB 本体とは独立したリポジトリ・独立したバージョン系列**である。
本体の `alopex-core` / `alopex-sql` 等には依存しない。系列全体は
[Skulk マイルストーン](../roadmap/skulk-milestones.md) を参照。

## 現行版

**v0.3.0**（2026-07-28、crates.io 公開済み）。v0.2 からストレージエンジンを
破壊的に刷新した。

## ストレージ

現行のオンディスク形式は次のとおり。

| 項目 | 現行 (v0.3.0) |
|---|---|
| データモデル | wide/multi-field（measurement = table、series key = tags、field = 独立列） |
| in-memory | Arrow RecordBatch |
| on-disk | Parquet |
| ブロック圧縮 | BROTLI 品質 5（純 Rust） |
| 耐久性 | WAL + Parquet + manifest の 3 層 |
| 依存 | `arrow` + `parquet` のみ。C 依存クレートゼロ |

field の型は float / integer / unsigned / boolean / string の 5 種である。
ネスト構造・バイナリ・配列は現行の型では表現できない。

series identity は measurement と tags から決まり、**field 名を含まない**。

### 互換性

v0.2 のオンディスク形式（TSM / WAL）は読み込まれず、明示的に拒否される。
インプレースの移行ツールは提供しない。v0.2 でエクスポートし、新しい v0.3
データルートへ再取り込みする必要がある。

v0.3.1 は公開 API とオンディスク形式を変更しない。v0.3.0 のデータルートは
そのまま読める。

## Ingest

現行の取り込みプロトコルは次の 3 つ。いずれも HTTP から独立したデコーダとして
提供され、ひとつの取り込みサービスの背後に置かれる。

| プロトコル | 範囲 |
|---|---|
| Line Protocol | パーサー + バリデーション + series/field マッピング |
| Prometheus Remote Write v1 | float sample のみ |
| JSON | canonical 形式と単一ポイント形式 |

取り込みはリクエスト・行・展開後サイズ・バッファ・WAL の各段階で上限を持ち、
超過時は明示的なバックプレッシャーを返す。行単位の検証失敗は部分成功として
報告され、失敗した行の位置が相関付けられる。

### 現行版で対応しないもの

次はいずれも**明示的に拒否される**。将来対応の予定として扱ってはならない。

- Prometheus Remote Write v2
- metadata、exemplar、native histogram

## 現行版に含まれないもの

次は Skulk v0.3 の実装範囲ではない。

| 機能 | 予定 |
|---|---|
| クエリ実行（PromQL / SQL-TS） | v0.4 |
| 述語プッシュダウン、列プロジェクション | v0.4 |
| Downsampling、Continuous Query | v0.5 |
| HTTP サーバー、Prometheus 互換エンドポイント | v0.6 |
| Alert | v0.7 |
| 分散、レプリケーション | v0.8 以降 |

v0.3.0 のリーダーは書き込み検証に必要な最小限の実装である。これをクエリ機能
として扱ってはならない。

## 既知の未達項目

v0.3.0 は ingest スループットと p99 レイテンシの固定目標を**満たしていない**。
目標を緩和せず open のまま記録しており、**v0.3.1 で対応する**。

| 経路 | 固定目標 | 実測 | 判定 |
|---|---:|---:|:---:|
| Line Protocol decode | 500K points/s | 118.85–147.41K/s | FAIL |
| Remote Write v1 decode | 100K samples/s | 201.48–217.88K/s | PASS |
| Line Protocol → WAL ACK | 500K points/s | 34.141–37.760K/s | FAIL |
| Remote Write v1 → WAL ACK | 100K samples/s | 34.112–39.819K/s | FAIL |

計測条件は 10,000 points / 100 series / 単一ライタ / ACK 前 fsync である。
達成済みの項目（圧縮率、フットプリント、耐久性）と未達の項目は
[Skulk マイルストーン](../roadmap/skulk-milestones.md) に併記している。

## 関連

- [Skulk マイルストーン](../roadmap/skulk-milestones.md)
- [Skulk 技術仕様](../specs/alopex-skulk-technical-spec.md)
- [alopex-trail 構想提案](../design/alopex-trail-proposal.md) — Proposal。現行製品ではない
