# セキュリティガイド

このリポジトリは [sponsors-orchestrator](https://github.com/asopitech-labs/sponsors-orchestrator) によりスポンサー向けに配信されます。機密情報の漏洩を防ぐため、以下のセキュリティ機能が導入されています。

## セキュリティ機能

### 1. GitHub Actions セキュリティスキャン

`.github/workflows/security-scan.yml` により、PR作成時・push時に自動スキャンが実行されます。

#### 検出項目

| 項目 | パターン例 | 検出時 |
|------|-----------|-------|
| ローカルパス | `/home/user/`, `/Users/name/` | Warning |
| プライベートIP | `192.168.x.x`, `10.x.x.x` | Warning |
| APIキー | `ghp_*`, `sk-*`, `AKIA*` | **Error（PRブロック）** |
| 認証情報 | `password = "xxx"` | **Error（PRブロック）** |
| 機密ファイル | `.env`, `*.pem`, `*.key` | **Error（PRブロック）** |

**Warning**: 警告は表示されますがマージ可能です。配信時にサニタイズされます。

**Error**: PRがブロックされます。修正が必要です。

### 2. Pre-commit Hook（推奨）

コミット前にローカルでチェックを実行できます。

#### 設定方法

```bash
# Git hook として設定
cp scripts/pre-commit-check.sh .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

#### 手動実行

```bash
./scripts/pre-commit-check.sh
```

#### バイパス（非推奨）

緊急時のみ使用してください：

```bash
git commit --no-verify
```

### 3. .gitignore

機密ファイルが誤ってコミットされないよう、以下のパターンが除外されています：

- 環境変数: `.env`, `.env.*`
- 秘密鍵: `*.pem`, `*.key`, `id_rsa*`
- 認証情報: `credentials.*`, `secrets.*`
- ローカル設定: `config.local.*`, `local.settings.json`

## 配信時のセキュリティ処理

sponsors-orchestrator は配信前に追加のセキュリティ処理を行います：

### サニタイズ（自動置換）

| パターン | 置換後 |
|---------|--------|
| `/home/username/...` | `/home/{USER}/...` |
| `/tmp/...` | `{TEMP}/...` |
| `192.168.x.x` | `{PRIVATE_IP}` |
| `postgresql://...` | `{DATABASE_URL}` |

### ブロック（配信除外）

以下を含むファイルは配信から除外されます：

- APIキー・トークン
- ハードコードされたパスワード
- 秘密鍵ファイル

## ベストプラクティス

### DO（推奨）

- 環境変数を使用する（ハードコードしない）
- プレースホルダーを使用する（`your_api_key_here`）
- 例示には架空の値を使用する（`192.0.2.1` = TEST-NET-1）
- pre-commit hook を設定する

### DON'T（禁止）

- 本番の認証情報をコミットしない
- ローカル環境固有のパスを記載しない
- `.env` ファイルをコミットしない
- `--no-verify` を常用しない

## 問題が発生した場合

### PRがブロックされた

1. GitHub Actions のログを確認
2. 検出された箇所を修正
3. 再度 push

### 機密情報をコミットしてしまった

1. **すぐに** 該当の認証情報を無効化（トークン再発行等）
2. `git filter-branch` または BFG Repo-Cleaner で履歴から削除
3. Force push（要注意）

```bash
# BFG を使用した例
bfg --delete-files .env
git reflog expire --expire=now --all
git gc --prune=now --aggressive
git push --force
```

## 関連ドキュメント

- [sponsors-orchestrator README](https://github.com/asopitech-labs/sponsors-orchestrator)
- [GitHub - Removing sensitive data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
