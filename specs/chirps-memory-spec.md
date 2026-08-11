# Chirps ノードメモリ管理仕様書

> **対象バージョン**: Chirps v0.6.3以降
> **ステータス**: 部分達成（論理メモリ管理 API は v0.6.3 実装済み、長時間実測は別契約）
> **前提**: Chirps v0.6 Multi-Raft + TSO 完了後

## 概要

Chirps ノードのメモリ使用量を効率的に管理し、メッセージスループットと安定性を両立させる。
alopex-core のキャッシュ管理と連携した統合的なメモリ管理を実現。

---

## メッセージバッファ管理

### 現行実装との責務境界

```
crates/alopex-chirps/src/buffer/
├── message_buffer.rs  # MessageBuffer、profile 別 bytes、backpressure
├── priority_queue.rs  # Control > Durable > Ephemeral
└── backpressure.rs    # Warning → Limited → Reject

crates/chirps-transport-quic/src/
├── config.rs           # flow-control、stream、queue、QoS、接続上限
├── lib.rs              # QUIC endpoint、接続 map、idle eviction、health check
└── metrics.rs          # transport 単位の観測値
```

`crates/chirps/src/buffer/` は現行 workspace に存在しない。メッセージ buffer
の責務は `alopex-chirps` の buffer module、QUIC の window・stream・接続制御の
責務は `chirps-transport-quic` に分離されている。

### メッセージバッファ（`alopex-chirps/src/buffer/message_buffer.rs`）

- `MessageBuffer` 構造体
- Control / Durable / Ephemeral ごとの bytes 集計
- `max_buffer_bytes` と Warning → Limited → Reject
- profile-aware priority queue との接続

### 優先度キュー（`alopex-chirps/src/buffer/priority_queue.rs`）

- `PriorityQueue` 構造体
- Control > Durable > Ephemeral の処理順序
- profile ごとの受信順序制御

### バックプレッシャー制御（`alopex-chirps/src/buffer/backpressure.rs`）

- `BackpressureController` 構造体
- メモリ使用量閾値での Warning → Limited → Reject

---

## Raft ログキャッシュ

### 現行実装との責務境界

```
crates/chirps-raft-storage/src/wal_storage.rs
└── log_cache / log_order  # WAL 読み出し用の現行キャッシュ（LRU）

crates/alopex-chirps/src/raft/
└── # Raft facade、node、transport、metrics
```

`crates/chirps/src/raft/cache/` は存在しない。Raft log cache は storage
crate が WAL と同じ責務として保持し、Raft の公開 facade は
`alopex-chirps::raft` に置く。統合メモリ管理用の byte-bounded
`RaftLogCache` は `crates/alopex-chirps/src/memory.rs` にもある。

### WAL log cache（`chirps-raft-storage/src/wal_storage.rs`）

- `BTreeMap` の `log_cache` と `VecDeque` の `log_order`
- 最近の Raft ログエントリの index ベース検索
- 参照時 touch を含む LRU eviction
- 統合 manager 側は byte 上限と eviction bytes を管理

### スナップショットキャッシュ（将来候補）

- `SnapshotCache` 構造体、転送時の参照カウント、複数バージョンの保持は未実装

### ステートキャッシュ（将来候補）

- `StateCache` 構造体、read query cache、cache 一貫性保証は未実装

---

## 接続プール管理

### 現行実装との責務境界

```
crates/chirps-transport-quic/src/config.rs
crates/chirps-transport-quic/src/lib.rs
crates/chirps-transport-quic/src/metrics.rs
```

`crates/chirps/src/connection/` は存在しない。connection pool、QUIC
flow-control、connection admission、idle eviction、transport metrics は
`chirps-transport-quic` が担当する。Raft の接続利用側と facade は
`crates/alopex-chirps/src/raft/`、wire の型は `crates/chirps-wire/src/` に
分離されている。

### 接続 admission と idle eviction（`chirps-transport-quic/src/lib.rs`）

- 接続 map と peer ごとの接続再利用
- 接続数上限設定（`max_connections`）
- idle timeout 後の map 退避と close
- `health_check()` と定期 probe による stale connection の検出・close

### QUIC 接続管理（`chirps-transport-quic/src/lib.rs`）

- QUIC 接続管理（`chirps-transport-quic/src/lib.rs`）
- QUIC ストリームの多重化と stream 数上限
- flow-control window の設定反映
- 0-RTT 接続の再利用（未実装、v0.7へ繰り越し）
- `certificate_cache_stats()` を持つ証明書・trust anchor cache

### 接続メトリクス（`chirps-transport-quic/src/metrics.rs`）

- active connection / stream 数
- connection rejection / idle eviction counter
- retransmit buffer 使用量
- ノード全体の memory stats は `alopex-chirps/src/memory.rs` が担当

---

## alopex インメモリキャッシュ連携

### 統合キャッシュ管理

```rust
pub struct IntegratedCacheManager {
    /// Chirps メッセージバッファ
    pub message_buffer: MessageBuffer,
    /// Chirps Raft ログキャッシュ
    pub raft_cache: RaftLogCache,
    /// alopex-core との accounting/eviction adapter
    pub block_cache: Arc<BlockCacheHandle>,
    /// 総メモリ予算
    pub total_budget: usize,
    /// 動的割り当て比率
    pub allocation_ratio: AllocationRatio,
}
```

現行の配置は `crates/alopex-chirps/src/memory.rs` であり、
`MessageBuffer`、byte-bounded `RaftLogCache`、`BlockCacheHandle`、
`AllocationRatio`、`rebalance`、`emergency_evict`、`get_unified_metrics` を
同じ manager が調整する。alopex-core 0.3 は public `BlockCache` 型を公開しない
ため、block cache は現行では usage/eviction adapter である。

### メモリ割り当て戦略

```rust
pub struct AllocationRatio {
    /// メッセージバッファ比率（デフォルト: 30%）
    pub message_buffer: f32,
    /// Raft キャッシュ比率（デフォルト: 20%）
    pub raft_cache: f32,
    /// 接続プール比率（デフォルト: 10%）
    pub connection_pool: f32,
    /// alopex ブロックキャッシュ比率（デフォルト: 40%）
    pub block_cache: f32,
}
```

### 動的調整 API

```rust
impl IntegratedCacheManager {
    /// ワークロードに応じた動的再配分
    pub fn rebalance(&mut self, workload: WorkloadProfile);

    /// メモリプレッシャー時の緊急解放
    pub fn emergency_evict(&mut self, target_bytes: usize) -> usize;

    /// 統合メトリクス取得
    pub fn get_unified_metrics(&self) -> UnifiedMemoryMetrics;
}
```

---

## 設定・API

### メモリ設定（`MemoryConfig`）

```rust
pub struct MemoryConfig {
    /// 総メモリ予算（デフォルト: 256MB）
    pub total_budget: usize,
    /// メッセージバッファ上限（デフォルト: 64MB）
    pub message_buffer_limit: usize,
    /// Raft ログキャッシュ上限（デフォルト: 32MB）
    pub raft_log_cache_limit: usize,
    /// 接続プール上限（デフォルト: 16MB）
    pub connection_pool_limit: usize,
    /// バックプレッシャー閾値（デフォルト: 80%）
    pub backpressure_threshold: f32,
    /// 緊急 eviction 閾値（デフォルト: 95%）
    pub emergency_threshold: f32,
}
```

### ランタイム調整 API

```rust
impl MeshHandle {
    pub fn resize_memory_budget(&self, new_budget: usize) -> Result<(), MemoryError>;
    pub fn get_memory_stats(&self) -> MemoryStats;
    pub fn trigger_gc(&self) -> Result<(), MemoryError>;
}
```

---

## テスト・ベンチマーク

### 単体テスト

- MessageBuffer: バッファリング、バックプレッシャー
- RaftLogCache: LRU eviction、インデックス検索
- QUIC connection: 接続再利用、timeout、health check
- IntegratedCacheManager: 動的再配分、緊急解放

### ベンチマーク

- メッセージスループット vs メモリ使用量
- Raft ログ読み取りレイテンシ vs キャッシュサイズ
- 高負荷時のメモリ安定性
- alopex 連携時の統合性能

---

## 受け入れ基準

- メモリ使用量が設定上限内で安定
- バックプレッシャーが適切に機能
- alopex-core との連携でメモリ競合なし
- `get_memory_stats()` が統合メトリクスを返す
