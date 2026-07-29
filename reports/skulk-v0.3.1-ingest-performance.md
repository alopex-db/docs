# Skulk v0.3.1 取り込みスループット改善レポート

**バージョン**: 1.0
**測定日**: 2026-07-29
**対象**: alopex-skulk v0.3.1（オンディスクフォーマット v0.3 互換のパッチリリース）
**ステータス**: Final

> 総合結果: **耐久込み取り込みスループットを Line Protocol 約4.9倍・Remote Write 約3.9倍に改善**（フォーマット変更なし・耐障害性テスト全維持）

## 1. 結果サマリ

固定ワークロード（10,000点 / 100 series / 1 writer / 1 batch / 実ファイルシステム / Ack前 fsync 1回）での耐久込みエンドツーエンド実測:

| 経路 | v0.3.0 | v0.3.1（完全静穏窓・3ラン中央値） | 改善 | 内部ゲート |
|---|---|---|---|---|
| Line Protocol → WAL ACK | 34.1–37.8 K pts/s | **180.1 K pts/s**（150.9 / 180.1 / 189.7） | **約4.9倍** | ≥150K: **PASS**（3/3ラン超過） |
| Remote Write v1 → WAL ACK | 34.1–39.8 K samples/s | **144.4 K samples/s**（139.2 / 144.4 / 144.6） | **約3.9倍** | ≥100K（公開目標）: **PASS**（全ラン下限CIでも超過） |
| Line Protocol decode 単体 | 118.9–147.4 K pts/s | 225.2–324.7 K pts/s | 約2倍 | — |
| Remote Write decode 単体 | 201.5–217.9 K samples/s | 595.7–743.3 K samples/s | 約3倍 | — |

耐障害性は**退行ゼロ**: クラッシュ回復不変条件 I1〜I6・RTO<5分・RPO<1分を含む全119テストが green のまま（prometheus wlog / head_bench、influxdb3_wal のテストパターンに倣ったロード/ストレステスト6種を新規追加）。

## 2. 変更内容（すべてフォーマット不変）

v0.3.0 の書き込みホットパスに存在した行あたりのオーバーヘッド（深いclone約4回・write syscall 3回・WAL全エントリのメモリ常駐・出力が破棄されるArrow構築・検証の多重走査）を、参考実装の構造調査に基づいて除去した:

1. **WAL バッチ追記の借用化**: 行cloneゼロ（`&WideRow`のみ受理）、フレームを再利用バッファへ連結しバッチあたり定数回の書き込み。checkpoint は同期済みログのストリーム走査で書き直し（原子性 = temp+fsync+rename+dirsync は不変）
2. **単一走査の行受理**（InfluxDB 3 の WriteValidator 構造に準拠）: 資源上限・名前検証・型/役割整合・バイト見積を1回の走査に統合し、型状態パターン（`BatchQualification`）でストア層の再検証を排除
3. **取り込み時 Arrow 構築の廃止**: flush が pending 行から Parquet を構築する設計のため、取り込み時の列構築は出力が使われていなかった。軽量な列役割状態（`MeasurementState`）に置換
4. **series 識別子の共有とメモ化**: `Arc<SeriesKey>` 共有 + ハッシュの構築時1回計算
5. **Line Protocol 高速パス**: エスケープ・クォートを含まない行を直接スライス解析（曖昧な行はすべて参照パーサーへフォールバック）。**差分プロパティテストが高速パスと参照パーサーの完全一致を強制**

## 3. 測定方法（再現手順つき）

- ワークロード・条件は `skulk/crates/skulk/benches/INGEST_BASELINE.md` に固定・記録
- **静穏窓規則**: load1 < 1.2 かつ load5 < 1.5 で開始した3連続ランの**中央値**で判定
- **汚染マーカー**: 変更していない経路の同時崩落を汚染判定に使用し、該当ランは除外（除外内容もベースラインに全記録）
- 測定環境は WSL2（ホスト側ディスク活動による±15%程度の残留分散あり）。今後のリリースゲートは専用CIランナーでの実行を推奨

再現:

```bash
cd skulk
cargo test --all-features            # 全テスト（クラッシュ回復・ロード/ストレス含む）
cargo bench --bench ingest_bench -- decode_wal_fsync_ack_10k --noplot
```

## 4. 既知の制限と今後

- 公開目標 **Line Protocol 500K pts/s および バッチ p99 <10ms は未達のまま**であり、目標は変更していない。実測分解の結果、残りの行あたりコストは名前キー行表現（`BTreeMap<String, …>`）と WAL の自己記述エンコードに由来し、到達には**行表現の世代交代**（列名インターン・WAL 列名辞書 = フォーマット改訂）が必要であることを定量的に確認した
- この結論は次世代の行表現設計（インターンID・ゼロコピー・WAL辞書分離）の妥当性を裏付けるものであり、将来バージョンで扱う

## 5. 参照

- 実測ベースライン: `skulk/crates/skulk/benches/INGEST_BASELINE.md`（v0.3.1 節）
- 変更一覧: `skulk/CHANGELOG.md` 0.3.1
- リリースPR: alopex-db/alopex-skulk #3
