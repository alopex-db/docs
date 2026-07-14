# モードパリティ検証・デモ仕様書

> **対象バージョン**: Alopex DB v0.6 以降（v0.7.1 で SF-CLUSTER を有効化）
> **ステータス**: ドラフト

## 概要

Alopex DB の中核価値は「ライブラリ（インメモリ）・組み込み（ファイル）・シングルノードサーバー・クラスタが、同一データファイルと同一プロトコル（API・SQL）で動作する単一エンジンである」ことである。
本仕様書は、この価値を**検証可能な不変条件**として定義し、それを実演（デモ）かつ機械検証（動作保証）するシナリオ・実行系を規定する。

成果物は次の 2 層で構成する。

- **検証層（S2）**: 不変条件を機械検証するスクリプト群。CI ゲートとして exit code で合否を返す。
- **デモ層（S1）**: 検証層と同一の SQL コーパス・検証クエリを用い、ストーリー仕立てで人間向けに表示するスクリプト。

デモ層は検証層の上に構築し、コーパス・期待値・正規化ロジックを共有する。二重管理は行わない。

---

## サーフェス定義

本仕様で「サーフェス」とは、エンジンへの到達経路を指す。

| ID | サーフェス | 到達経路 | データ形態 |
|----|-----------|---------|-----------|
| SF-MEM | ライブラリ（インメモリ） | `alopex-embedded` API / CLI `--in-memory` | メモリのみ（永続化なし） |
| SF-FILE | 組み込み（ファイル） | `alopex-embedded` API / CLI `--data-dir` | データディレクトリ |
| SF-HTTP | シングルノードサーバー（HTTP） | `alopex-server` の `/api/sql/query` | データディレクトリ |
| SF-GRPC | シングルノードサーバー（gRPC） | `alopex-server` の gRPC サーフェス | データディレクトリ |
| SF-CLUSTER | クラスタ（cluster-aware サーバー） | `alopex-server` を `[cluster] mode=cluster_aware`（単一メンバー）で起動した HTTP 経路 | データディレクトリ |

---

## 不変条件

### INV-1: 同一データファイル可搬性

SF-FILE / SF-HTTP / SF-GRPC はいずれも、他のサーフェスが作成したデータディレクトリを**そのまま**開き、読み書きできる。
あるサーフェスで書き込んだコミット済みデータは、別のサーフェスで開いたとき欠落なく可視である。

- 対象外: SF-MEM（永続化を持たないため、データファイル可搬性の対象から除く）
- 同時アクセスは対象外。サーフェスの切り替えは「前のプロセスを正常終了 → 次のプロセスが開く」順次アクセスで検証する。

### INV-2: プロトコル・結果等価性

同一の SQL 文は、すべてのサーフェスで**同一の結果**（正規化後に一致する結果集合、または同一のエラー分類）を返す。
SQL 方言・型システム・エラー体系はサーフェス間で分岐しない。

### INV-3: モード昇格の無変更性

利用者が SF-MEM → SF-FILE → SF-HTTP/SF-GRPC（→ SF-CLUSTER）へ移行するとき、SQL 文とデータ操作の意味は変更を要しない。変わるのは接続方法（パス・URL）のみである。

---

## 共有 SQL コーパス

### 構成

コーパスは `alopex/scripts/parity/corpus/` に配置する。

```
alopex/scripts/parity/
├── corpus/
│   ├── 01_ddl.sql          # CREATE/DROP TABLE, CREATE INDEX（BTREE/HNSW）
│   ├── 02_dml.sql          # INSERT（複数行）/ UPDATE / DELETE
│   ├── 03_query.sql        # SELECT, WHERE, ORDER BY, LIMIT/OFFSET, DISTINCT
│   ├── 04_join.sql         # INNER/LEFT/RIGHT/FULL/CROSS JOIN, USING, 派生テーブル
│   ├── 05_aggregate.sql    # GROUP BY, HAVING, COUNT/SUM/AVG/MIN/MAX/GROUP_CONCAT/STRING_AGG
│   ├── 06_subquery.sql     # スカラー / IN / EXISTS / ANY / ALL
│   ├── 07_vector.sql       # VECTOR 列, vector_similarity/distance, HNSW KNN（ORDER BY + LIMIT）
│   └── 99_verify.sql       # 検証クエリ（各シナリオの幕末で実行する共通アサート）
├── expected/
│   └── *.json              # 正規化済み期待値（ゴールデン）
├── runner/                 # Python パッケージ（経路実行・正規化・比較）
│   ├── __init__.py
│   ├── surfaces.py         # embedded / cli / http / grpc の各経路実装
│   ├── normalize.py        # 正規化規則の実装
│   └── report.py           # 合否・SKIP 集計と差分報告
├── verify.py               # S2 エントリポイント
├── demo.py                 # S1 エントリポイント
├── Dockerfile              # 検証コンテナ（後述）
└── requirements.txt        # Python 依存（バージョン固定）
```

組み込み API（Rust）経路のテストケースは `alopex/crates/alopex-embedded/tests/parity_corpus.rs` に配置する（「実行系の構成」を参照）。

- コーパスの SQL は `docs-public/specs/alopex-sql-dialect-spec.md` に定義された方言の範囲内とする。
- 結果順序が意味を持つクエリは必ず `ORDER BY` を明示し、順序非決定なクエリを含めない。

### 結果の正規化規則

サーフェスごとの出力（組み込み API の結果セット、CLI の `--output json`、HTTP レスポンス、gRPC レスポンス）を共通 JSON 形へ正規化して比較する。

1. 行は配列、列は列名をキーとするオブジェクトで表現する。
2. 浮動小数点値は有効数字 9 桁へ丸める（ベクトル距離・集約値の表現差を吸収する）。
3. NULL は JSON `null` で表現する。
4. エラーは「エラー分類コード + 対象オブジェクト名」へ正規化する。メッセージ文字列全体の一致は要求しない。
5. 実行時間・行数統計などのメタ情報は比較対象外。

---

## シナリオ S1: ライフサイクル昇格デモ「One Engine, Four Forms」

**目的**: INV-3 を軸に、同一 SQL・同一データが 4 つの形態を渡り歩く様子を実演する。各幕の終端が検証（アサート）を兼ねる。

**スクリプト**: `alopex/scripts/parity/demo.py`

| 幕 | サーフェス | 操作 | 幕末の検証 |
|----|-----------|------|-----------|
| 1 | SF-MEM | コーパス 01〜07 を実行 | `99_verify.sql` の結果が期待値と一致 |
| 2 | SF-FILE | 同一コーパスを `--data-dir` で実行 → プロセス終了 → 再オープン | 再オープン後も `99_verify.sql` が一致（永続性） |
| 3 | SF-HTTP / SF-GRPC | 第 2 幕のデータディレクトリで `alopex-server` を起動し、HTTP/gRPC で `99_verify.sql` を実行。サーバー経由で追加 INSERT | 第 2 幕のデータが可視 + 追加行を含む期待値と一致 |
| 4 | SF-FILE | サーバー停止後、同一ディレクトリを CLI で再オープン | サーバーが書いた行が可視（INV-1 の双方向性） |
| 5 | SF-CLUSTER | 第 4 幕のデータディレクトリで cluster-aware サーバー（単一メンバー）を起動し、HTTP で `99_verify.sql` を実行。cluster status（mode / node identity / membership）を表示 | 第 4 幕までの全データが可視で期待値と一致。status の `mode` が `cluster_aware`、`degraded` が false |

- 第 5 幕は v0.7 の cluster-aware foundation（単一メンバー、分散実行なし）を対象とする。マルチノードの分散実行は v0.8 以降の予約であり、本デモは扱わない。
- デモは各幕の SQL と結果を人間可読形式で表示しつつ、検証失敗時は非ゼロ exit で即座に停止する。

## シナリオ S2: サーフェス等価性マトリクス検証

**目的**: INV-1 / INV-2 を全組み合わせで機械検証する。CI ゲートの本体。

**スクリプト**: `alopex/scripts/parity/verify.py`

### S2-a: 実行経路の等価性（INV-2）

同一コーパスを次の 4 経路で独立実行し、正規化 JSON を相互 diff する。

| 経路 | 実行手段 |
|------|---------|
| 組み込み API | `cargo test` で実行する統合テストケース（`crates/alopex-embedded/tests/parity_corpus.rs`）。コーパスを実行し、正規化 JSON を成果物として出力する |
| CLI バッチ | subprocess で `alopex --batch --output json --data-dir <dir> sql -f <corpus>` |
| HTTP | Python HTTP クライアントで `/api/sql/query` |
| gRPC | `grpcio` + `alopex.proto` から生成した Python スタブで `AlopexService.ExecuteSql` |

組み込み API 経路のテストケースは、コーパス・データディレクトリ・ロール（writer / reader）を環境変数で受け取り、S2-b のマトリクスのセルとしても再利用する。

1 クエリでも不一致があれば失敗とし、不一致のクエリ・経路・差分を報告する。

### S2-b: データディレクトリの writer × reader マトリクス（INV-1）

書き込みサーフェスと読み取りサーフェスの全組み合わせで、`99_verify.sql` の一致を検証する。

| writer \ reader | 組み込み API | CLI | HTTP | gRPC | クラスタ |
|----------------|:---:|:---:|:---:|:---:|:---:|
| 組み込み API | ✓ | ✓ | ✓ | ✓ | ✓ |
| CLI | ✓ | ✓ | ✓ | ✓ | ✓ |
| サーバー（HTTP 経由の DML） | ✓ | ✓ | ✓ | ✓ | ✓ |

「クラスタ」reader は、cluster-aware モード（単一メンバー）で起動した `alopex-server` の HTTP 経路である。

各セルは「writer がコーパスを実行 → プロセス終了 → reader が同一ディレクトリを開き検証クエリを実行」の順次アクセスで検証する。

### S2-c: データファイルのバージョン互換

- `alopex-core` の互換フィクスチャ生成器（`generate_compat_v0_1.rs` 系）で生成した旧バージョンのデータディレクトリを、現行バージョンの全 reader サーフェスで開けることを検証する。
- 互換フィクスチャは対象バージョンの追加に合わせて拡充する。

## クラスタサーフェスの有効化（v0.7.1）

- SF-CLUSTER は v0.7 の cluster-aware foundation により有効化する。定義は「`alopex-server` を `[cluster]` セクションで `mode=cluster_aware`・`node_id`・`cluster_id`・`advertised_endpoint` を明示設定（単一メンバー）して起動した HTTP 経路」である。
- 有効化要件は予約条項のとおり「クラスタノードが既存データディレクトリを取り込み、同一コーパス・同一検証クエリが一致すること」であり、コーパス・期待値・正規化規則は変更なく用いる。
- ライブ実行のルーティング判定は `local_only` である。v0.7 は分散実行を行わず、複数ノードに跨る判定は `future_distributed_execution_required` としてクエリを拒否する。
- マルチノード（実分散実行）のセルは v0.8 以降の予約である。v0.7.0 機能そのもの（cluster status / join・leave / routing 診断 / DataFrame P3）の実証は `alopex-v07-feature-demo-spec.md` が規定する。

---

## 実行系の構成

### parity-runner（Python + cargo test）

経路実行のオーケストレーション・結果正規化・比較は **Python スクリプト**（`scripts/parity/runner/` パッケージ + `verify.py` / `demo.py`）で実装する。検証目的のコンパイル済みバイナリ（Rust `[[bin]]` 等）は追加しない。ビルドして使用するのは製品バイナリ（`alopex`, `alopex-server`）のみである。

```
python verify.py --corpus corpus/ --expected expected/ [--filter s2a|s2b|s2c]
python demo.py   --corpus corpus/
```

- 各経路の実装:
  - **組み込み API（Rust）**: `cargo test` の統合テストケース（`crates/alopex-embedded/tests/parity_corpus.rs`）として実装する。テストはコーパスを実行して正規化 JSON を出力し、期待値との一致を自己アサートする。`verify.py` は subprocess で `cargo test --test parity_corpus` を起動し、出力 JSON を回収して他経路との相互 diff に用いる。
  - **CLI**: `subprocess` で製品バイナリ `alopex` を起動。
  - **HTTP**: Python HTTP クライアント。
  - **gRPC**: `grpcio-tools` で `crates/alopex-server/proto/alopex.proto` から Python スタブを実行時に生成して用いる（生成物はコミットしない）。
- Python 依存は `requirements.txt` でバージョン固定する。
- 出力・比較は「結果の正規化規則」に従う。

### 検証コンテナ

検証系一式（`cargo test` / `verify.py` / `demo.py`）を実行するコンテナを準備する。

- **Dockerfile**: `alopex/scripts/parity/Dockerfile`
- **内容物**: Rust toolchain（CI と同一バージョンに固定）、Nim（SQL パーサーのビルド用）+ nimble 依存、Python 3.10+ と `requirements.txt` の依存
- **非 root 実行**: イメージに専用ユーザーを定義して `USER` を指定する。リポジトリをマウントして実行する際は `--user`/`HOME` を指定し、ホスト側に root 所有物を作らない
- **用途**: ローカル実行と CI で同一イメージを用い、検証環境の差異を排除する。コンテナ内での `cargo build` / `cargo test` は逐次実行とする

### スクリプト共通要件

1. **冪等性**: 一時データディレクトリは `tempfile` で作成し、終了時（異常終了含む）に必ず削除する。再実行時に前回の状態へ依存しない。
2. **ビルドは単発**: 冒頭で製品バイナリ（`alopex`, `alopex-server`）を**逐次**ビルドし、以後はビルド済み成果物を直接実行する。`cargo build` / `cargo test` の並列多重起動は行わない。
3. **exit code**: 成功 0 / 検証不一致 1 / 環境・起動エラー 2。
4. **サーバー管理**: サーバー起動はヘルスチェック（`/health` 相当）のポーリングで ready を確認してから検証を開始し、終了時（異常終了含む）に確実に停止する。ポートは空きポートを動的に割り当てる。
5. **正直な報告**: SKIP したケース（SF-CLUSTER 列、未対応経路）は SKIP として明示的に集計・表示し、成功数に含めない。

### CI 統合

- CI ジョブは検証コンテナのイメージ上で `verify.py` を実行する。ローカルと CI で依存環境（Rust toolchain、Nim、Python）を完全に一致させる。
- 既存の `crates/alopex-server/tests/cross_surface_consistency.rs` は継続して維持し、本検証系はその上位（プロセス境界・実データディレクトリを跨ぐ）検証として位置付ける。

---

## 受け入れ基準

1. `verify.py` が S2-a / S2-b / S2-c をすべて実行し、全マトリクスの合否・SKIP を集計表示して正しい exit code を返す。
2. `demo.py` が第 1〜4 幕を通しで実行でき、各幕末の検証が期待値と一致する。第 5 幕は SKIP と表示される。
3. 任意の 1 サーフェスで結果を意図的に破壊（期待値の改変）した場合に、`verify.py` が不一致箇所を特定して失敗する（検証系自体の検知能力の証明）。
4. コーパス・期待値・正規化ロジックが S1 / S2 間で単一ソースであること。

## 参照

- `docs-public/specs/alopex-sql-dialect-spec.md` — SQL 方言仕様
- `docs-public/roadmap/alopex-milestones.md` — バージョン対応表（v0.6 / v0.7 スコープ）
- `alopex/docs/server-guide.md` — サーバー設定・エンドポイント
- `alopex/crates/alopex-server/tests/cross_surface_consistency.rs` — 既存のサーフェス間一貫性テスト
