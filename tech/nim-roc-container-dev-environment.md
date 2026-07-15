# Nim / Roc コンテナ開発環境構築 調査レポート

**作成日**: 2026-06-27
**目的**: Alopex SQL パーサーの代替言語候補（Nim, Roc）のコンテナ開発環境を調査し、実現可能性を評価する

---

## 1. 概要

コンテナ環境ではいずれの言語もバイナリの取得と配置だけで完結するため、**構築コストに本質的な差はない**。公式イメージの有無はローカル開発の利便性に影響するが、コンテナ内では `curl + tar` で同等にセットアップできる。

| 項目 | **Nim** | **Roc** |
|---|---|---|
| 公式 Docker イメージ | ◎ [nimlang/nim](https://hub.docker.com/r/nimlang/nim/) | × なし（ただしバイナリ取得は容易） |
| コンテナ内セットアップ | `FROM nimlang/nim:2.2` | `curl + tar` で ~30MB のバイナリを配置 |
| Devcontainer | ○ [metio/devcontainers-nim](https://hub.docker.com/r/metio/devcontainers-nim) | ○ debian + postCreateCommand で構築可能 |
| マルチアーキテクチャ | ◎ amd64, arm64, armv7 | ○ x86_64, arm64 |
| ベースイメージ選択 | Alpine Slim ~50MB / Ubuntu Slim | debian-slim + Roc バイナリ ~100MB |
| バージョン固定 | ◎ セマンティックバージョニング | △ alpha-rolling（tar.gz URL で固定可能） |

---

## 2. Nim コンテナ開発環境

### 2.1 公式 Docker イメージ

[nim-lang/docker-images](https://github.com/nim-lang/docker-images) で公式メンテナンスされている。

**利用可能なタグ**:

| タグパターン | 例 | 用途 |
|---|---|---|
| `latest` | `nimlang/nim:latest` | 最新安定版 |
| `{major}` | `nimlang/nim:2` | メジャーバージョン固定 |
| `{major}.{minor}` | `nimlang/nim:2.2` | マイナーバージョン固定 |
| `{major}.{minor}.{patch}` | `nimlang/nim:2.2.8` | 完全固定（再現性重視） |
| `*-alpine-slim` | `nimlang/nim:2.2-alpine-slim` | 最小イメージ（~50MB） |
| `*-alpine-regular` | `nimlang/nim:2.2.2-alpine-regular` | Alpine + 追加ツール |
| `*-ubuntu-slim` | `nimlang/nim:2.0.4-ubuntu-slim` | Ubuntu ベース slim |

**含まれるツールチェーン**:
- Nim コンパイラ
- Nimble パッケージマネージャ
- C/C++ コンパイラ（gcc/musl-gcc）
- Node.js（JS バックエンド用）
- SSL サポート（nimble のリモートパッケージ取得用）

### 2.2 基本的な使い方

```bash
# 即座にコンパイル＆実行
docker run --rm -v "$(pwd)":/usr/src/app nimlang/nim:latest \
  nim c -r /usr/src/app/main.nim

# nimble パッケージのインストール
docker run --rm -v "$(pwd)":/usr/src/app nimlang/nim:latest \
  nimble install -y npeg
```

### 2.3 Alopex SQL パーサー向け Dockerfile（案）

```dockerfile
# ==============================================================
# Stage 1: Nim でパーサーを共有ライブラリとしてビルド
# ==============================================================
FROM nimlang/nim:2.2-alpine-slim AS nim-builder

WORKDIR /build

# 依存パッケージのインストール
COPY nimble.lock nim-sql-parser.nimble ./
RUN nimble install -y --depsOnly

# ソースコードのコピーとビルド
COPY src/ ./src/

# 共有ライブラリ (.so) としてビルド — Rust から FFI で呼び出す
RUN nim c \
  -d:release \
  --app:lib \
  --noMain \
  --gc:orc \
  --opt:speed \
  -o:/build/libalopex_sql_parser.so \
  src/alopex_sql_parser.nim

# ヘッダファイルの生成（Rust FFI 用）
RUN nim c \
  -d:release \
  --header:alopex_sql_parser.h \
  --noMain \
  --app:lib \
  src/alopex_sql_parser.nim

# ==============================================================
# Stage 2: Rust プロジェクトに統合
# ==============================================================
FROM rust:1.87-alpine AS rust-builder

WORKDIR /app

# Nim でビルドした共有ライブラリをコピー
COPY --from=nim-builder /build/libalopex_sql_parser.so /usr/local/lib/
COPY --from=nim-builder /build/alopex_sql_parser.h /usr/local/include/

# Rust プロジェクトのビルド
COPY alopex/ ./
RUN cargo build --release

# ==============================================================
# Stage 3: 最小ランタイムイメージ
# ==============================================================
FROM alpine:3.21

COPY --from=rust-builder /app/target/release/alopex-server /usr/local/bin/
COPY --from=nim-builder /build/libalopex_sql_parser.so /usr/local/lib/

RUN ldconfig /usr/local/lib

ENTRYPOINT ["alopex-server"]
```

### 2.4 Nim の C 共有ライブラリ出力

Nim から C ABI 互換の共有ライブラリを出力する方法:

```nim
# alopex_sql_parser.nim

# Nim のランタイム初期化（ライブラリ利用側が呼ぶ必要あり）
proc NimMain() {.importc.}

# C ABI でエクスポートする関数
proc alopex_parser_init*() {.exportc, dynlib, cdecl.} =
  NimMain()

proc alopex_parse_sql*(input: cstring, len: cint): pointer {.exportc, dynlib, cdecl.} =
  ## SQL 文字列をパースし、AST のポインタを返す
  let sql = $input  # cstring → Nim string
  let ast = parseSql(sql)
  # ... AST を C 互換構造体に変換して返す

proc alopex_free_ast*(ast: pointer) {.exportc, dynlib, cdecl.} =
  ## AST のメモリを解放
  # ...
```

コンパイル:
```bash
nim c -d:release --app:lib --noMain --gc:orc -o:libalopex_sql_parser.so alopex_sql_parser.nim
```

### 2.5 Devcontainer 設定（VS Code）

```jsonc
// .devcontainer/devcontainer.json
{
  "name": "Alopex SQL Parser (Nim)",
  "image": "nimlang/nim:2.2-alpine-regular",
  "customizations": {
    "vscode": {
      "extensions": [
        "nimsaem.nimvscode",
        "saem.vscode-nim"
      ]
    }
  },
  "postCreateCommand": "nimble install -y npeg",
  "mounts": [
    "source=${localWorkspaceFolder},target=/workspace,type=bind"
  ]
}
```

---

## 3. Roc コンテナ開発環境

### 3.1 インストール方法

Roc は公式 Docker イメージを提供していない。以下の方法でインストールする:

#### 方法 A: バイナリリリース（推奨・簡単）

```bash
# Linux x86_64
curl -OL https://github.com/roc-lang/roc/releases/download/alpha4-rolling/roc-linux_x86_64-alpha4-rolling.tar.gz
tar xzf roc-linux_x86_64-alpha4-rolling.tar.gz
export PATH=$PATH:$(pwd)/roc-linux_x86_64-alpha4-rolling
```

#### 方法 B: Nix Flake（推奨・再現性重視）

```nix
# flake.nix
{
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixpkgs-unstable";
    roc.url = "github:roc-lang/roc";
  };

  outputs = { nixpkgs, roc, ... }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      rocPkgs = roc.packages.${system};
    in {
      devShells.${system}.default = pkgs.mkShell {
        buildInputs = [
          rocPkgs.cli
        ];
      };
    };
}
```

```bash
nix develop  # Roc が使える shell に入る
```

#### 方法 C: ソースビルド

```bash
# Zig 0.15.2 が必要
git clone https://github.com/roc-lang/roc.git
cd roc
# BUILDING_FROM_SOURCE.md に従う
```

### 3.2 Roc 用 Dockerfile（案）

公式 Docker イメージはないが、バイナリリリースを `curl + tar` で取得するだけでセットアップは完了する。

```dockerfile
# ==============================================================
# 方法 A: バイナリリリースベース（シンプル）
# ==============================================================
FROM debian:bookworm-slim AS roc-env

# 必要な依存
RUN apt-get update && apt-get install -y \
  curl \
  ca-certificates \
  gcc \
  libc6-dev \
  && rm -rf /var/lib/apt/lists/*

# Roc バイナリのダウンロード
ARG ROC_VERSION=alpha4-rolling
RUN curl -OL https://github.com/roc-lang/roc/releases/download/${ROC_VERSION}/roc-linux_x86_64-${ROC_VERSION}.tar.gz \
  && tar xzf roc-linux_x86_64-${ROC_VERSION}.tar.gz \
  && mv roc-linux_x86_64-${ROC_VERSION} /opt/roc \
  && rm roc-linux_x86_64-${ROC_VERSION}.tar.gz

ENV PATH="/opt/roc:${PATH}"

WORKDIR /app
```

```dockerfile
# ==============================================================
# 方法 B: Nix ベース（再現性重視、イメージサイズ大）
# ==============================================================
FROM nixos/nix:latest AS roc-nix

RUN echo "experimental-features = nix-command flakes" >> /etc/nix/nix.conf

WORKDIR /app
COPY flake.nix flake.lock ./
RUN nix develop --command echo "Roc environment ready"

# 以降、nix develop 内で roc コマンドを使用
```

### 3.3 Roc の Platform/Host 構成でのコンテナ

Roc + Rust Host のビルドパイプライン:

```dockerfile
# ==============================================================
# Stage 1: Roc パーサーをビルド
# ==============================================================
FROM debian:bookworm-slim AS roc-builder

RUN apt-get update && apt-get install -y curl ca-certificates gcc libc6-dev \
  && rm -rf /var/lib/apt/lists/*

ARG ROC_VERSION=alpha4-rolling
RUN curl -OL https://github.com/roc-lang/roc/releases/download/${ROC_VERSION}/roc-linux_x86_64-${ROC_VERSION}.tar.gz \
  && tar xzf roc-linux_x86_64-${ROC_VERSION}.tar.gz \
  && mv roc-linux_x86_64-${ROC_VERSION} /opt/roc \
  && rm roc-linux_x86_64-${ROC_VERSION}.tar.gz

ENV PATH="/opt/roc:${PATH}"

WORKDIR /build
COPY roc-parser/ ./

# Roc アプリをコンパイル → C ABI オブジェクトを出力
RUN roc build --optimize sql_parser.roc

# ==============================================================
# Stage 2: Rust Host とリンク
# ==============================================================
FROM rust:1.87-bookworm AS rust-builder

WORKDIR /app

COPY --from=roc-builder /build/sql_parser /usr/local/lib/
COPY alopex/ ./

RUN cargo build --release

# ==============================================================
# Stage 3: ランタイム
# ==============================================================
FROM debian:bookworm-slim

COPY --from=rust-builder /app/target/release/alopex-server /usr/local/bin/
ENTRYPOINT ["alopex-server"]
```

### 3.4 Devcontainer 設定（VS Code）

```jsonc
// .devcontainer/devcontainer.json (Roc)
{
  "name": "Alopex SQL Parser (Roc)",
  "image": "debian:bookworm-slim",
  "features": {
    "ghcr.io/devcontainers/features/common-utils:2": {}
  },
  "customizations": {
    "vscode": {
      "extensions": [
        "IvanDemchenko.roc-lang-unofficial"
      ]
    }
  },
  "postCreateCommand": "curl -OL https://github.com/roc-lang/roc/releases/download/alpha4-rolling/roc-linux_x86_64-alpha4-rolling.tar.gz && tar xzf roc-linux_x86_64-alpha4-rolling.tar.gz && sudo mv roc-linux_x86_64-alpha4-rolling /opt/roc && echo 'export PATH=/opt/roc:$PATH' >> ~/.bashrc",
  "remoteEnv": {
    "PATH": "/opt/roc:${containerEnv:PATH}"
  }
}
```

---

## 4. 比較評価

### 4.1 コンテナ開発環境の比較

コンテナ環境では両言語とも構築コストは同等。差異はツールチェーンの成熟度に集約される。

| 観点 | **Nim** | **Roc** |
|---|---|---|
| コンテナ構築コスト | ○ `FROM nimlang/nim` で完了 | ○ `curl + tar` で完了（同等） |
| CI/CD 統合 | ◎ 公式イメージで GitHub Actions 実績多数 | ○ Dockerfile 数行で対応可能 |
| マルチアーキ | ◎ amd64/arm64/armv7 | ○ x86_64/arm64 |
| バージョン固定 | ◎ セマンティックバージョニング | △ alpha-rolling（URL 固定で回避可能） |
| 再現性 | ◎ イメージタグで完全再現 | ○ tar.gz URL 固定 or Nix Flake |

### 4.2 Rust プロジェクトとのコンテナ統合

| 観点 | **Nim** | **Roc** |
|---|---|---|
| マルチステージビルド | ◎ Nim → .so → Rust リンクが確立されたパターン | △ ビルドパイプラインが未確立 |
| 出力形式 | ◎ `.so` / `.a` (C 共有/静的ライブラリ) | △ 実行バイナリ（ライブラリ出力は未成熟） |
| ヘッダ生成 | ◎ `--header` フラグで C ヘッダ自動生成 | × なし |
| GC 制御 | ◎ `--gc:orc` / `--gc:none` 選択可能 | ○ Perceus（自動） |
| 静的リンク | ◎ musl + `--passL:"-static"` | △ 未検証 |

### 4.3 開発ワークフロー

| ワークフロー | **Nim** | **Roc** |
|---|---|---|
| ローカル開発 | `nimble install && nim c -r` | `nix develop && roc run` or バイナリ直接 |
| コンテナ開発 | `docker run nimlang/nim nim c -r` | `docker build` + `roc run`（構築コスト同等） |
| テスト | `nimble test` (unittest2) | `roc test` |
| パッケージ管理 | nimble (成熟) | roc packages (初期段階) |
| LSP / IDE | nimlsp / VS Code 拡張あり | 非公式 VS Code 拡張あり |
| CI/CD | `nimlang/nim` イメージで即座に構築可能 | Dockerfile 数行で対応可能 |

---

## 5. 推奨構成

### Nim（推奨: すぐに着手可能）

```
alopex-db/
├── nim-sql-parser/              # Nim パーサープロジェクト
│   ├── .devcontainer/
│   │   └── devcontainer.json    # VS Code Devcontainer
│   ├── Dockerfile               # マルチステージビルド
│   ├── nim-sql-parser.nimble    # パッケージ定義
│   └── src/
│       ├── alopex_sql_parser.nim  # エントリポイント (exportc)
│       ├── lexer.nim
│       ├── parser.nim           # npeg PEG 文法
│       └── ast.nim              # AST 定義
├── alopex/
│   └── crates/alopex-sql/
│       ├── build.rs             # Nim .so のリンク設定
│       └── src/
│           └── ffi.rs           # extern "C" FFI バインディング
```

### Roc（環境構築コストは Nim と同等、言語設計が優れている）

```
alopex-db/
├── roc-sql-parser/              # Roc パーサープロジェクト
│   ├── Dockerfile               # 自前ビルド
│   ├── flake.nix                # Nix Flake (再現性)
│   ├── sql_parser.roc           # メインパーサー
│   └── platform/
│       └── main.roc             # Rust Host との接点
├── alopex/
│   └── crates/alopex-sql/
│       └── src/
│           └── roc_host.rs      # Roc Platform Host
```

---

## 6. 試験実装の計測結果

Rust 版 SQL パーサー（alopex-sql クレート）のテストケースを Nim / Roc にそれぞれ移植し、同等の SQL パーサーを実装した上でコード量・ビルド時間を計測した。計測は Docker コンテナ内で `--no-cache` ビルドにより実施。

### 6.1 コード量

現在の試験実装は SQLite 文法の約 15〜20% をカバーしている（基本 DML + 単純な DDL のみ）。SQLite 相当のフルパーサーには、サブクエリ、CTE（再帰含む）、ウィンドウ関数、CASE 式、UNION / INTERSECT / EXCEPT、ALTER TABLE、CREATE VIEW / Trigger、トランザクション制御、UPSERT、RETURNING 句、COLLATE、生成列など多数の文法が追加で必要となる。コード量は現在の **約 6 倍** と推定される。

#### 実装コード

| ファイル | **Nim** | **Roc** | **Rust** |
|---|---|---|---|
| AST 定義 | 140 行 | 93 行 | 478 行（5ファイル） |
| レキサー | 234 行 | 242 行 | 620 行（3ファイル） |
| パーサー | 616 行 | 686 行 | 1,866 行（6ファイル） |
| FFI / エントリポイント | 114 行 | 28 行 | — |
| **実装合計** | **1,104 行** | **1,049 行** | **2,964 行** |
| **SQLite 相当（推定 ×6）** | **〜6,600 行** | **〜6,300 行** | **〜18,000 行** |

#### テストコード

| | **Nim** | **Roc** | **Rust**（パーサー関連のみ） |
|---|---|---|---|
| テストコード | 601 行 | 584 行 | 570 行（4ファイル） |
| テスト数 | 58 テスト | 56 テスト (expect) | 74+ テスト |
| テスト結果 | **全 PASS** | **全 PASS** | 全 PASS |
| **SQLite 相当（推定 ×6）** | **〜3,600 行** | **〜3,500 行** | **〜3,400 行** |

#### カバー範囲

両言語とも Rust 版の以下のテストカテゴリを移植済み:

- **Tokenizer**: キーワード大文字小文字、識別子保持、数値・浮動小数点、文字列エスケープ、演算子、コメント
- **Expression**: リテラル、単項演算子（NOT, 負号）、演算子優先順位、括弧、BETWEEN / NOT BETWEEN、LIKE / NOT LIKE / ESCAPE、IN / NOT IN、IS NULL / IS NOT NULL、関数呼び出し、テーブル.カラム参照
- **DML**: SELECT（DISTINCT, WHERE, ORDER BY ASC/DESC, LIMIT, OFFSET, 列/テーブル別名）、INSERT（列リスト、複数行 VALUES）、UPDATE（複数 SET、WHERE）、DELETE
- **DDL**: CREATE TABLE（IF NOT EXISTS, PRIMARY KEY, NOT NULL, UNIQUE, DEFAULT, 複数データ型）、DROP TABLE（IF EXISTS）

SQLite 相当にはさらに以下が必要:

- サブクエリ（FROM / WHERE / EXISTS）、CTE（WITH ... AS、再帰）
- ウィンドウ関数（OVER、PARTITION BY、フレーム指定）
- CASE WHEN THEN ELSE END、CAST、COALESCE
- UNION / INTERSECT / EXCEPT
- 複合 JOIN（NATURAL、USING、多段ネスト）
- ALTER TABLE（ADD / RENAME / DROP COLUMN）
- CREATE / DROP VIEW、Index、Trigger
- トランザクション制御（BEGIN / COMMIT / ROLLBACK / SAVEPOINT）
- UPSERT（INSERT ... ON CONFLICT）、RETURNING 句
- EXPLAIN / EXPLAIN QUERY PLAN
- ATTACH / DETACH / PRAGMA / VACUUM
- COLLATE、GLOB、生成列、完全な外部キー制約

### 6.2 ビルド時間

計測環境: Nim / Roc は Docker コンテナ内 `--no-cache` ビルド、Rust はホスト上で `cargo clean -p alopex-sql` 後に計測。SQLite 相当の推定値はコード量 ×6 に基づく線形外挿（Rust は依存クレートのコンパイル時間が支配的なためパーサーコード増分のみ加算）。

| 計測項目 | **Nim** | **Roc** | **Rust** |
|---|---|---|---|
| **現在の計測値** | | | |
| release ビルド | **2.6 秒** | 4.7 秒 | 165 秒 |
| dev ビルド | — | **0.8 秒** | — |
| テスト（ビルド込み） | 4.9 秒 | — | 124 秒 |
| テスト（実行のみ） | — | **0.3 秒** | 0.01 秒 |
| **SQLite 相当（推定 ×6）** | | | |
| release ビルド | **〜16 秒** | 〜28 秒 | **〜250 秒（4 分超）** |
| dev ビルド | — | **〜5 秒** | — |
| テスト（ビルド込み） | 〜30 秒 | — | **〜200 秒（3 分超）** |
| テスト（実行のみ） | — | **〜2 秒** | — |

現時点で SQL 文法の一部（SELECT / INSERT / UPDATE / DELETE / CREATE TABLE / DROP TABLE）しか実装していない段階で、Rust の alopex-sql クレートは release ビルドに **2 分 45 秒**を要する。SQLite 相当のフル SQL パーサーに拡張すると **4 分超**、テストのイテレーションに **3 分超**が見込まれる。1 回の修正→テストサイクルに 3〜4 分かかる環境では、SQL パーサーの反復開発は現実的ではない。

一方、Nim は SQLite 相当でも release ビルド **16 秒**、テスト **30 秒**に収まり、Roc は dev ビルド **5 秒** + テスト実行 **2 秒**で完結する。いずれも Rust の **10 倍以上高速**な開発イテレーションが可能である。

### 6.3 ビルド時の課題

| 課題 | **Nim** | **Roc** |
|---|---|---|
| API 変更対応 | `--gc:orc` → `--mm:orc` の1箇所のみ | camelCase → snake_case 全面移行（24箇所修正） |
| 未使用 import | 警告のみ（ビルド成功） | エラー扱い（exit code 2、修正必須） |
| リンカー問題 | なし | surgical linker の issue #3609 により `--linker=legacy` 必須 |
| パッケージ名制約 | ハイフン不可（`nim-sql-parser` → `nim_sql_parser`） | なし |
| プラットフォーム URL | — | basic-cli 0.19.0 → 0.20.0 で URL ハッシュ変更（404） |

---

## 7. 結論

**コンテナ環境では Nim も Roc も構築コストは同等**であり、どちらも Phase 1 の着手に障壁はない。公式 Docker イメージの有無はローカル開発の利便性の差に過ぎず、コンテナ内では `curl + tar` でバイナリを配置するだけで完結する。

**試験実装により差異が明確化された**:

| 差異の源泉 | **Nim** | **Roc** |
|---|---|---|
| C ライブラリ出力 | ◎ `--app:lib` + ヘッダ自動生成 | △ ライブラリ出力ワークフロー未確立 |
| GC 制御 | ◎ `--mm:orc` / `--mm:none` 選択可能 | ○ Perceus（自動、選択不可） |
| バージョン安定性 | ◎ 2.x 安定版（API 変更 1 箇所） | △ alpha（API 全面変更 24 箇所） |
| SQL パーサー実績 | ◎ `std/parsesql` が標準ライブラリに内蔵 | × なし |
| 実装コード量（現在） | ◎ 1,104 行（Rust の 37%） | ◎ 1,049 行（Rust の 35%） |
| 実装コード量（SQLite 相当推定） | 〜6,600 行 | 〜6,300 行 |
| release ビルド（現在 → SQLite 相当） | ◎ 2.6 秒 → **16 秒** | ○ 4.7 秒 → 28 秒 |
| dev ビルド（SQLite 相当） | — | ◎ **〜5 秒** |
| テスト 1 サイクル（SQLite 相当） | ○ 〜30 秒 | ◎ **〜7 秒** |
| Rust 比 ビルド速度 | **63x → 16x 高速** | **35x → 9x 高速** |

**コンテナ環境構築は両方とも即座に可能**であるため、言語選択の判断基準はコンテナではなく、前述の SQL パーサー実装の適性評価（[sql-engine-research.md セクション 10](sql-engine-research.md)）に基づくべきである。

---

## 8. 参考資料

### Nim

- [nimlang/nim Docker Hub](https://hub.docker.com/r/nimlang/nim/)
- [nim-lang/docker-images (GitHub)](https://github.com/nim-lang/docker-images)
- [metio/devcontainers-nim](https://hub.docker.com/r/metio/devcontainers-nim)
- [How to Containerize a Nim Application with Docker (2026)](https://oneuptime.com/blog/post/2026-02-08-how-to-containerize-a-nim-application-with-docker/view)
- [Nim Backend Integration (C/C++ FFI)](https://nim-lang.github.io/Nim/backends.html)
- [Dynamic libraries in Nim](https://peterme.net/dynamic-libraries-in-nim.html)
- [Nim Compiler User Guide](https://nim-lang.org/docs/nimc.html)
- [std/parsesql](https://nim-lang.org/docs/parsesql.html)

### Roc

- [Roc Install Guide](https://www.roc-lang.org/install/)
- [Getting started on Linux x86_64](https://www.roc-lang.org/install/linux_x86_64)
- [Getting started with Nix](https://www.roc-lang.org/install/nix)
- [roc-lang/roc flake.nix (GitHub)](https://github.com/roc-lang/roc/blob/main/flake.nix)
- [BUILDING_FROM_SOURCE.md](https://github.com/roc-lang/roc/blob/main/BUILDING_FROM_SOURCE.md)
- [roc-lang/roc devtools README](https://github.com/roc-lang/roc/blob/main/devtools/README.md)

### Docker / Nix 全般

- [Using Nix with Dockerfiles (Mitchell Hashimoto)](https://mitchellh.com/writing/nix-with-dockerfiles)
- [Building Docker images with Nix (nix.dev)](https://nix.dev/tutorials/nixos/building-and-running-docker-images.html)
