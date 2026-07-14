# v0.7 機能デモ・検証仕様書（cluster-aware foundation / DataFrame P3）

> **対象バージョン**: Alopex DB v0.7.1
> **ステータス**: ドラフト
> **前提仕様**: `alopex-mode-parity-spec.md`（SF-CLUSTER の定義・有効化条件はそちらが規定する）

## 概要

v0.7 は single-node compatible な cluster-aware release である。その中核価値は次の 3 点であり、本仕様はこれらを実演（デモ）かつ機械検証するシナリオを規定する。

1. **観測可能なクラスタ基盤**: node identity・membership lifecycle・cluster status schema が Server / CLI の各サーフェスから同一に観測できる。
2. **ルーティングの透明性**: すべての SQL 実行がルーティング判定を通り、その決定と理由が診断として観測できる。v0.7 のライブ実行は `local_only` であり、分散が必要な判定は partial result を返さず明示的に拒否される。
3. **DataFrame P3**: string / datetime / list namespace と explode / implode が Rust・Python の両サーフェスで決定的に動作する。

## 対象外（v0.7.0 リリース契約の Not Included に従う）

- 本番のリモート scatter-gather 実行、Raft ベースのメタデータ合意、分散トランザクション、Multi-Raft、Changefeed（v0.8 以降）
- マルチノードの実 join・ノード発見（v0.7 の join/leave はローカルノードの lifecycle 遷移である）
- alopex-py の Client / Transaction / ConnectionPool API（独立リリーストラック）

## シナリオ D1: クラスタ昇格パリティ

`alopex-mode-parity-spec.md` の S1 第 5 幕・S2-b「クラスタ」列がこれを規定する（本仕様では重複定義しない）。

## シナリオ D2: cluster status のクロスサーフェス実証

**目的**: 同一サーバー状態を Server admin API と CLI が等価に報告し、membership lifecycle（join / leave）と degraded フォールバックが観測できることを実証する。

**スクリプト**: `alopex/scripts/demo/v07/demo_cluster.py`

| 場 | 操作 | 検証 |
|----|------|------|
| 1 | 既定設定（single_node）でサーバー起動 | `GET /api/admin/status` の `cluster.mode` が `single_node`、degraded=false |
| 2 | `[cluster] mode=cluster_aware`（node_id / cluster_id / advertised_endpoint 明示、単一メンバー）で起動 | status の mode / identity / membership（自ノード 1 件）が設定値と一致。CLI `alopex server status` の表示フィールドが HTTP レスポンスの対応フィールドと一致 |
| 3 | `POST /api/admin/cluster/leave` → status 観測 → `join` → status 観測 | lifecycle_state が `leaving` → `active` へ遷移し、両サーフェスで観測一致 |
| 4 | `membership_source_available=false` で起動 | `mode=cluster_aware` のまま degraded=true、診断に chirps 不可が出る |

- 各場の検証は HTTP レスポンス（JSON）を正とし、CLI 出力はフィールド射影の一致で検証する。
- Python の `Database.cluster_status()` は静的プレースホルダ実装（issue #35）であるため本デモの検証対象に含めない。スクリプトはその旨を注記表示する（隠さない）。

## シナリオ D3: ルーティング透明性

**目的**: v0.7 のルーティング契約 — ライブは `local_only`、分散必要時は拒否、retry / backoff / idempotency / cancellation はシミュレーションハーネスの契約 — を実測する。

**スクリプト**: `alopex/scripts/demo/v07/demo_routing.py` + 検証コンテナでの `cargo test`

| 場 | 操作 | 検証 |
|----|------|------|
| 1 | cluster_aware サーバーへ SQL 実行し、応答の routing 診断を表示 | decision が `local_only`、reason が `single_resolved_target` または `placement_absent` |
| 2 | 検証コンテナで `cargo test -p alopex-cluster --test simulated_harness` を実行 | scatter-gather 判定・retry 境界・cancellation 記録・idempotency key 安定性の全テストが green |

- 場 2 は「シミュレーションハーネスの契約検証」であり、分散実行の実証ではない。スクリプトはこの区別を明示して表示する。
- 分散必要時の拒否（`future_distributed_execution_required`）は、本番サーフェスに placement を跨がせる操作用 API が存在しない（設計上の意図）ため、ライブでは再現しない。該当挙動はサーバー統合テストが担保しており、スクリプトはその参照を表示するに留める。

## シナリオ D4: DataFrame P3

**目的**: str / dt / list namespace と explode / implode が Python サーフェスで動作し、決定的な結果を返すことを実演する。

**スクリプト**: `alopex/scripts/demo/v07/demo_dataframe_p3.py`

| 場 | 操作 | 検証 |
|----|------|------|
| 1 | 固定サンプル列に対し `str.to_lowercase / contains / split / extract` | 手計算期待値と一致 |
| 2 | 固定タイムスタンプ列に対し `dt.year / month / weekday / convert_time_zone` | 手計算期待値と一致 |
| 3 | リスト列に対し `list.join / len / contains` → `explode` → `implode` | 手計算期待値と一致、explode→implode の往復が元と等価 |
| 4 | 同一入力で 2 回実行 | 全出力がバイト単位で一致（決定性） |

## 実行系

- ランナーはすべて Python スクリプトである。検証目的のコンパイル済みバイナリは追加しない。Rust 側の検証は `cargo test`（検証コンテナ内）で行う。
- 検証コンテナは parity 仕様の `alopex-parity` イメージを共用する。v0.7.0 以降は chirps リポジトリを `/chirps` に読み取り専用マウントする。
- exit code 規約: 成功 0 / 検証不一致 1 / 環境・起動エラー 2。
- サーバーはヘルスチェックのポーリングで ready を確認してから検証し、終了時（異常終了含む）に確実に停止する。ポートは動的割り当てとする。
- SKIP・注記（issue #35 の Python アクセサ制約など）は明示的に表示し、成功数に含めない。
