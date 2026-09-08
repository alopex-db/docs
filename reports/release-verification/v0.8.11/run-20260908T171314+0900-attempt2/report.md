# リリース確認レポート: v0.8.11

> 総合結果: **❌ 失敗あり**

v0.8.11 の確認中に失敗したステップがある。詳細は下記を参照。

## ステップ

### 1. コンテナイメージビルド ✅

検証専用の Docker イメージをビルドする。alopex-cli/alopex-server は `cargo install`、alopex(Python) は `pip install` で crates.io/PyPI から取得する(このイメージには alopex のソースコードを一切 COPY しない)。

```
  Downloaded thiserror-impl v2.0.17
  Downloaded thiserror v1.0.69
  Downloaded thiserror-impl v1.0.69
  Downloaded thiserror v2.0.17
   Compiling thiserror v1.0.69
   Compiling thiserror-impl v1.0.69
   Compiling thiserror v2.0.17
   Compiling thiserror-impl v2.0.17
  Downloaded serde_path_to_error v0.1.20
   Compiling thiserror v1.0.69
   Compiling thiserror-impl v1.0.69
   Compiling thiserror v2.0.17
   Compiling thiserror-impl v2.0.17
   Compiling serde_path_to_error v0.1.20
   Compiling encoding_rs v0.8.35
   Compiling arraydeque v0.5.1
   Compiling minimal-lexical v0.2.1
   Compiling prometheus v0.14.0
   Compiling base64 v0.21.7
   Compiling unicode-segmentation v1.12.0
   Compiling hex v0.4.3
   Compiling convert_case v0.6.0
   Compiling ron v0.8.1
   Compiling yaml-rust2 v0.8.1
   Compiling zstd v0.13.3
   Compiling parquet v53.4.1
   Compiling alopex-core v0.8.11
   Compiling nom v7.1.3
   Compiling tonic v0.14.6
   Compiling arc-swap v1.8.0
   Compiling tokio-rustls v0.26.4
   Compiling rust-ini v0.20.0
   Compiling json5 v0.4.1
   Compiling toml v0.8.23
   Compiling alopex-server v0.8.11
   Compiling sharded-slab v0.1.7
   Compiling matchers v0.2.0
   Compiling tracing-log v0.2.0
   Compiling thread_local v1.1.9
   Compiling humantime v2.3.0
   Compiling nu-ansi-term v0.50.3
   Compiling pathdiff v0.2.3
   Compiling axum-server v0.8.0
   Compiling config v0.14.1
   Compiling tracing-subscriber v0.3.22
   Compiling humantime-serde v1.1.1
   Compiling tonic-prost v0.14.6
   Compiling tower-http v0.6.8
   Compiling rustls-pemfile v2.2.0
   Compiling dashmap v5.5.3
   Compiling alopex-cluster v0.8.11
    Finished `release` profile [optimized] target(s) in 29m 20s
  Installing /home/verify/.cargo/bin/alopex-server
   Installed package `alopex-server v0.8.11` (executable `alopex-server`)
--> Using cache cbe750b2a337514635613f06f689d2ad5bc4b7062e22a0d077720fcdd17f8ece
--> cbe750b2a337
[2/2] STEP 22/26: ENV PATH=/home/verify/.cargo/bin:${PATH}
--> Using cache 74a50e14a4e84b6a8c6095e2b223ad61bf1045578421c9fba0c7bc717b476fd3
--> 74a50e14a4e8
[2/2] STEP 23/26: COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
--> Using cache 81eacc7850c5deab274867ae35fe43bfca8687f83b3e7ed38b750628976bf1c7
--> 81eacc7850c5
[2/2] STEP 24/26: ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
--> Using cache a3c7eb49b253c413d331e057c9e52aa1d00dcec062c104d0f65cc8e962d78113
--> a3c7eb49b253
[2/2] STEP 25/26: WORKDIR /workspace
--> Using cache aa2fde55521ba496db2ae75fa3a334b9aa98c90ee8a70d1650965246e2f96c71
--> aa2fde55521b
[2/2] STEP 26/26: CMD ["bash"]
--> Using cache 0c616e71f08111e49ce7aae7d96e9df49b7b8b5973da3152159873712869b0df
[2/2] COMMIT alopex-verify-release:0.8.11
--> 0c616e71f081
Successfully tagged localhost/alopex-verify-release:0.8.11
0c616e71f08111e49ce7aae7d96e9df49b7b8b5973da3152159873712869b0df
```

### 2. verify-release-embedded ビルド ❌

公開検証用の3つの bin source を一時 crate へコピーし、ALOPEX_VERSION と完全一致する crates.io 公開版 alopex-embedded/alopex-core/alopex-sql だけを依存としてビルドする。固定 Cargo.toml の追随漏れと repository path 混入の双方を防ぐ。

```
  Downloaded thiserror v2.0.20
  Downloaded thiserror-impl v2.0.20
error: failed to create directory `/tools-target/release`
  Permission denied (os error 13)
    Updating crates.io index
     Locking 173 packages to latest Rust 1.96.0 compatible versions
      Adding chrono v0.4.39 (available: v0.4.45)
      Adding generic-array v0.14.7 (available: v0.14.9)
      Adding zstd-safe v7.2.1 (available: v7.3.0)
      Adding zstd-sys v2.0.13+zstd.1.5.6 (available: v2.1.0+zstd.1.5.7)
 Downloading crates ...
  Downloaded futures-core v0.3.34
  Downloaded num-iter v0.1.46
  Downloaded alloc-stdlib v0.2.4
  Downloaded itoa v1.0.18
  Downloaded jobserver v0.1.35
  Downloaded zmij v1.0.23
  Downloaded uuid v1.26.0
  Downloaded serde_core v1.0.229
  Downloaded proc-macro2 v1.0.107
  Downloaded rand v0.8.8
  Downloaded zerocopy-derive v0.8.56
  Downloaded num-bigint v0.4.8
  Downloaded memchr v2.8.3
  Downloaded serde_json v1.0.151
  Downloaded regex v1.13.1
  Downloaded libm v0.2.16
  Downloaded hashbrown v0.17.1
  Downloaded indexmap v2.14.2
  Downloaded cc v1.4.5
  Downloaded serde v1.0.229
  Downloaded zerocopy v0.8.56
  Downloaded syn v3.0.5
  Downloaded miniz_oxide v0.9.1
  Downloaded syn v2.0.119
  Downloaded regex-syntax v0.8.11
  Downloaded flate2 v1.1.10
  Downloaded aho-corasick v1.1.5
  Downloaded ryu v1.0.23
  Downloaded crc32fast v1.5.1
  Downloaded unicode-ident v1.0.24
  Downloaded serde_derive v1.0.229
  Downloaded iana-time-zone v0.1.65
  Downloaded find-msvc-tools v0.1.12
  Downloaded twox-hash v2.1.4
  Downloaded regex-automata v0.4.18
  Downloaded snap v1.1.2
  Downloaded simd-adler32 v0.3.10
  Downloaded semver v1.0.28
  Downloaded once_cell v1.21.4
  Downloaded autocfg v1.5.1
  Downloaded shlex v2.0.1
  Downloaded quote v1.0.47
  Downloaded pkg-config v0.3.34
  Downloaded pin-project-lite v0.2.17
  Downloaded zstd-sys v2.0.13+zstd.1.5.6
  Downloaded num-integer v0.1.47
  Downloaded libc v0.2.189

Caused by:
```

---

## 検証環境

| 項目 | 値 |
|---|---|
| 対象バージョン | v0.8.11 |
| 生成日時 (UTC) | 2026-09-08T08:14:24.024247Z |
| パッケージ取得元 | crates.io / PyPI |
| ソースビルド | なし(公開パッケージのみ使用) |
| Rust | `1.96` |
| Nim(ビルド専用イメージ) | `nimlang/nim:2.2` |
| Python | `3.11` |
