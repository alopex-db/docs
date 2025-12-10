# 分散DBファイルフォーマット比較レポート

対象: `reference/` にクローンされた4プロジェクト（CockroachDB, TiDB/TiKV, YugabyteDB, FoundationDB）と Alopex DB の技術仕様（`design/technical-spec.md` 1.3）。

## Alopex DB（基準）
- 単一拡張子 `.alopex`、ヘッダ64B + メタセクション + 複数データセクション + フッタ。
- データセクション: SSTable (KV), Vector Index, Columnar Segment（v0.2+）。全モードで同一バイナリ形式。
- 読み書き: Embedded/Single/Distributed。WASM はポリシー上 read-only（エンジン機能として書き込みを持たないだけで、ファイル自体に専用フラグは不要）。
- 整合性: セクションヘッダ checksum、フッタ checksum、Version 互換マトリクス。WAL+atomic rename で更新。
- Range 単位 `.alopex` を分散モードで採用。メジャー互換は後方のみ、前方非互換。

## CockroachDB（`reference/cockroach`）
- ストレージ: Pebble (RocksDB 系 LSM) で SSTables (`*.sst`), WAL (`*.log`), MANIFEST, CURRENT, OPTIONS, shared block cache。
- キー: MVCC タイムスタンプをサフィックスに付与したバイナリ key；ユーザ/システム/メタ空間を前置で分割。Range 分割 ~数十～数百 MiB。
- 値: Pebble のバイト列。SQL 行は KV カラムファミリーに分解。圧縮: snappy/zstd/none。
- 特徴: Range=Raft グループ。SST スナップショットを丸ごと送付。価値分離オプションで大型値を別領域。
- Alopex 比のメリット: 実戦投入の LSM チューニング、Range 分割と Raft 連携が成熟、価値分離で WA/IO 削減。
- デメリット: 統一単一ファイルではなく多数の SST/WAL/manifest。WASM 向けの read-only 単一スナップショット形態なし。Vector/Columnar を同一ファイルに共存させる設計は無く、バージョン明示の互換マトリクスも弱い。

## TiDB / TiKV（`reference/tidb`）
- ストレージ: TiKV が RocksDB（LSM）を採用。Column Families: `default`(value), `write`(MVCCメタ), `lock`。WAL は RocksDB WAL。Raft log も RocksDB か raft-engine に保存。
- キー: Region（約96MB目安）で分割、Raft 複製。ユーザキーに timestamp をサフィックスして MVCC；プレフィックスでテーブル/インデックス空間を分離。
- 値: バイト列。行フォーマットは TiDB 層でエンコード（RowKV / txnKV）。圧縮: snappy/zstd 等 RocksDB 依存。
- 特徴: Region スナップショットを SST として送付。Raft+RocksDB CF でログ/データを分離。
- Alopex 比のメリット: CF 分離でホットパス最適化、成熟した Region/Raft 管理。Raft log 切り出し (raft-engine) で compaction の影響を軽減。
- デメリット: ファイルは多数の SST/WAL/manifest に分散。Columnar/Vector を同一ファイルで扱う設計なし。read-only WASM 配布を想定していない。バージョン互換ポリシーは RocksDB に依存。

## YugabyteDB（`reference/yugabyte-db`）
- ストレージ: DocDB (RocksDB LSM) + Raft。各 Tablet（Range 相当）に RocksDB インスタンス。WAL, MANIFEST, SST がタブレット単位。
- キー: DocKey（ハッシュ/レンジ + col_id）に HybridTime をサフィックス（MVCC）。トランザクション用 Intent CF（未コミット）と Regular CF を分離。
- 値: フレックスなドキュメント/列データを DocDB エンコード。圧縮: RocksDB (snappy/zlib/zstd/none)。
- 特徴: SST スナップショットを Raft で配布。YSQL/YSQL カタログも DocDB 上の KV。
- Alopex 比のメリット: Intent CF による高頻度トランザクション最適化、タブレット単位の独立 LSM で水平分割が明快。
- デメリット: 単一統一ファイルではなく LSM ファイル集合。Vector/Columnar 同梱なし。WASM 配布や明示的なファイル互換マトリクスがない。

## FoundationDB（`reference/foundationdb`）
- ストレージ: デフォルト `ssd-2` エンジン（SQLite ベースB+Tree + WAL/pager）、新世代 `redwood-1`（ログ構造B-Tree）。ファイル: `*.fdb` データファイル + `*.log`。レプリカ/プロセスで複数ファイル。
- キー・値: 単純バイト列 KV。MVCC はサーバ側 TSO + バージョン管理で保持し、ディスク上は一世代だけ（古い世代はサーバがクリーン）。
- 特徴: トランザクションは層で提供、ストレージはシンプルB-Tree（LSMでない）。スナップショットはログとページで再構築。
- Alopex 比のメリット: B-Tree で読みレイテンシ安定、WAL + ページで書き増しを抑制。シンプルなファイル構成。
- デメリット: LSM ほどの書き込み最適化/圧縮柔軟性なし。Columnar/Vector 同梱なし。Range 分割はプロセス/クラスタで管理し、単一ファイル互換ポリシーは限定。

## まとめ比較（Alopex 視点）
- **単一ファイル性**: Alopex は `.alopex` に統合。4製品はいずれも多数 SST/WAL/manifest（FoundationDB は .fdb + log の少数だが用途分離）。配布・持ち運びは Alopex が簡便。
- **マルチ・データ構造共存**: Alopex は KV + Vector + Columnar を同一ファイルに格納可能。4製品は KV 専用（Columnar/Vector なし、別コンポーネント依存）。
- **WASM/Read-only スナップショット**: Alopex は read_only フラグで WASM 配布を想定。4製品はブラウザ配布の想定なし（SST スナップショットはあるが多数ファイル）。
- **バージョン互換/メタ**: Alopex はヘッダに semver, checksum 種別, schema version を埋め、互換マトリクスを定義。4製品は RocksDB/SQLite 互換に依存し、明示マトリクスは限定。
- **Range/Tablet 単位**: Cockroach/TiDB/Yugabyte は Range/Region/Tablet の SST 集合で細粒度管理。Alopex は Range 単位 `.alopex` で同等の分割を単一ファイルで実現。
- **耐障害性更新**: Alopex は WAL + atomic rename。Cockroach/TiDB/Yugabyte は LSM+MANIFEST で同等、FoundationDB は WAL+paging。差はなし。
- **性能チューニング成熟度**: 既存4製品は実運用で熟成した compaction/pacing/cf 分割/intent/価値分離がある。Alopex は設計段階であり、実装・チューニングが課題。

## Alopex への含意
- 強み: 配布容易（WASM 含む）、複合データ構造を単一ファイルで扱える拡張性、明示的互換ポリシー。
- リスク/課題: LSM 周辺の実戦チューニング（write amp, level sizing, ingest/snapshot bulk load, value separation）やトランザクション・Raft とファイル形式の整合実装が未成熟。多数ファイル運用の利点（並列I/O、部分回収）を単一ファイルでどう吸収するか検討が必要。

## Alopex 単一最終ファイル方針と一時ファイル許容の整理
- ゴール: 「最終コミット済みデータ」は Range 単位の `.alopex` に収斂させ、配布・バックアップ・WASM 配送を容易にする。一方、動作中の WAL や compaction/rename 用一時ファイルの存在は許容する。
- 最低限の一時ファイルセット:
  - `.wal`（追記型、fsync された durability log）
  - `.alopex.tmp`（compaction/flush の書き出し先）
  - ロールフォワード/再起動で不要になった `.wal` は truncate/削除して最終状態を単一 `.alopex` に回収する。
- アトミック更新手順（提案）:
  1) WAL に追記 → MemTable 反映  
  2) flush/compaction で `.alopex.tmp` に新セクションを書き出し、footer まで fsync  
  3) `rename(.alopex.tmp, range_X.alopex)` でアトミック置換  
  4) WAL を truncate（または世代ローテーション）  
  → 稼働中は WAL + 現行 `.alopex` の2本立て、安定後は `.alopex` 単体で完全状態。
- ログ/メタ分離の考慮:
  - MANIFEST 相当を `.alopex` footer に包含する設計のため、別ファイルの MANIFEST は不要。WAL 再生後に footer を更新し、rename で合成。
  - 大型値分離（value separation）を導入する場合は `.alopex` 内のセクションとして格納し、外部 blob ファイルを増やさない方針を維持するか要検討（単一ファイル性とトレードオフ）。
- 並列 I/O / 部分回収への対処:
- 単一ファイルでもセクション単位で mmap/範囲読みを行い、プリフェッチとパイプライン I/O を活用する。
- Compaction を Range 内部でセクション単位マージできる API を設け、全体 rewrite ではなく増分セクション置換を可能にすることで書き込み増幅を抑制。
- バックアップ/スナップショット:
  - 安定状態の `.alopex` をそのままスナップショットとして配布。稼働中は「`.alopex` + fsync 済み WAL」で point-in-time を再現可能にする。
  - WASM 配布はポリシーで read-only とし、ファイル形式は他モードと同一（専用フラグ無し）。一時ファイルは配布に含めない運用ガイドを明示する。

## ディスク書き込み戦略の比較
- **Alopex (設計)**: WAL 先行書き込み → MemTable → flush/compaction を `.alopex.tmp` へ書き、fsync 後に rename。Range 単位で完結し、最終は単一 `.alopex`。compaction はセクション置換型を検討し、書き込み増幅を抑制。

- **CockroachDB (Pebble)**:
  - WAL: Pebble の append-only ログ。fsync バッチング。log recycle。
  - MemTable: skiplist。L0 サイズ/ファイル数を監視して compaction ペーシング。`compaction_debt` で backpressure。
  - Flush: L0 SST を生成、MANIFEST に記録。`Options` でターゲットファイルサイズ/level を制御。
  - Compaction: Levelled。L0→LBase 優先、`compaction_picker` で圧縮。`shared block cache` で読みコストを抑制。
  - Write amp 対策: pacing + bloom + target file size。value separation (optional) で大値を別領域にして compaction コストを低減。

- **TiDB / TiKV (RocksDB)**:
  - WAL: RocksDB WAL。Raft log は raft-engine で分離運用可（ログとデータ compaction を分離）。
  - MemTable: skiplist。CF 分離 (`default`/`write`/`lock`) によりホットなメタ/ロックを軽量化。
  - Flush/Compaction: CF ごとの LSM。`write` CF は小さく頻繁に flush、`default` は大きく保持。L0 トリガで backpressure。
  - Ingest: `ingest_external_file`（SST ingest）で bulk 書き込みを最適化。
  - Raft スナップショット: Region 単位で SST を送付し、適用時に RocksDB ingest。

- **YugabyteDB (DocDB on RocksDB)**:
  - WAL: Tablet ごとに WAL。Raft log は同居か別ストア設定。Intent CF と Regular CF を分離し、未コミット書き込みを isolation。
  - Flush: Intent CF は短周期で flush し、コミット/abort で GC。Regular CF は通常 LSM。
  - Compaction: RocksDB leveled。`DocDBCompactionFilter` で過去の intent/obsolete を削除。HybridTime に基づくガベージ。
  - Bulk load: `BulkLoad`/`SSTableBuilder` による直接 SST 作成。Raft スナップショットは SST セットを転送。

- **FoundationDB**:
  - `ssd-2` (SQLite pager): Write-ahead logging + B+Tree ページ書き換え。commit 時に WAL fsync、checkpoint でページを書き戻し。ページサイズ固定でランダムライトを抑制。
  - `redwood-1`: ログ構造 B-Tree（可変長キー）。update は append、古いページは GC。write amp を下げるためにデルタ合成を遅延。
  - 一貫性: commit version を介した MVCC。ディスク上は最新世代のみ保持し、古い世代はクラスタがクリーンアップ。
  - 障害復旧: WAL + recovery ロジックで page map を再構成。レプリカで多重化。

### Alopex への示唆（書き込み戦略）
- バックプレッシャ: Pebble/TiKV 同様に L0 サイズ/セクション数ベースで write throttle を導入し、compaction debt を計測。
- CF/intent 分離の代替: `.alopex` 内セクション分離（例: intent/lock/regular）で compaction コストを局所化する設計を検討。
- External ingest: Bulk ロード用に外部 SST 相当を直接セクションとして取り込む API を持つとスナップショット/クローンが容易。
- ログ分離: raft-log を WAL と分離するか、`.alopex` に含めず別ファイルにするポリシーを明確化（単一ファイル性と運用性のバランス）。

### シーケンス図（書き込みとファイル更新の流れ）

```
        Alopex (単一ファイル指向)                       LSM系 (Cockroach/TiKV/YB: 複数SST)
┌──────────────────────────────┐              ┌─────────────────────────────────────┐
│  write(key,value)            │              │  write(key,value)                   │
└─────────────┬────────────────┘              └──────────────┬─────────────────────┘
              │ WAL append (fsync)                           │ WAL append (fsync)
              ▼                                              ▼
        MemTable insert                                MemTable insert
              │                                              │
    flush trigger? (size/time)                      flush trigger? (size/time)
              │                                              │
              ▼                                              ▼
   build `.alopex.tmp` セクション                  build L0 SST file(s)
              │                                              │
          fsync(tmp)                                   fsync(SST)
              │                                              │
   atomic rename → `range.alopex`                  MANIFEST書き込み + 現行SSTセット更新
              │                                              │
        truncate WAL                                   optional: ingest to Raft snapshot
              │                                              │
   最終状態は単一 `.alopex`                         L0→LBase compaction (複数SST再生成)
              │                                              │
        読み/配布/WASM                           読み/配布は複数SST+MANIFEST+WAL
```

ポイント:
- Alopex は flush/compaction で常に「tmp→rename」で単一ファイルに収束。配布・WASM 用スナップショットは `.alopex` 単体をコピーすればよい。
- LSM 系は L0/L1… の複数 SST が並存し、MANIFEST でメタを持つ。スナップショットや配布は SST セットをバンドルする必要がある。
