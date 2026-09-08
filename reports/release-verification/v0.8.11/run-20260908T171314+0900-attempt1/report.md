# リリース確認レポート: v0.8.11

> 総合結果: **❌ 失敗あり**

v0.8.11 の確認中に失敗したステップがある。詳細は下記を参照。

## ステップ

### 1. コンテナイメージビルド ❌

検証専用の Docker イメージをビルドする。alopex-cli/alopex-server は `cargo install`、alopex(Python) は `pip install` で crates.io/PyPI から取得する(このイメージには alopex のソースコードを一切 COPY しない)。

```
time="2026-09-08T17:13:14+09:00" level=error msg="set sticky bit on: chmod /run/user/1000/libpod: read-only file system"
```

---

## 検証環境

| 項目 | 値 |
|---|---|
| 対象バージョン | v0.8.11 |
| 生成日時 (UTC) | 2026-09-08T08:13:14.328991Z |
| パッケージ取得元 | crates.io / PyPI |
| ソースビルド | なし(公開パッケージのみ使用) |
| Rust | `1.96` |
| Nim(ビルド専用イメージ) | `nimlang/nim:2.2` |
| Python | `3.11` |
