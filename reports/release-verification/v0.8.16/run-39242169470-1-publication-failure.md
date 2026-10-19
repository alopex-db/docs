# リリース確認レポート: v0.8.16

> 総合結果: **❌ 失敗あり**

v0.8.16 の確認中に失敗したステップがある。詳細は下記を参照。

## ステップ

### 1. public package availability ✅

PyPIから完全一致wheelを取得し、隔離先へ導入してimportできることを確認する。既知機能の正しさは対象commitのDevelopment CI/Extended Verificationが所有する。

```
Collecting alopex==0.8.16
  Downloading alopex-0.8.16-cp38-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl.metadata (18 kB)
Downloading alopex-0.8.16-cp38-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl (12.5 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 12.5/12.5 MB 12.7 MB/s eta 0:00:00
Saved /home/runner/work/_temp/pypi-readiness-v0.8.16/alopex-0.8.16-cp38-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
Successfully downloaded alopex
Looking in links: /home/runner/work/_temp/pypi-readiness-v0.8.16
Processing /home/runner/work/_temp/pypi-readiness-v0.8.16/alopex-0.8.16-cp38-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
Installing collected packages: alopex
Successfully installed alopex-0.8.16
0.8.16
```

### 2. v0.8.16 public vector scenario ✅

PyPIから取得した完全一致wheelで、Kaggleと同じ組み込みPythonのベクトル投入・検索を再実行し、v0.8.16のget_vectors、バッチHNSW投入、重複キー原子拒否、kNN EXPLAIN経路表示を検証する。

```
installed wheel executes v0.8.16 vector/HNSW/streaming contracts
nearest=b'point' distance=0.0
second=b'quarter' distance=0.25
search_stats=nodes_visited
```

### 3. immutable report publication ❌

公開パッケージの検証は成功したが、docsへの保存依頼がHTTP403で失敗した。元runの失敗を後から保存した証跡。

```
Operator-retained evidence from original public verifier run39242169470 attempt1.
Published-package availability and vector scenario both succeeded.
2026-10-19T11:06:30Z Request docs report ingestion failed: Resource not accessible by personal access token (HTTP403).
Independent fallback Publish immutable failure report to docs also failed with exit128.
The failed Actions attempt remains unchanged; this is later evidence retention, not a rerun or a claim that publication succeeded.
```

---

## 検証環境

| 項目 | 値 |
|---|---|
| 対象バージョン | v0.8.16 |
| 開始日時 (UTC) | 2026-10-19T11:06:11.633550Z |
| 終了日時 (UTC) | 2026-10-19T11:13:49.218287Z |
| パッケージ取得元 | crates.io / PyPI |
| ソースビルド | なし(公開パッケージのみ使用) |
| Rust | `1.96` |
| Nim(ビルド専用イメージ) | `nimlang/nim:2.2` |
| Python | `3.11` |

## 証跡

| 項目 | 値 |
|---|---|
| Commit | `d9ff8783b8d18a63d167204e55902ea6cd90dcd1` |
| Tag | `alopex-py-v0.8.16` |
| Run | `39242169470` / attempt `1` |
| 責務層 | Stable Delivery / downstream availability |
| 失敗段階 | immutable report publication |
| 実行 | https://github.com/alopex-db/alopex/actions/runs/39242169470 |
