# alopex-core バッファプール・メモリ管理仕様書

> **対象バージョン**: alopex-core v0.1.1 / Alopex DB v0.3.1
> **ステータス**: 未着手
> **前提**: v0.3 で SQL Frontend が追加された後、KVS 層のメモリ効率を最適化する

## 概要

alopex-core のディスク I/O を最小化し、ホットデータをメモリに保持することで読み取り性能を向上させる。
上位層（SQL / embedded）と連携した階層キャッシュを構築。

alopex-sql の v0.2.2 キャッシュ管理と連携し、統合的なメモリ管理を実現。

---

## ブロックキャッシュ

### ファイル配置

```
crates/alopex-core/src/cache/
├── mod.rs
├── block_cache.rs
├── memtable_pool.rs
└── page_cache.rs
```

### ブロックキャッシュ（`block_cache.rs`）

- `BlockCache` 構造体（LRU ベース）
- SSTable データブロックのキャッシュ
- インデックスブロックの優先キャッシュ（eviction 抵抗）
- フィルタブロック（Bloom filter）のキャッシュ

#### API

```rust
impl BlockCache {
    fn get_block(file_id: FileId, block_offset: u64) -> Option<Arc<Block>>;
    fn put_block(file_id: FileId, block_offset: u64, block: Block);
    fn invalidate_file(file_id: FileId);  // SSTable 削除時
}
```

- キャッシュサイズ上限設定（`max_cache_bytes`）
- 共有参照（`Arc<Block>`）によるゼロコピー読み取り

### メモリテーブルキャッシュ（`memtable_pool.rs`）

- `MemTablePool` 構造体
- Active MemTable のメモリ予算管理
- Immutable MemTable の flush 優先度
- メモリプレッシャー時の強制 flush トリガー
- MemTable サイズ閾値設定（`memtable_size_threshold`）

### ページキャッシュ統合（`page_cache.rs`）

- OS ページキャッシュとの連携戦略
- Direct I/O オプション（OS キャッシュバイパス）
- mmap オプション（大規模ファイル向け）
- アドバイザリプリフェッチ（`fadvise`/`madvise`）

---

## I/O メトリクス

### ファイル配置

```
crates/alopex-core/src/metrics/
├── mod.rs
├── storage_metrics.rs
└── memory_metrics.rs
```

### ストレージメトリクス（`storage_metrics.rs`）

- `StorageMetrics` 構造体
- ブロック読み取り/書き込みカウント
- キャッシュヒット/ミス率
- Compaction I/O 統計
- WAL 書き込み統計
- レイテンシヒストグラム（read/write/sync）

### メモリメトリクス（`memory_metrics.rs`）

- `MemoryMetrics` 構造体
- MemTable 使用量
- BlockCache 使用量
- 総メモリ使用量
- eviction 回数/バイト数

---

## 設定・API

### キャッシュ設定（`CacheConfig`）

```rust
pub struct CacheConfig {
    /// ブロックキャッシュサイズ（デフォルト: 64MB）
    pub block_cache_size: usize,
    /// MemTable メモリ予算（デフォルト: 64MB）
    pub memtable_budget: usize,
    /// インデックスブロックをキャッシュするか（デフォルト: true）
    pub cache_index_blocks: bool,
    /// フィルタブロックをキャッシュするか（デフォルト: true）
    pub cache_filter_blocks: bool,
    /// Direct I/O を使用するか（デフォルト: false）
    pub direct_io: bool,
}
```

### ランタイム調整 API

```rust
impl Database {
    fn resize_block_cache(&self, new_size: usize) -> Result<()>;
    fn flush_cache(&self) -> Result<()>;
    fn get_cache_stats(&self) -> CacheStats;
}
```

---

## テスト・ベンチマーク

### 単体テスト

- BlockCache: LRU eviction、サイズ制限
- MemTablePool: flush トリガー
- メトリクス: 正確なカウント

### ベンチマーク

- キャッシュヒット率 vs 読み取りスループット
- 様々なキャッシュサイズでの性能曲線
- メモリプレッシャー下での書き込み性能

---

## 受け入れ基準

- ブロックキャッシュで SSTable 読み取りが 10x 高速化（ホットデータ）
- メモリ使用量が設定上限内
- `get_metrics()` が `cache_hit_total`, `cache_size_bytes` を返す
