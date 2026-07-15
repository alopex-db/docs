# インメモリモード仕様書

> **対象バージョン**: alopex-core v0.1.1 / alopex-embedded v0.2.1
> **ステータス**: 未着手

## 概要

ディスク I/O を完全にバイパスし、純粋なメモリ上でデータベース操作を行うモード。
テスト、CI/CD、プロトタイピング、一時的なキャッシュ用途に最適。

## ユースケース

- **単体テスト**: ファイルシステム不要でテストが高速化（10x 以上）
- **CI/CD**: 一時ディレクトリ不要、並列テスト時のファイル競合回避
- **プロトタイピング**: 永続化なしの軽量な実験環境
- **キャッシュレイヤー**: 短命データの高速 read/write
- **Embedded 用途**: モバイル/WASM での一時ストレージ

---

## alopex-core インメモリストレージ

### ファイル配置

```
crates/alopex-core/src/storage/memory/
├── mod.rs
├── memory_store.rs
├── memory_wal.rs
├── memory_sst.rs
└── storage_factory.rs
```

### インメモリストレージエンジン（`memory_store.rs`）

- `MemoryStore` 構造体（`Storage` トレイト実装）
- `BTreeMap<Vec<u8>, Vec<u8>>` ベースの KV ストレージ
- Copy-on-Write セマンティクス（スナップショット分離用）
- スレッドセーフ実装（`RwLock` / `DashMap`）
- メモリ使用量トラッキング
- 上限設定とメモリプレッシャー通知

### インメモリ WAL（`memory_wal.rs`）

- `MemoryWal` 構造体（`Wal` トレイト実装）
- `Vec<WalEntry>` ベースのログ
- トランザクション境界の追跡
- オプショナルな WAL（無効化可能）
- WAL サイズ制限とトランケーション

### インメモリ SSTable（`memory_sst.rs`）

- `MemorySstManager` 構造体
- MemTable → インメモリ SSTable 変換
- Compaction のインメモリ実行
- SSTable メタデータ管理

### ストレージファクトリ（`storage_factory.rs`）

```rust
pub enum StorageMode {
    Disk { path: PathBuf },
    Memory { max_size: Option<usize> },
}
```

- `StorageFactory::create(config) -> Box<dyn Storage>`
- ランタイムでのモード選択

---

## alopex-embedded インメモリ API

### ファイル配置

```
crates/alopex-embedded/src/
├── options.rs  (拡張)
└── database.rs (拡張)
```

### Database オプション拡張（`options.rs`）

- `DatabaseOptions::in_memory() -> Self`
- `DatabaseOptions::with_memory_limit(bytes: usize) -> Self`
- `DatabaseOptions::memory_mode() -> bool`

### インメモリ Database 初期化

- `Database::open_in_memory() -> Result<Database>`
- `Database::open_in_memory_with_options(opts) -> Result<Database>`
- パス指定なしでの初期化サポート

### メモリ管理 API

- `Database::memory_usage() -> MemoryStats`
- `Database::set_memory_limit(bytes: usize) -> Result<()>`
- `Database::clear() -> Result<()>`（全データ削除、構造維持）

### スナップショット機能

- `Database::snapshot() -> Snapshot`（読み取り専用ビュー）
- `Database::clone_to_memory() -> Result<Database>`（ディスク→メモリ複製）
- `Database::persist_to_disk(path) -> Result<()>`（メモリ→ディスク書き出し）

---

## テスト・ベンチマーク

### 単体テスト

- インメモリ KV CRUD（put/get/delete）
- インメモリトランザクション（commit/rollback）
- スナップショット分離の動作確認
- メモリ上限到達時の挙動（エラー返却）
- 並行アクセス（マルチスレッド read/write）

### ベンチマーク

- ディスクモード vs インメモリモードの性能比較
- シーケンシャル write スループット
- ランダム read レイテンシ
- 並行 read/write 混在ワークロード

### デモプログラム

`examples/in-memory.rs`:
- インメモリ DB のオープンとクローズ
- KV 操作（put/get/delete）
- トランザクション操作
- メモリ使用量の確認
- persist_to_disk によるディスク書き出し

---

## 受け入れ基準

- インメモリモードで全 KV API が動作
- ディスクモードと API 互換
- メモリ使用量が上限内
- ディスクモード比で read/write が 10x 以上高速
- Vector API（upsert/search）がインメモリモードで動作
- `cargo run --example in-memory` で動作
