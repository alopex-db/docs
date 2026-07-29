# alopex-trail 構想提案 — スキーマ後定義のログ/イベントストア

**バージョン**: 1.0
**作成日**: 2026-07-29
**ステータス**: Proposal（合意形成用。実装着手の承認を得たものではない）

---

## 1. 概要

### 1.1 何を作るか

`alopex-trail` は、**スキーマを事前に定義せずに取り込める**追記専用のログ/イベントストアである。到着したイベントの属性集合から列を動的に構築し、Parquet に列指向で永続する。

alopex-skulk（時系列データベース、v0.3.0 リリース済み）が「スキーマ既定の時系列」を担うのに対し、trail は「スキーマ未定の半構造化イベント」を担う。両者は追記専用・列指向・Parquet 永続という同じストレージ基盤を共有し、上位のデータモデルだけが分かれる。

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

## 3. スキーマ後定義の方式

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

この方式の要点は、**取り込みが決して止まらない**ことである。型の不整合は書き込み時のエラーではなく、読み取り時の解決対象として扱う。これが「スキーマ後定義」の実質的な意味である。

なお coalesce の際に同一行で複数のシャドー列が非 null になることはない（1 イベントの 1 属性は 1 つの型にしか振り分けられないため）。

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

---

## 7. skulk からの流用マップ

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

## 8. 段階計画

| 版 | 内容 |
|---|---|
| v0.1 | 追記パス最小構成 — Event モデル、WAL（辞書付き）、動的列 union バッファ、Parquet 公開、manifest（列サマリ付き）、単一ライタ排他、クラッシュ回復 |
| v0.2 | type-shadowing と読み取り時 coalesce、JSON Lines / OTLP logs デコーダ、retention |
| v0.3 | 述語プッシュダウンと列プロジェクション、manifest による枝刈り |
| v0.4 | compaction と sidecar 索引、全文検索の要否判断 |

述語プッシュダウンと列プロジェクションは skulk v0.3.0 では未実装であり、trail v0.3 で新規に設計・実装する必要がある。

---

## 9. 未確定事項

本提案は以下を意図的に未確定として残す。これらは合意形成の対象であり、決定なしに実装へ進むべきではない。

### 9.1 skulk とのコード共有形態（最優先）

共通クレートへ切り出すか、フォークして独立させるかが決まらないと着手できない。

- **共通クレート化**: skulk 側の改善が trail に自動で波及する。反面、両者の要求が割れた際にインタフェースが歪む
- **フォーク**: 独立して進化できる。反面、耐久性まわりの修正を二重に適用する必要が生じる

**推奨**: 当面はフォークとし、trail が v0.2 に到達した時点で共通化を再評価する。現段階では trail 側の要求がまだ固まっておらず、未成熟な要求で skulk のインタフェースを歪めるリスクがある。

### 9.2 skulk v0.3.1 との着手順序

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

### 9.3 スループット目標値

目標値が行表現の設計（入力バッファ借用ベースか owned か）を左右するため、先に決める必要がある。skulk の目標を踏襲するのか、ログ向けに別途設定するのかも含めて未定である。

### 9.4 クエリインタフェース

SQL（alopex の Nim パーサー経由）とするか、ログ検索に特化した専用 DSL とするかが未定である。この選択は第 8 章の v0.3 の設計に直接影響する。

### 9.5 全文検索の要否

全文検索を要件に含める場合、inverted index は v0.4 の追加機能ではなく**設計全体の前提**となる。Parquet レイアウトと compaction の設計に遡って影響するため、早期の判断が必要である。

### 9.6 その他

- 時刻欠損時の補完ポリシーの詳細（取り込み時刻で十分か、ソース側の順序保証をどう扱うか）
- パーティション幅の既定値
- 型シャドー列の上限（同一属性名に何種類の型まで許容するか）
- 資源上限（1 イベントあたりの属性数、ネスト深さ、文字列長）

---

## 10. 参考

- [alopex-skulk 技術仕様](../specs/alopex-skulk-technical-spec.md)
- [alopex-skulk 要求仕様](../concepts/alopex-skulk-requirements.md)
- [alopex-skulk 設計仕様](../concepts/alopex-skulk-design-spec.md)
- [カラムナ DB 調査](../tech/columnar-db-research.md)
- [ファイルフォーマット比較](../tech/file-format-comparison.md)
- [TSDB ソース解析](../tech/tsdb-source-analysis.md)
