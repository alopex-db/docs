# alopex-trail 構想提案 — late-bound schema のログ/イベントストア

**バージョン**: 1.0
**作成日**: 2026-07-29
**ステータス**: Proposal（合意形成用。実装着手の承認を得たものではない）

---

## 1. 概要

### 1.1 何を作るか

`alopex-trail` は、**late-bound schema** を採る追記専用のログ/イベントストアである。到着したイベントの属性集合から列を動的に構築し、Parquet に列指向で永続する。

alopex-skulk（時系列データベース、v0.3.0 リリース済み）が「スキーマ既定の時系列」を担うのに対し、trail は「スキーマ未定の半構造化イベント」を担う。両者は追記専用・列指向・Parquet 永続という同じストレージ基盤を共有し、上位のデータモデルだけが分かれる。

#### late-bound schema とは何か

プログラミング言語の *late binding*（遅延束縛）から借りた語である。束縛をできるだけ遅いタイミングまで先送りする、という意味であり、trail において遅延するのは**スキーマの束縛**である。

| 工程 | schema-on-write | **late-bound（trail）** |
|---|---|---|
| 書き込み前 | スキーマを宣言する | 宣言する対象が存在しない |
| 書き込み時 | 宣言に照合し、合わなければ拒否する | 到着した形をそのまま受ける |
| **読み取り時** | 宣言済みの型で読む | **このとき型を決める** |

**「後からスキーマを定義する」工程があるわけではない。** `CREATE TABLE` に相当する操作は存在せず、変更すべき既存のスキーマ定義も存在しない。列は、その名前の属性を持つイベントが到着した時点で生える。

遅延するのは**束縛**である。`status` という列を問い合わせたとき、整数として読むか、文字列として読むか、両者を統合した 1 列として読むかは、そのクエリが決める。同じデータに対して、利用者ごとに異なる束縛を与えられる。

利用者がスキーマを一度も意識しないことも可能である。既定の読み取りは全シャドー列を統合した論理列を返すため、型を明示する必要が生じたときだけ `status@str` のように書けばよい。

### 1.2 なぜ skulk では足りないのか

skulk v0.3.0 のデータモデルは、以下を型レベルで強制する（`crates/skulk/src/model/mod.rs`）。

| 制約 | skulk の実装 | ログ/イベントでの問題 |
|---|---|---|
| タイムスタンプ必須 | `timestamp: Timestamp`（非 Option, ns 固定） | ログは時刻欠損・時刻不正が常態 |
| tags / fields の二分 | `Tags = BTreeMap<String,String>` と `Fields` が別型 | ログに tag/field の区別は存在しない |
| 型は厳密に 5 種 | `FieldValue::{Float,Integer,Unsigned,Boolean,String}` | JSON/OTLP のネスト構造・バイナリを表現できない |
| 型衝突は拒否 | `column_role_conflict` エラー | 同一フィールドに int と string が混ざると取り込みが止まる |
| 最低 1 field 必須 | `validate_common_names` | payload が空のイベントを表現できない |

とくに最後の 2 点が決定的である。ログにおいて `status` が `200` の日と `"timeout"` の日があるのは日常的であり、これを拒否することは**取り込みの停止**を意味する。TSDB としては正しい厳格さが、ログストアとしては採用できない。

### 1.3 なぜ skulk の資産が使えるのか

一方で skulk v0.3.0 は、TSDB に必要な水準を超えて**汎用的な late-bound schema 機構をすでに実装している**。

`crates/skulk/src/store/buffer.rs` の `MeasurementBuffer::append` は、

- 未知の属性が到着したら列を新設し、**それ以前の全行に null をバックフィルする**（`DataColumn::new(role, prior_rows)`）
- その行に存在しない列は `append_null()` で埋める
- フラッシュ時に Arrow スキーマを構築して Parquet へ書き出す

という動作をする。これは schema-on-write の列 union そのものであり、trail が必要とする中核機構がすでに稼働・テスト済みであることを意味する。

trail はこの機構を主役に据え、TSDB 固有の制約（時刻必須・tag/field 二分・5 型固定・型衝突拒否）だけを外す。

### 1.4 本提案のスコープ

本書は**構想段階の提案**であり、以下を含む。

- データモデルと late-bound schema の方式
- skulk からの流用範囲の切り分け
- 段階的な実装計画
- 未確定事項の明示

本書は以下を**含まない**。

- 実装の着手判断（別途承認を要する）
- 性能目標の確定値（第 9 章で未確定として扱う）
- クレート名・API シグネチャ等の実装詳細

---

## 2. データモデル

```rust
pub struct Event {
    stream: StreamId,              // 論理ストリーム（skulk の measurement 相当）
    ts: Option<i64>,               // 欠損可。未指定なら取り込み時刻を採番
    attrs: Vec<(ColumnId, Value)>, // 任意の属性集合。事前定義なし
}

pub enum Value {
    Null, Bool(bool), Int(i64), Uint(u64), Float(f64),
    Str(Box<str>), Bytes(Box<[u8]>),
    List(Vec<Value>),              // ネスト対応
    Map(Vec<(Box<str>, Value)>),
}
```

### 2.1 skulk との差分

| 項目 | skulk | trail | 根拠 |
|---|---|---|---|
| 時刻 | 必須 `i64` | `Option<i64>` | ログは時刻欠損が常態。欠損時は取り込み時刻で補完 |
| 属性 | tags(`String→String`) / fields の二分 | 単一の属性集合 | ログに tag/field の区別は無い |
| 型 | 5 型固定 | Bytes / List / Map を追加 | JSON・OTLP のネスト構造を表現するため |
| シリーズ identity | `SeriesId = xxh64(measurement + tags)` | 持たない | series はカーディナリティ管理の概念。ログには不要 |

**シリーズ identity を持たない**ことは意図的な決定である。skulk の `SeriesId` は「同一系列の点を時間軸で束ねる」ための概念だが、ログイベントは独立した事象であり、束ねる単位は時刻範囲とストリームで足りる。

---

## 3. late-bound schema の実現方式

### 3.1 書き込み時 — 列の動的 union

skulk の `MeasurementBuffer` の動作を継承する。

1. イベントの属性を走査し、未知の属性名なら列を新設する
2. 新設列には、それ以前にバッファへ入った全行分の null をバックフィルする
3. 当該イベントに存在しない既存列には null を追加する
4. フラッシュ時、バッファ内の列集合から Arrow スキーマを構築して Parquet 1 ファイルへ書き出す

これにより「宣言なしに列が生える」が成立する。**skulk で既に動作している機構であり、trail 固有の新規実装ではない。**

### 3.2 型衝突の扱い — type-shadowing

skulk は同一列名の型変更を明示的に拒否する。trail はこれを **type-shadowing** で吸収する。

```
attrs: { status: 200 }        → 物理列 status@i64
attrs: { status: "timeout" }  → 物理列 status@str を新設（過去行は null バックフィル）
```

- 物理列は `{name}@{type}` の形で分離するため、Parquet の物理スキーマ上で衝突は起きない
- 読み取り時に論理列 `status` を要求されたら、同名の全シャドー列を **coalesce** する（行ごとに非 null な 1 つを採用）
- 型を明示的に指定したい場合は `status@str` として直接参照できる

この方式の要点は、**取り込みが決して止まらない**ことである。型の不整合は書き込み時のエラーではなく、読み取り時の解決対象として扱う。§1.1 で述べた「束縛が遅延する」とは、具体的にはこの解決を指す。

なお coalesce の際に同一行で複数のシャドー列が非 null になることはない（1 イベントの 1 属性は 1 つの型にしか振り分けられないため）。

#### 型の網羅と逃げ道

OTLP の `AnyValue` は string / bool / int64 / double / bytes / array / kvlist の 7 種を取り、**array の要素ごとに型が異なることすら許される**。シャドー列を primitive 型ごとに用意するだけでは表現しきれない。

Grafana Tempo は同じ問題を、4 つの型付きカラム（`Value` / `ValueInt` / `ValueDouble` / `ValueBool`）に加えて、

- **`ValueUnsupported`** — 収まらない値を JSON 文字列へ退避する optional カラム
- **`IsArray`** — 配列かどうかのフラグ

で解決している。Trail もこれに倣う。

| シャドー列 | 対象 |
|---|---|
| `@str` / `@i64` / `@f64` / `@bool` / `@bytes` | primitive |
| `@json` | array、kvlist、混在配列など、上記に収まらないもの。JSON 文字列として退避 |
| `@is_array` | 配列であることのフラグ |

**`@json` の逃げ道は必須である。** これがなければ OTLP の一部を表現できず、取り込みが止まる。

なお SigNoz は int64 と float64 を単一の `Float64` マップに統合しているが、これは 2^53 を超える ID 系属性で精度が失われる。**Trail は `@i64` と `@f64` を分離する。**

#### 型メタデータによる枝刈り

常に全シャドー列を coalesce すると読み取りコストが上がる。SigNoz は型メタデータ表を持ち、**型が既知のキーは単一列だけを読み、未知のキーに限って coalesce を生成する**という二段構えを採る。Trail も manifest の列サマリ（§3.3）を同じ用途に使う。

### 3.3 読み取り時 — manifest からのスキーマ引き当て

skulk の manifest が `ActiveFile` として保持するのは `(measurement, name, row_count, file_bytes, min_timestamp, max_timestamp)` のみで、**列集合もスキーマも記録しない**。skulk では全 Parquet が同一 measurement 内で同じ論理スキーマを持つ前提のため問題にならないが、trail ではファイルごとに列集合が異なるため、これでは列の所在を知るのに全 Parquet フッタを読む必要が生じる。

trail は `ActiveFile` を拡張する。

```rust
struct ActiveFile {
    stream: String,
    name: String,
    row_count: u64,
    file_bytes: u64,
    min_ts: Option<i64>,
    max_ts: Option<i64>,
    // 以下を追加
    columns: Vec<ColumnSummary>,   // (col_id, physical_type, null_count, min/max または bloom)
    schema_fingerprint: u64,       // 列集合のハッシュ
}
```

これにより以下が可能になる。

- **カタログ照会**（`SHOW COLUMNS FROM stream` 相当）を manifest だけで即答できる
- **ファイル単位の枝刈り** — `WHERE user_id = 'x'` に対し、`user_id` 列を持たないファイルを読まずに捨てる
- `schema_fingerprint` が同一のファイル群はスキャン計画を再利用できる

manifest の永続機構（2 世代 `current` / `previous` の rename + CRC32 + previous フォールバック）は skulk のものをそのまま流用する。ただし列サマリを載せる分、ファイルサイズ上限の引き上げが必要になる。

---

## 4. 追記パスの構成

```
デコーダ（OTLP logs / JSON Lines / syslog / 生バイト）
  → IngestBatch                         ← skulk の ingest 層を流用
  → Ingestor<S>（S: IngestSink）         ← skulk で既にジェネリック
  → TrailStore::ingest_batch
      1. ts 補完（欠損なら取り込み時刻）
      2. retention 検証
      3. WAL append_buffered ×N → sync() 1 回   ← ACK 境界
      4. StreamBuffer へ積む（動的列 union）
  → flush: stream × partition ごとに
      Parquet 原子公開 → manifest publish → WAL checkpoint
```

skulk の起動順序と 3 段階のクラッシュ境界（`AfterParquetPublish` / `AfterManifestPublish` / `AfterWalCheckpoint`）は設計としてそのまま踏襲する。skulk 側でクラッシュ回復テストによる検証実績がある構造である。

### 4.1 WAL の差分 — 列名辞書の分離

skulk の WAL は各行に列名を文字列で書き込む自己記述形式を採る。ログは同一の列名が反復して出現するワークロードであるため、trail は**列名辞書を WAL レコードとして分離**する。

- レコード種別に `Dict { col_id: u32, name: str }` を追加し、列名は初出時に 1 回だけ書く
- データ行は `col_id: u32` を参照する
- リカバリ時は辞書を先に再構築してから行を復元する

フレーミング（`[u32 len][payload][u32 CRC32]`）、torn tail の切り詰め、ハンドルの poisoning、間隔ベース fsync、rename によるチェックポイントは skulk の実装をそのまま用いる。

---

## 5. Parquet レイアウト

skulk の「Arrow フィールドメタデータで列の役割を自己記述させ、役割ごとにエンコードを選ぶ」方式（`skulk.column.kind`）は良好な設計であるため、語彙を差し替えて踏襲する。

| 列 | kind | エンコード |
|---|---|---|
| `_time` | `time` | DELTA_BINARY_PACKED |
| `_seq` | `ingest_seq` | 既定 |
| 低カーディナリティ属性 | `attr_dict` | RLE_DICTIONARY |
| 高カーディナリティ属性 | `attr` | 既定（辞書 OFF） |
| 本文 / バイナリ | `blob` | 既定 |

### 5.1 skulk と異なる点

- **ソート順は time-first とする。** skulk は tag 列名の辞書順を第 1 キーとするが、ログの支配的なクエリは時刻範囲走査であるため、時刻を第 1 キーに置く。
- **辞書化は自動判定とする。** skulk は tag 列を常に辞書エンコードするが、trail の属性はカーディナリティが事前に分からないため、書き込み時の推定で切り替える。

ブロック圧縮は **BROTLI 品質 5** を継承する。skulk の事前検証において、品質 11（既定値）に対し圧縮率の差は 0.47%（誤差範囲）であるのに対し速度は約 46 倍という結果が得られており、品質 5 が妥当な選択であることが確認されている。

依存は `arrow` + `parquet(brotli)` のみとし、**C 依存ゼロ・純 Rust** を維持する。

---

## 6. compaction の設計

skulk の compaction は重複解決キーが `(Tags, Timestamp)` であり、完全に TSDB のセマンティクスに依存する。trail は用途が異なるため別設計とする。

- **重複排除を行わない。** ログは同一内容の行が正当に重複しうるため、dedup は意味的に誤りである。
- 代わりに、**`schema_fingerprint` が近いファイル群をマージ**して列の断片化を解消する。
- マージ時に **sidecar 索引**（列 bloom、高カーディナリティ属性の inverted index）を任意で付与する。

「読む → 変換 → 書く → manifest で原子的に差し替える」という骨格は skulk から借用する。

### 6.1 グルーピングキーにスキーマ指紋を含める

**スキーマが異なるファイルは統合できない。** Grafana Tempo は compaction のグルーピングキーにブロックのフォーマット版と dedicated column の割り当てハッシュを含めており、コード中に「同じ版のブロック同士を、同じ dedicated column のブロック同士を必ず一緒にする」と明記している。

late-bound schema では列集合がファイルごとに異なるため、この制約はより強く効く。Trail は次をグルーピングキーとする。

```
(stream, time_window, schema_fingerprint)
```

指紋が異なるファイルを混ぜると、統合後のスキーマが両者の union となり列が肥大化する。**近い指紋を優先的にまとめ、遠い指紋は別グループに残す。**

### 6.2 再書き込み回数の上限

Tempo は `MaxCompactionLevel` により、一定回数以上 compaction されたブロックを対象から外す。**古いデータを何度も書き直さない**という方針である。

Trail も compaction レベルを持ち、上限を設ける。これは §7.1 の保持階層とも整合する — 古いデータに対する追加 I/O を避けるという同じ判断に基づく。

---

## 7. 保持・サンプリング・統計

イベントは量が多い。時系列であれば古いデータを粗い粒度へダウンサンプリングできるが、**イベントには周期がないため同じ手法が使えない**。

本節の設計は、参照実装（Grafana Tempo、SigNoz、OpenTelemetry Collector）の実装を調査した上で定めた。**独自の語彙を作らず、OpenTelemetry 仕様および既存実装の用語に合わせる**ことを原則とする。調査で判明した反証は §7.7 に記録する。

### 7.1 保持階層 — 軸は圧縮率ではなく媒体コスト

「古いデータをどうするか」に対する答えは、削除だけではない。ただし**階層化の軸を圧縮率に取るのは誤り**である。

Tempo は Parquet の圧縮を snappy に固定し、年齢別のコーデック設定を持たない。利用している parquet-go は BROTLI をサポートしているにもかかわらず使っていない。さらに `MaxCompactionLevel` により**古いブロックの再書き込み回数を制限している**。再圧縮は、この制限が避けようとしている I/O を増やす行為にあたる。

SigNoz は ClickHouse の TTL を使い、`TO VOLUME '<cold>'`（媒体移動）と `DELETE` を併用する。ClickHouse は `RECOMPRESS` も持つが、**使っていない**。

したがって Trail の保持階層は**媒体コストを軸**とする。

| 階層 | 内容 | 媒体 | 取り出し |
|---|---|---|---|
| **Hot** | 全件。通常の Parquet、sidecar 索引あり | ローカル SSD | 即座 |
| **Cold** | 全件。同一形式のまま媒体のみ移動。索引は manifest 側に残す | オブジェクトストレージ等 | ネットワーク往復分だけ遅い |

**形式は変えない。移すだけである。** これにより再圧縮の I/O が発生せず、読み取り経路も同一のまま保てる。

圧縮パラメータを年齢で変える案は、**測定してから判断する**。compaction が既にファイルを書き直す契機であれば追加コストは小さいが、Tempo が意図的に避けている以上、根拠なく採用しない。

### 7.2 解像度の並置 — 元データを要約で置き換えない

集計済みデータを持つ場合、**元データの置き換えではなく、別解像度として並置する**。

SigNoz はメトリクスについて `samples_v4` / `samples_v4_agg_5m` / `samples_v4_agg_30m` の 3 つを並置し、クエリの時間範囲に応じてルーティングする。粗い表を作っても細かい表は消さない。削除は TTL が別途行う。

Tempo は metrics-generator でトレースから RED メトリクスを抽出し、**Prometheus という別ストアへ書き出す**。トレース本体を要約で置き換えるのではない。

Trail もこれに倣う。統計サマリ（§7.4）は元データとは独立に存在し、**サマリの生成が元データの削除条件にならない**。元データの削除は retention policy が単独で決める。

### 7.3 サンプリング — OTel の adjusted count に従う

サンプリングは**利用者が明示的に選ぶ**手段であり、既定では行わない。

#### 語彙は OpenTelemetry 仕様に従う

独自の `_sample_rate` は定義しない。OpenTelemetry には仕様化された機構が既に存在する。

| 用語 | 意味 | 所在 |
|---|---|---|
| **adjusted count** | そのイベントが代表する件数。サンプリング確率の逆数 | OTel 仕様 |
| **threshold（`th`）** | 56 ビット固定小数のサンプリング閾値 | W3C tracestate の `ot=` セクション |
| **R-value（`rv`）** | サンプリング判定に用いる乱数 | 同上 |

Span の `trace_state` フィールド（`trace.proto`）にこれらが載る。**Trail は専用列を新設せず、`tracestate` 文字列をそのまま保持し、読み取り時にパースする。** Tempo が採る方式であり、冗長な列を増やさない。

パースコストが問題になる場合に限り、materialize を検討する。その判断は測定に基づく。

#### 補正の規則

adjusted count による補正には、実装から学んだ規則がある。

**確率的丸め（stochastic rounding）を行う。** 素朴に `count × (1/probability)` を足すと小数が発生し、カウンタ系の下流を壊す。R-value を乱数源として `floor(m)` または `floor(m)+1` に丸め、期待値を保ちながら各イベントの寄与を整数にする。

**集約関数ごとに補正の要否が異なる。**

| 集約 | 補正 |
|---|---|
| COUNT / SUM / rate | 補正する |
| AVG | 加重平均として補正する |
| 分位数 / ヒストグラム | 補正する |
| **MIN / MAX** | **補正しない**。極値はサンプリングでスケールしない |

**「不明」と「0」を区別する。** tracestate に threshold が無い場合は「情報なし」であり、呼び出し側が 1.0 にフォールバックする。「決してサンプルされない」を意味する 0 とは別物である。

**補正はオプトインとする。** 既定で常に補正すると、サンプリングしていない環境で tracestate の残骸により値が壊れる。クエリ側で明示的に要求した場合のみ適用する。

#### 補正より前に、補正不要な地点で集計する

OpenTelemetry Collector のドキュメントは、span からメトリクスを生成する処理を **tail sampling の前に置く**よう指示している。サンプリングで捨てられる前に集計すれば、そもそも補正が要らない。

Trail もこの順序を推奨する。補正は「集計地点をサンプリング前に置けない場合」の手段である。

#### サンプリングの段階

| 段階 | 実行時点 | 目的 |
|---|---|---|
| **Head sampling** | 取り込み時、個々のイベント単位 | 取り込み量の即時削減 |
| **Tail sampling** | 取り込み時、相関グループ単位 | 「エラーを含む trace は全 span 残す」など、結果を見てから決める |

Head sampling は**ハッシュ方式ではなく threshold 方式**を採る。ハッシュ方式は多段サンプリング時に「1 段目を通過したものが 2 段目も必ず通過する」問題があり、OTEP-235 の threshold 方式はこれを解決するために作られた。

Tail sampling は本質的に `decision_wait` 幅の時間窓バッファである。バッファ上限（保持 trace 数、待機時間）を持ち、超過分は head sampling の結果に従って確定させる。**判定の遅延がバックプレッシャの原因にならないこと**を要件とする。

### 7.4 統計サマリ

compaction 時にマージ可能な集計構造を生成する。**これは元データの置き換えではなく、追加の解像度である**（§7.2）。

| 統計量 | 構造 | 備考 |
|---|---|---|
| 分位数 | **exponential histogram**（= DDSketch、Prometheus の native histogram と同等） | OTLP から入ってくる形式そのもの。変換不要 |
| 相異なり数 | HyperLogLog | Tempo がカーディナリティ制限に使用 |
| 頻出値 | Count-Min Sketch / Space-Saving | 参照実装に前例なし |
| 数値集計 | 合計・最小・最大・二乗和 | 平均と分散を後から算出可能にする |

**新しい語彙を作らない。** 「マージ可能スケッチ」と呼んでいたものは、この生態系では exponential histogram（OTel）、native histogram（Prometheus）、DDSketch（Datadog 由来）の 3 つの名を持つ。OTLP から届くのは exponential histogram であり、**それをそのまま格納するのが最短路**である。

サマリの粒度は `(stream, 属性グループ, 時間バケット)` を単位とし、対象属性は設定で明示指定する。全属性の組み合わせを持つとカーディナリティが爆発する。

> **前例の不在について**: SigNoz はスケッチ用のロールアップ表を持たず、コード中に `// we don't have any aggregated table for sketches (yet)` と未実装であることを明記している。compaction 時のスケッチ事前計算は**実装例が存在しない領域**であり、差別化の余地であると同時に、設計を自力で正当化する必要がある。

### 7.5 統計クエリ API

サマリは通常のクエリから透過的に使えることを要件とする。

```sql
SELECT service, percentile(duration_ms, 0.99) AS p99
FROM trail.events
WHERE stream = 'api' AND _time > NOW() - INTERVAL '7 days'
GROUP BY service;
```

プランナは次を判断する。

1. 要求された時間範囲と粒度がサマリで満たせるか
2. 満たせるならサマリを読む（元データを読まない）
3. 満たせないなら元データから計算する
4. adjusted count による補正が要求されていれば適用する（§7.3）
5. いずれの経路でも、**結果に精度メタデータを付与する**（誤差境界、サマリ由来か否か、補正の有無）

**近似値を正確な値のように見せない。** これは §3.2 の型シャドーイングと同じ原則である。都合の悪い事実を隠すのではなく、扱える形で提示する。

### 7.6 探索的集約と定常集約の両輪

事前計算だけでは足りない。Tempo は 2 つの経路を持つ。

- **metrics-generator** — 低カーディナリティの定常 RED メトリクスを事前計算し、別ストアへ書き出す
- **TraceQL metrics** — 任意の属性による探索的な集約を、生の span から実行時に計算する

Trail も両方を要件とする。統計サマリ（§7.4）だけでは「任意の group-by による探索」に応えられず、生スキャンだけでは定常ダッシュボードが高価になる。

### 7.7 調査で判明した反証と修正

参照実装の調査により、本提案の初版から次を修正した。記録として残す。

| 初版の設計 | 反証 | 修正後 |
|---|---|---|
| Hot(q5) → Warm(q9-11) → Cold の圧縮階層 | Tempo は snappy 固定。parquet-go が BROTLI を持つのに使わず、`MaxCompactionLevel` で再書き込みを制限。SigNoz も `RECOMPRESS` 不使用 | 媒体コストを軸とした Hot / Cold の 2 階層。形式は変えない（§7.1） |
| Summary-only 階層で元データを削除 | SigNoz は raw / 5m / 30m を並置し細かい表を消さない。Tempo は別ストアへ書き出す | 解像度の並置。サマリ生成は削除条件にしない（§7.2） |
| 独自の `_sample_rate` 列 | OTel に adjusted count / threshold(`th`) / R-value(`rv`) が仕様化済み。Tempo は tracestate をそのまま保存し読み取り時にパース | OTel 語彙に統一。専用列を作らない（§7.3） |
| `COUNT(*)` をサンプリング率で補正 | 確率的丸めが必要（小数が下流を壊す）。MIN/MAX は補正禁止。SUM も補正対象。オプトインであるべき | 集約ごとの規則を明記（§7.3） |
| 型シャドーイングは `@i64` / `@str` | OTLP の `AnyValue` は 8 型 + 任意ネスト。Tempo は 4 型 + `ValueUnsupported` への JSON 退避 + `IsArray` フラグ | §3.2 を改訂。逃げ道を必須とする |
| 「マージ可能スケッチ」 | exponential histogram / native histogram / DDSketch という既存名がある | 既存語彙に統一（§7.4） |

なお、**型シャドーイングと読み取り時 coalesce という中核方式そのものは、実装に裏付けられた**。Tempo は `ValueInt` / `ValueDouble` / `ValueBool` / `Value` と型別カラムを持ち、読み取り時に case チェーンで解決する。SigNoz は `attributes_string` / `attributes_number` / `attributes_bool` の 3 マップを持ち、型が未知のキーには `multiIf` による coalesce を生成する。独自案ではなく業界の標準的な解法であった。

### 7.8 OTel における位置づけ

Alopex OTel は Trail のこの機構をそのまま使う。

- Tail sampling — 「エラーを含む trace は全 span 保持」は OTel の標準的な要求
- adjusted count — サンプリング済み trace から算出したエラー率を母集団の推定値として扱う
- 統計サマリ — RED メトリクスの一部は span からの派生集計であり、サマリから直接得られる
- 媒体階層 — trace の保持期間管理。イベントにダウンサンプリングは適用できないため、これが代替となる

---

## 8. クエリ層 — 内部言語と外部互換 API

Trail は Observe（ダッシュボード）を内蔵する。したがってクエリ層には**性格の異なる 2 つの面**がある。両者を混同すると、どちらも中途半端になる。

| 層 | 用途 | 選択基準 |
|---|---|---|
| **内部クエリ言語** | Observe が自分のストレージを読む | Trail の能力を最大限引き出せること |
| **外部互換 API** | Grafana など既存ツールから読まれる | 相手が期待する形に合わせること |

内部言語は Trail の設計に最適な形を選べる。外部 API には**こちらの都合を持ち込めない**。この非対称性が層を分ける理由である。

本章の設計は Grafana Tempo（TraceQL）、Grafana Loki（LogQL）、SigNoz の実装調査に基づく。

### 8.1 内部クエリ言語 — 集計特化 DSL

**方式: 集計特化 DSL とし、JOIN と集計を第一級で持つ。**

#### 「DSL は表現力が落ちる」は誤り

TraceQL は豊富な集計を持つ。`rate` / `count_over_time` / `min_over_time` / `max_over_time` / `avg_over_time` / `sum_over_time` / `quantile_over_time` / `histogram_over_time`、`by()` によるグルーピング、系列間の算術、`topk` / `bottomk`、結果への閾値フィルタ。

```
({status=error} | count_over_time()) / ({} | count_over_time())
{status=error} | rate() | topk(5) > 10
```

LogQL も同様に、範囲集約・`by`/`without` グルーピング・二項演算を持つ。

**表現力は言語形式ではなく設計で決まる。** SQL でなければ集計や結合が書けない、という前提は成り立たない。

#### 既存 DSL に無いもの — Signal 横断 JOIN

TraceQL の構造演算子（`>>` descendant、`>` child、`~` sibling）は JOIN 相当だが、**必ず 1 trace 内に閉じる**。trace をまたぐ結合も、Logs と Traces を跨ぐ結合も存在しない。LogQL の二項演算は PromQL 同様のラベルマッチングで、これも Signal 横断ではない。

SigNoz は IR に `QueryTypeJoin` を定義しているが、**有効化していない**（コード中に `// Not yet supported.` と明記）。

つまり **Signal 横断 JOIN は既存 OSS に完成形の先例がない**。Trail の内部言語はここを持つ。

#### 表現すべきもの

| 機能 | 必要な理由 |
|---|---|
| Signal 横断 JOIN | Trace ↔ Log ↔ Metric の相関。Observe の障害調査導線の基盤 |
| 集計（範囲集約・グルーピング・分位数） | ダッシュボードの主用途 |
| 系列間算術 | エラー率のような比率の表現 |
| 束縛指定 | `status@str` のような型シャドー列の明示（§3.2） |
| 構造演算子 | trace 内の親子・兄弟関係 |
| 統計サマリの透過利用 | §7.5 のプランナ判断 |

#### TraceQL を上位互換にはできない

内部言語を「TraceQL の拡張」として設計する案は成立しない。TraceQL の意味論は spanset パイプライン（trace 単位の集合代数）であり、SQL 的 JOIN とは別モデルである。リッチな JOIN 言語の部分集合として自然に埋め込めない。

**内部言語は独立に設計し、TraceQL / LogQL は互換レイヤとして別に持つ。**

### 8.2 外部互換 API — Grafana 互換を謳う

**Metrics / Traces / Logs のすべてで Grafana 互換を目指す。**

| Signal | 互換対象 | Grafana 側のデータソース |
|---|---|---|
| Metrics | Prometheus Query API | 組み込み Prometheus |
| Traces | Tempo HTTP API + TraceQL | Tempo |
| Logs | Loki HTTP API + LogQL | Loki |

#### 契約の実態 — 言語そのものが契約である

Grafana は**生の TraceQL / LogQL 文字列をそのまま転送する**。中間表現へ変換しない。

```
GET /api/search?q={ status=error }
GET /api/metrics/query_range?q={...} | rate() by(resource.service.name)
```

したがって「TraceQL 互換」を名乗るには、**彼らの文法を受理するパーサを実装するしかない**。プロトコル互換だけでは不十分である。

ただし救いが 2 つある。

1. **HTTP 面の契約は極めて薄い** — クエリパラメータ（Tempo は `q`、Loki は `query`）とレスポンス JSON の形だけ
2. **文法のサブセット実装で実用に足る** — Grafana 自身が「Builder mode は一部の複雑なクエリをサポートしない」と認めており、複雑なものは Code mode に落ちるだけである

#### 実装方式 — 共通論理プランへの desugar

各互換フロントエンドは、独自のパーサを持ち、**共通の型付き論理プランへ変換する**。

```
内部 DSL ──┐
TraceQL ───┼──→ 型付き論理プラン ──→ 実行
LogQL ─────┤     （フィルタ / projection / 集約 / 結合 / 系列後処理）
PromQL ────┘
```

共通化する境界は「言語 AST」ではなく**論理プラン**である。SigNoz の実装が示すのは、AST レベルの統合は破綻するということである（同社は PromQL を別エンジンへ委譲し、ClickHouse SQL は素通しし、結果レベルで合流させている。抽象化の漏れがコードに残る）。

### 8.3 参照実装から借用する設計要素

| 要素 | 出典 | 理由 |
|---|---|---|
| 集約の 3 モード（Raw / Sum / Final） | TraceQL | 分散実行のため「部分集約可能な段」と「単一箇所でしか計算できない段」を型で分離する。分散を視野に入れるなら初日から必要 |
| 名前付きクエリ DAG | SigNoz | JOIN・formula・サブクエリを統一的に表現でき、JSON で運べる |
| 構造式の葉を名前参照にする分離 | SigNoz | フィルタ構文と結合構文を独立に進化させられる |
| 複雑度の明示的上限 | SigNoz | 演算子数の上限を設け、実行不能なクエリを事前に弾く |
| pushdown 可能なフィルタの第一級化 | TraceQL | Tempo は「論理積のみのクエリは Parquet 層へ pushdown できて最速」と明記している。論理プランでこれを区別する |

### 8.4 段階

内部言語が正典であり、互換レイヤは後から足せる。したがって順序は次となる。

1. 内部 DSL（§10 の v0.3）
2. Prometheus Query API 互換（Metrics。Alopex OTel が先に必要とする）
3. TraceQL / LogQL 互換（Traces / Logs）
---

## 9. skulk からの流用マップ

| 対象 | 扱い | 備考 |
|---|---|---|
| データルートの単一ライタ排他 | **そのまま** | OS アドバイザリロック。ドメイン非依存 |
| Parquet 原子公開 | **そのまま** | tmp 作成 → fsync → rename → ディレクトリ fsync → Drop によるクリーンアップ |
| manifest 永続機構 | **拡張して流用** | 2 世代 rename + CRC32。`ActiveFile` に列サマリを追加 |
| 取り込みシーケンス採番 | **型パラメータ化して流用** | 行型への依存のみ |
| WAL フレーミング / リカバリ / チェックポイント | **流用** | エントリのエンコード / デコードのみ辞書方式へ差し替え |
| バッファの動的列 union | **中核を流用** | 型衝突を拒否 → シャドーへ、ソートを time-first へ |
| 取り込み層（限界値・部分成功・バックプレッシャ） | **そのまま流用** | sink 抽象が既にジェネリック |
| retention / パーティション | **流用** | パーティション幅の固定値を設定可能化 |
| データモデル | 新規 | 第 2 章 |
| ストア統合・compaction・リーダー | 新規 | 第 4・6 章 |
| プロトコルデコーダ | 新規 | OTLP logs / JSON Lines / syslog |

---

## 10. 段階計画

| 版 | 内容 |
|---|---|
| v0.1 | 追記パス最小構成 — Event モデル、WAL（辞書付き）、動的列 union バッファ、Parquet 公開、manifest（列サマリ付き）、単一ライタ排他、クラッシュ回復 |
| v0.2 | type-shadowing と読み取り時 coalesce、JSON Lines / OTLP logs デコーダ、retention |
| v0.3 | 述語プッシュダウンと列プロジェクション、manifest による枝刈り、**内部クエリ言語（集計特化 DSL）の最小版** — フィルタ、束縛指定、基本集計 |
| v0.4 | compaction（スキーマ指紋グルーピング、レベル上限）と sidecar 索引、**保持階層（Hot / Cold の媒体移動）**、全文検索の要否判断。**Python バインディング** |
| v0.5 | **統計サマリ（exponential histogram / HLL）と統計クエリ API**、**Head / Tail サンプリング**と adjusted count による補正 |
| v0.6 | **Signal 横断 JOIN**、系列間算術。**TraceQL / LogQL 互換レイヤ**（§8.2） |

保持階層は compaction の基盤の上に載るため v0.4 に置く。統計サマリは compaction 時に生成するため、compaction が動いてからになる。

サンプリングを最後に置くのは優先順位の反映である。**全件保持のまま容量を下げる手段（媒体階層）を先に用意し、それでも足りない場合の手段としてサンプリングを後から加える。**

クエリ層は 2 段に分かれる。v0.3 で内部 DSL の最小版（単一ストリームのフィルタと集計）を出し、v0.6 で Signal 横断 JOIN と互換レイヤを加える。**互換レイヤを後に置くのは、共通論理プランが固まってからでないと desugar 先が定まらないためである**（§8.2）。

### 10.1 Python バインディング（v0.4）

ログ分析は Python から扱われることが多いため、バインディングを提供する。方式は
alopex-py および Skulk と揃える。

- PyO3 + maturin、abi3 wheel を PyPI で配布する
- 取り込み（JSON Lines / dict）と、v0.3 のクエリを公開する
- 結果は Arrow 経由で pandas / Polars へ渡す。Trail は内部が Arrow のため変換は不要
- **late-bound schema は Python と相性が良い**。列集合が実行時に決まる点は
  DataFrame の扱いと一致し、静的な型宣言を要求しない
- 型シャドー列は、既定では coalesce した論理列として見せる。`status@str` の
  形で物理列を直接指定することもできる

述語プッシュダウンと列プロジェクションは skulk v0.3.0 では未実装であり、trail v0.3 で新規に設計・実装する必要がある。

---

## 11. 未確定事項

本提案は以下を意図的に未確定として残す。これらは合意形成の対象であり、決定なしに実装へ進むべきではない。

### 11.1 skulk とのコード共有形態（最優先）

共通クレートへ切り出すか、フォークして独立させるかが決まらないと着手できない。

- **共通クレート化**: skulk 側の改善が trail に自動で波及する。反面、両者の要求が割れた際にインタフェースが歪む
- **フォーク**: 独立して進化できる。反面、耐久性まわりの修正を二重に適用する必要が生じる

**推奨**: 当面はフォークとし、trail が v0.2 に到達した時点で共通化を再評価する。現段階では trail 側の要求がまだ固まっておらず、未成熟な要求で skulk のインタフェースを歪めるリスクがある。

### 11.2 skulk v0.3.1 との着手順序

skulk は v0.3.1 でインジェストのスループット改善を予定しており、その対象と trail の流用範囲が一部重なる。**trail の着手可否はモジュールごとに異なる。**

| trail が流用する対象 | skulk v0.3.1 / v0.4 のスコープ | 着手可否 |
|---|---|---|
| 単一ライタ排他 | 対象外 | **即着手可** |
| Parquet 原子公開 | 対象外 | **即着手可** |
| manifest 永続機構 | 対象外 | **即着手可** |
| シーケンス採番 | 対象外 | **即着手可** |
| バッファの動的列 union | 対象外 | **即着手可** |
| retention / パーティション | 対象外 | **即着手可** |
| WAL フレーミング / エンコード | **v0.3.1 の対象**（フレームエンコード、バッチ append） | v0.3.1 完了後 |
| 取り込み層の共通検証 | **v0.3.1 の対象**（行単位バリデーション） | v0.3.1 完了後 |
| Parquet リーダー | v0.4 で本格実装（v0.3.0 は最小 read のみ） | trail は新規実装のため影響なし |

skulk v0.4（クエリエンジン）は読み取り側の新規追加であり、trail が流用する書き込み側の耐久性機構には影響しない。

**したがって着手順序は以下とする。**

1. 第 8 章 v0.1 のうち、データモデル・manifest 拡張・バッファ改造・Parquet 公開・単一ライタ排他を先行実装する
2. WAL と取り込み層は skulk v0.3.1 のリリース後に取り込む。先行してフォークすると、v0.3.1 の改善を再適用する二重作業が生じる

### 11.3 スループット目標値

目標値が行表現の設計（入力バッファ借用ベースか owned か）を左右するため、先に決める必要がある。skulk の目標を踏襲するのか、ログ向けに別途設定するのかも含めて未定である。

### 11.4 内部クエリ言語の具体的な文法

方式（集計特化 DSL、Signal 横断 JOIN を持つ）は §8 で確定した。残るのは構文の細部である。演算子の記法、束縛指定の書き方（`status@str`）、JOIN の表現形式が未定である。

### 11.5 全文検索の要否

全文検索を要件に含める場合、inverted index は v0.4 の追加機能ではなく**設計全体の前提**となる。Parquet レイアウトと compaction の設計に遡って影響するため、早期の判断が必要である。

### 11.6 その他

- 時刻欠損時の補完ポリシーの詳細（取り込み時刻で十分か、ソース側の順序保証をどう扱うか）
- パーティション幅の既定値
- 型シャドー列の上限（同一属性名に何種類の型まで許容するか）
- 資源上限（1 イベントあたりの属性数、ネスト深さ、文字列長）

---

## 12. 参考

### 11.1 Alopex 内部

- [alopex-skulk 技術仕様](../specs/alopex-skulk-technical-spec.md)
- [alopex-skulk 要求仕様](../concepts/alopex-skulk-requirements.md)
- [alopex-skulk 設計仕様](../concepts/alopex-skulk-design-spec.md)
- [カラムナ DB 調査](../tech/columnar-db-research.md)
- [ファイルフォーマット比較](../tech/file-format-comparison.md)
- [TSDB ソース解析](../tech/tsdb-source-analysis.md)

### 11.2 参照実装

§7 の設計は次の実装を調査した上で定めた。反証の詳細は §7.7 を参照。

| 実装 | 参照した点 |
|---|---|
| [OpenTelemetry Proto](https://github.com/open-telemetry/opentelemetry-proto) | `AnyValue` の型定義。属性の型が揺れることの根拠 |
| [Grafana Tempo](https://github.com/grafana/tempo) | Parquet での型別カラムと読み取り時 coalesce、dedicated columns、compaction のグルーピング、adjusted count による補正、時間パーティション + trace ID クラスタリング |
| [SigNoz](https://github.com/SigNoz/signoz) | ClickHouse での型別マップ、未知キーの `multiIf` coalesce、型メタデータ表、`TO VOLUME` による媒体階層、解像度の並置、DDSketch のマージ |
| [OpenTelemetry Collector](https://github.com/open-telemetry/opentelemetry-collector) | tail sampling のバッファ設計、サンプリング前に集計するという方針 |
