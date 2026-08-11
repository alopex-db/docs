# Chirps ノードメモリ管理仕様書

> **対象バージョン**: Chirps v0.6.3以降
> **ステータス**: 未着手（v0.6.3の受入対象外）
> **前提**: Chirps v0.6 Multi-Raft + TSO 完了後

## 概要

Chirps ノードのメモリ使用量を効率的に管理し、メッセージスループットと安定性を両立させる。
alopex-core のキャッシュ管理と連携した統合的なメモリ管理を実現。

---

## メッセージバッファ管理

### 現行実装との責務境界

```
crates/chirps-transport-quic/src/
├── config.rs       # flow-control、stream、queue、QoS、接続上限
├── lib.rs          # QUIC endpoint、送信キュー、接続 map、idle eviction
└── metrics.rs      # transport 単位の観測値
```

`crates/chirps/src/buffer/` は現行 workspace に存在しない。メッセージ
buffer、priority queue、backpressure はこの仕様の論理コンポーネント名であり、
実装を追加する場合も上記 transport crate の責務境界をまたいで独立 crate に
複製しない。

### transport の送信キュー／backpressure（`chirps-transport-quic/src/lib.rs`）

- mpsc 送信キューと semaphore による受付制限
- プロファイル別 queue limit と再送 buffer
- flow-control window、stream 数、接続数の設定
- 満杯時の待機・拒否
- `MessageBuffer` という独立型、ノード全体の `max_buffer_bytes` は未実装

### transport の優先度制御（`chirps-transport-quic/src/config.rs`）

- message profile ごとの priority と queue limit
- Control / Durable / Ephemeral の送信制御
- `PriorityQueue` という独立型と比率配分は未実装

### backpressure の現状

- queue／semaphore 単位の送信受付制御は実装済み
- ノード全体のメモリ閾値に基づく警告 → 制限 → 拒否の統合制御は未実装

---

## Raft ログキャッシュ

### 現行実装との責務境界

```
crates/chirps-raft-storage/src/wal_storage.rs
└── log_cache / log_order  # WAL 読み出し用の現行キャッシュ（FIFO）

crates/alopex-chirps/src/raft/
└── # Raft facade、node、transport、metrics
```

`crates/chirps/src/raft/cache/` は存在しない。Raft log cache は storage
crate が WAL と同じ責務として保持し、Raft の公開 facade は
`alopex-chirps::raft` に置く。`snapshot_cache` と `state_cache`、LRU eviction
は現行実装にないため、この仕様の将来候補として扱う。

### WAL log cache（`chirps-raft-storage/src/wal_storage.rs`）

- `BTreeMap` の `log_cache` と `VecDeque` の `log_order`
- 最近の Raft ログエントリの index ベース検索
- WAL の読み出しを減らすための挿入順 FIFO
- `RaftLogCache` 型、`max_cached_entries`、LRU eviction は未実装

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
- health check は未実装

### QUIC 接続管理（`chirps-transport-quic/src/lib.rs`）

- QUIC 接続管理（`chirps-transport-quic/src/lib.rs`）
- QUIC ストリームの多重化と stream 数上限
- flow-control window の設定反映
- 0-RTT 接続の再利用（未実装）
- 証明書キャッシュ（未実装）

### 接続メトリクス（`chirps-transport-quic/src/metrics.rs`）

- active connection / stream 数
- connection rejection / idle eviction counter
- retransmit buffer 使用量
- ノード全体の memory stats は未実装

---

## alopex インメモリキャッシュ連携

### 統合キャッシュ管理

```rust
pub struct IntegratedCacheManager {
    /// Chirps メッセージバッファ
    pub message_buffer: MessageBuffer,
    /// Chirps Raft ログキャッシュ
    pub raft_cache: RaftLogCache,
    /// alopex-core ブロックキャッシュ（参照）
    pub block_cache: Arc<BlockCache>,
    /// 総メモリ予算
    pub total_budget: usize,
    /// 動的割り当て比率
    pub allocation_ratio: AllocationRatio,
}
```

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
    fn rebalance(&mut self, workload: WorkloadProfile);

    /// メモリプレッシャー時の緊急解放
    fn emergency_evict(&mut self, target_bytes: usize);

    /// 統合メトリクス取得
    fn get_unified_metrics(&self) -> UnifiedMemoryMetrics;
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
impl ChirpsNode {
    fn resize_memory_budget(&self, new_budget: usize) -> Result<()>;
    fn get_memory_stats(&self) -> MemoryStats;
    fn trigger_gc(&self) -> Result<()>;
}
```

---

## テスト・ベンチマーク

### 単体テスト

- MessageBuffer: バッファリング、バックプレッシャー
- RaftLogCache: LRU eviction、インデックス検索
- ConnectionPool: 接続再利用、タイムアウト
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
