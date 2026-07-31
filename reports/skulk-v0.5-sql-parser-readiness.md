# Skulk v0.5 SQL パーサー準備状況

**調査日**: 2026-07-31

**対象**: Skulk v0.5 Downsampling / Continuous Query

**現在の結論**: 通常の集約 `SELECT` は実装済みだが、Continuous
Aggregate の定義構文とライフサイクル制御契約は未実装である。Skulk v0.5
の実装開始前に Alopex 側で Nim パーサー契約 `0.3.0` を実装し、予定された
Alopex v0.8.3 として先行リリースする。v0.8.2 は不具合対応専用とし、
parser 機能追加を混在させない。

## 決定事項

1. v0.5 の Continuous Query 定義は、既存要求を引き継いで
   `CREATE CONTINUOUS AGGREGATE ... AS SELECT ... WITH (...)` を公開制御面とする。
2. tokenizer / parser / wire AST は Alopex の Nim 実装が所有する。Skulk
   の Rust は AST mapping、型・意味検証、計画、実行だけを担当し、構文解析を
   重複実装しない。
3. 新しい statement variant を含む wire contract は `0.3.0` とする。
   Alopex v0.8.3 のリリース完了と成果物検証を、Skulk v0.5 の
   parser-dependent task の開始条件にする。
4. `CREATE/ALTER TIMESERIES TABLE` は現状未実装だが、v0.5 の必須 parser
   scope には含めない。保持期間は Continuous Aggregate の `WITH
   (retention=...)` と既存の設定 API で扱う。将来この DDL を昇格する場合は、
   別の要求・契約変更として扱う。
5. WASM は v1.0 以降の再評価対象であり、v0.5 の parser/release gate
   には含めない。

## 実装済み範囲

| 能力 | Alopex Nim parser | Skulk v0.4 | v0.5 判定 |
|---|---|---|---|
| `TIME_BUCKET(INTERVAL '1 hour', time)` | 受理 | 型検証・計画・実行済み | 利用可能 |
| `TIME_BUCKET('1 hour', time)` | 受理 | duration mapping 済み | 利用可能 |
| `AVG` / `SUM` / `MIN` / `MAX` / `COUNT` | 汎用関数 AST として受理 | 集約実行済み | 利用可能 |
| `FIRST` / `LAST` / `RATE` / `DELTA` / `DERIVATIVE` | 受理 | 型検証・計画・実行済み | 利用可能 |
| raw / rollup 解像度選択 | 構文非依存 | catalog、coverage、alignment、raw fallback 実装済み | v0.5 は rollup 登録を追加 |
| 単一 measurement の `SELECT` | 受理 | SQL-TS 意味層へ mapping 済み | CQ の query body に再利用 |

したがって、Downsampler が型付き設定から通常の SQL-TS `SELECT` を組み立てて
実行するだけなら、既存 parser contract `0.2.0` で構文上は足りる。ただし、
公開要求にある Continuous Query の定義・永続化・再読込まで満たすには、次の
不足を解消する必要がある。

## 不足と責任分界

| 不足 | 現状の証拠 | 所有者 | v0.5 での処置 |
|---|---|---|---|
| `CONTINUOUS` / `AGGREGATE` の文脈認識 | lexer は両方を identifier として返す | Alopex / Nim | `CREATE` 直後だけ contextual keyword として認識 |
| `CREATE CONTINUOUS AGGREGATE` grammar | `CREATE` は `TABLE` / `INDEX` のみ | Alopex / Nim | canonical grammar を実装 |
| Continuous Aggregate AST | Nim AST と MessagePack wire に variant がない | Alopex / Nim | source span 付き variant を追加 |
| host AST compatibility | `alopex-sql::StatementKind` に variant がない | Alopex / Rust bridge | decode と明示的 unsupported 経路を追加 |
| Skulk definition mapping | SQL-TS mapper は単一 `Select` 専用 | Skulk / Rust | query path と分離した control-plane mapper を追加 |
| 定義の検証・永続化 | name、source、destination、interval、option の契約がない | Skulk / Rust | 型付き definition と catalog を追加 |
| scheduler / watermark / late data | v0.4 には実体がない | Skulk / Rust | 再計算範囲と冪等 commit を実装 |
| rollup の物理登録 | v0.4 catalog は raw のみ | Skulk / Rust | coverage/capability 付き rollup を登録 |
| `p50` / `p99` | 設計にはあるが一般 percentile 集約実行がない | Skulk / Rust | typed percentile 集約と回帰テストを追加 |
| target 別 parser 成果物 | Skulk source tree の vendor は Linux x86_64 のみ | Alopex + Skulk release | 対応 target matrix を spec で固定して consumer test |

`HISTOGRAM_QUANTILE` は classic histogram bucket 用であり、数値列の
`p50` / `p99` の代替にはならない。これは parser の不足ではなく Skulk
の型・集約実行層の不足である。

`CONTINUOUS` と `AGGREGATE` を無条件の予約語にすると、同名の既存
identifier を壊す可能性がある。まず `CREATE` の文脈内だけで
case-insensitive に認識し、既存 `SELECT aggregate FROM ...` が回帰しない
ことを fixture で固定する。

## 再現結果

Alopex v0.8.1 の Nim parser を Nim 2.2 で直接実行した。

```text
sql_ts_interval: OK nkSelect
sql_ts_string: OK nkSelect
documented_continuous_aggregate:
  ERROR expected TABLE or INDEX after CREATE (got CONTINUOUS)
conventional_continuous_aggregate:
  ERROR expected TABLE or INDEX after CREATE (got CONTINUOUS)
create_timeseries_table:
  ERROR expected TABLE or INDEX after CREATE (got TIMESERIES)
alter_timeseries_retention:
  ERROR expected SQL statement ... (got ALTER)
```

確認箇所:

- `alopex/crates/alopex-sql/nim-sql-parser/src/lexer.nim`
- `alopex/crates/alopex-sql/nim-sql-parser/src/parser.nim`
- `alopex/crates/alopex-sql/nim-sql-parser/src/ast.nim`
- `alopex/crates/alopex-sql/nim-sql-parser/src/alopex_sql_parser.nim`
- `alopex/crates/alopex-sql/src/ast/`
- `skulk/crates/skulk/src/query/sqlts/`
- `skulk/crates/skulk/src/query/plan/resolution.rs`
- `skulk/crates/skulk/src/query/exec/aggregate.rs`

## Canonical grammar の固定対象

v0.5 spec の Requirements 承認前に、少なくとも次の形を golden fixture
として固定する。

```sql
CREATE CONTINUOUS AGGREGATE cpu_hourly
AS
SELECT
  TIME_BUCKET(INTERVAL '1 hour', time) AS time,
  host,
  AVG(usage_user) AS usage_user_avg
FROM cpu_metrics
GROUP BY TIME_BUCKET(INTERVAL '1 hour', time), host
WITH (
  retention = '30d',
  refresh_interval = '1h'
);
```

固定対象は、句の順序、識別子・option の大小文字規則、duration の許容形式、
未知 option の拒否、重複 option の拒否、span/error 位置、複数 statement
の扱いである。query body は既存 `Select` AST を再利用し、同じ式 AST を
別実装しない。

## リリース順序

```text
Skulk v0.5 Requirements
  └─ grammar / AST / target matrix を固定
      └─ Alopex Nim parser contract 0.3.0
          └─ Alopex v0.8.3 release
              └─ Skulk consumer contract tests
                  └─ Skulk v0.5 scheduler / rollup implementation
                      └─ Skulk v0.5 release
```

### Gate A: Alopex v0.8.3

- Nim contextual keyword/parser/AST、MessagePack contract、host Rust AST を同じ PR で更新
- 正常系・異常系・span・wire golden fixture を Nim と Rust の両側で検証
- 既存 SQL/PromQL contract の回帰を検証
- Ubuntu x86_64 と Windows x86_64 で Nim native test と全 release gate を完走
- tag、crates/Python、GitHub Release、parser library を含む全対象の公開完了

Alopex の parser PR は main に未リリースのまま滞留させない。main への
merge はリリース列への投入であり、上記公開が完了して初めて Gate A 完了とする。

### Gate B: Skulk consumer

- contract `0.3.0` を exact pin し、異なる版を起動時に拒否
- Alopex release asset の checksum を固定
- Ubuntu/Windows の対応 target で DDL fixture を parse し、同じ typed
  definition へ mapping されることを検証
- `--no-default-features` の pure-Rust core に parser dependency が混入しない
- parser library を含む配布サイズと、core-only サイズを別々に上限判定

### Gate C: v0.5 engine

- 同一 window の再実行が重複行を作らない
- crash が data と watermark の片方だけを可視化しない
- late data の再計算範囲が bounded である
- raw retention は必要な rollup commit の完了前に source を削除しない
- p50/p99 を含む全 aggregate の型・null・空 window を検証
- v0.4 の resolution selector が新しい rollup を安全に選び、条件不一致時は
  raw へ戻る

## v0.5 spec 開始条件

次を満たすまでは `.spec-workflow/specs/skulk-v0-5/` の実装 task を開始しない。

- 本文の canonical grammar と scope を Requirements で承認
- Alopex v0.8.3 の version、contract `0.3.0`、release asset matrix を確定
- percentile の入力モデルと rollup schema を Design で確定
- data/watermark の原子性、再計算、削除順序を Design で確定
- Alopex release と Skulk consumer gate を Tasks の先頭に配置

関連ロードマップ:

- [Skulk マイルストーン](../roadmap/skulk-milestones.md)
- [Alopex / Chirps マイルストーン](../roadmap/alopex-milestones.md)
- [Alopex Skulk 要求仕様](../concepts/alopex-skulk-requirements.md)
