# Chirps ノードメモリ管理仕様書

> **対象バージョン**: Chirps v0.6.1
> **ステータス**: 未着手
> **前提**: Chirps v0.6 Multi-Raft + TSO 完了後

## 概要

Chirps ノードのメモリ使用量を効率的に管理し、メッセージスループットと安定性を両立させる。
alopex-core のキャッシュ管理と連携した統合的なメモリ管理を実現。

---

## メッセージバッファ管理

### ファイル配置

```
crates/chirps/src/buffer/
├── mod.rs
├── message_buffer.rs
├── priority_queue.rs
└── backpressure.rs
```

### メッセージバッファ（`message_buffer.rs`）

- `MessageBuffer` 構造体
- 受信メッセージのバッファリング
- プロファイル別バッファサイズ（Control/Ephemeral/Durable）
- メモリ上限設定（`max_buffer_bytes`）
- バッファ満杯時のバックプレッシャー

### 優先度キュー（`priority_queue.rs`）

- `PriorityQueue` 構造体
- メッセージプロファイル別優先度
- Control > Durable > Ephemeral の処理順序
- 優先度別メモリ割り当て比率

### バックプレッシャー制御（`backpressure.rs`）

- `BackpressureController` 構造体
- 送信側への流量制御シグナル
- メモリ使用量閾値でのトリガー
- 段階的な制御（警告 → 制限 → 拒否）

---

## Raft ログキャッシュ

### ファイル配置

```
crates/chirps/src/raft/cache/
├── mod.rs
├── log_cache.rs
├── snapshot_cache.rs
└── state_cache.rs
```

### ログキャッシュ（`log_cache.rs`）

- `RaftLogCache` 構造体
- 最近の Raft ログエントリのキャッシュ
- インデックスベースの高速検索
- キャッシュサイズ設定（`max_cached_entries`）
- LRU ベースの eviction

### スナップショットキャッシュ（`snapshot_cache.rs`）

- `SnapshotCache` 構造体
- 最新スナップショットのメモリ保持
- スナップショット転送時の参照カウント
- 複数バージョンの部分キャッシュ

### ステートキャッシュ（`state_cache.rs`）

- `StateCache` 構造体
- コミット済みステートの高速アクセス
- 読み取り専用クエリのキャッシュヒット
- キャッシュ一貫性保証

---

## 接続プール管理

### ファイル配置

```
crates/chirps/src/connection/
├── mod.rs
├── pool.rs
├── quic_pool.rs
└── metrics.rs
```

### 接続プール（`pool.rs`）

- `ConnectionPool` 構造体
- ノード間接続の再利用
- 接続数上限設定（`max_connections_per_node`）
- アイドル接続のタイムアウト
- 接続ヘルスチェック

### QUIC 接続プール（`quic_pool.rs`）

- `QuicConnectionPool` 構造体
- QUIC ストリームの多重化
- ストリーム数の動的調整
- 0-RTT 接続の再利用
- 証明書キャッシュ

### 接続メトリクス（`metrics.rs`）

- `ConnectionMetrics` 構造体
- アクティブ接続数
- 接続確立/切断レート
- ストリーム使用統計
- メモリ使用量

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
