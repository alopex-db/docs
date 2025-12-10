# alopex-cli 要求仕様（ドラフト）

## 目的とスコープ
- Alopex DB/Server/Cluster を CLI から操作するための統一インターフェースを定義する。
- ユースケース: ローカル開発/検証、運用監視、バッチ投入、トラブルシュート。

## 対象モード
1) **ローカルファイル/オブジェクトアクセス**
   - 対象: `file://`（ローカル）、`https://`、`s3://` 等で配置された `.alopex` ファイル群。
   - 方式: 埋め込み API（alopex-embedded）をクライアント内に同梱し、読み取り/書き込みを直接実行。
   - 要件:
     - ファイル/URL からセグメントをオープンし、KVS/カラムナ/ベクトル/SQL CRUD を実行可能。
     - 読み取り専用オプションと書き込み可能オプションを明示。
     - 遅延ロードや範囲指定ダウンロード（Range GET）による大容量最適化を行う。
     - `https://` へのアップロード（書き込み）は非対応。`s3://` でのアップロード/書き込みはクレデンシャルとポリシーに依存し、権限がない場合は明示的にエラーとする。

2) **Server モード**
   - 対象: 単一 Alopex Server への接続。
   - 方式: gRPC/HTTP API 経由で RPC を発行。認証・接続設定を CLI で管理。
   - 要件:
     - KVS/カラムナ/ベクトル/SQL CRUD API の操作を提供。
     - サーバー状態確認: バージョン、起動時間、メトリクス、ストレージ使用量、接続数。
     - 管理操作: 健全性チェック、設定読み出し、メンテナンス操作（例: compaction トリガ、インデックス再構築）。

3) **Cluster モード**
   - 対象: Chirps ベースのクラスタまたは将来の cluster API。
   - 方式: クラスタエンドポイントへ接続し、ルーティング/フェイルオーバーを CLI 側でハンドル。
   - 要件:
     - CRUD 操作はクラスタの適切なノードへルーティング（メタデータ取得 → ノード選択）。
     - 状態確認: メンバー一覧、ロール（leader/follower）、ヘルス、Raft/レプリケーションラグ、シャード配置。
     - 管理操作: ノード追加/削除、リバランス、スナップショット/バックアップ起動、クラスタ設定変更（認証/圧縮/レプリカ係数など）。

## 機能要求
- **共通 CRUD**
  - KVS: get/put/delete/scan、トランザクション（begin/commit/rollback）。
  - カラムナ: セグメント ingest、scan（projection/filter pushdown）、統計/インデックス確認。
  - ベクトル: upsert/delete、knn/search（metric: cosine/L2/inner）、フィルタ条件付き検索。
  - SQL: execute/query、バッチ実行、結果ストリーム（JSON/CSV/TSV 出力選択）。
- **接続管理**
  - プロファイル保存: `~/.alopex/config` に接続名ごとのエンドポイント、認証情報、デフォルト DB/テーブル。
  - 認証: トークン/Basic/mTLS。mTLS 用の cert/key/CA 設定と検証。
  - タイムアウト/リトライ/バックオフ設定。
- **入出力**
  - 出力フォーマット: table/JSON/quiet/CSV/TSV（シンプル運用＋CSV/TSV を優先、NDJSON 等は当面非対応）。エラーは構造化 JSON を選択可能。
  - バッチ入出力: ファイル指定（-f）、標準入力/標準出力パイプ対応。
  - ページング: 大量結果のページング、または `--limit/--offset`。
- **オブザーバビリティ**
  - `status`/`metrics` コマンドでメトリクス/統計表示。
  - `profile` オプションで API 呼び出し時間や I/O バイト数を表示。
  - ログレベル切替（quiet/info/debug/trace）。
- **安全性・整合性**
  - 破壊的操作には確認プロンプト（`--yes` でスキップ）。
  - トランザクションがサポートされないモードでは警告を表示。
  - バージョン互換性チェック（クライアント/サーバー/ファイルフォーマット）。

## コマンド体系（案）
- `alopex profile` … プロファイルの作成/一覧/削除。
- `alopex kv` … get/put/delete/scan/txn。
- `alopex columnar` … ingest/scan/stats/index/show-segment。
- `alopex vector` … upsert/delete/search/build-index/show-stats。
- `alopex sql` … query/exec、バッチ実行（-f）。
- `alopex status` … 接続先の状態確認（server/cluster）。
- `alopex admin` … compaction、バックアップ、ノード管理、設定変更。
- `alopex config` … 全体設定の確認/編集（出力形式、TLS、timeout 等）。

## 実装フェーズ案
- Phase 1（ローカル/オブジェクト）: `file://`/`s3://` 読み書き、KVS/カラムナ/ベクトル/SQL CRUD、出力フォーマット（table/JSON/quiet/CSV/TSV）。
- Phase 2（Server）: プロファイル管理、認証（token/Basic/mTLS）、サーバー状態確認（status/metrics）、compaction などの軽微管理コマンド。
- Phase 3（Cluster）: クラスタ接続・ルーティング、メンバー/ロール表示、レプリケーションラグ確認、ノード追加/削除やリバランスなどの管理操作。

## UX 要件
- サブコマンドと主要オプションは短縮エイリアスを用意（例: `-p` プロファイル、`-o` 出力）。
- ヘルプは詳細/簡易の2段階（`-h` / `--help --verbose`）。
- エラーは改善アクション付きで表示（例: 認証失敗時に必要なフラグを提示）。
- オートコンプリートスクリプト生成（bash/zsh/fish/pwsh）。

## 将来拡張のための前提
- プラガブルなトランスポート/認証（gRPC/HTTP、mTLS/OIDC など）を前提に抽象化。
- クラスタメタデータの取得 API が変化しても CLI 側はアダプタで吸収できる構造にする。
- `alopex-cli` 自身のバージョンとサーバー/クラスタの互換性マトリクスを持ち、警告を出せるようにする。

## 非対象（当面の非ゴール）
- GUI/ブラウザ UI。
- ワークフロー定義やジョブスケジューラ的機能（別ツールと連携想定）。

## オープン事項
- Server/Cluster API の確定版エンドポイント仕様（auth/metrics/admin を含む）。
- クラスタ接続時のルーティング戦略（クライアント側 vs サーバー側プロキシ）。
- バックアップ/リストアの詳細な操作粒度と進捗レポート仕様。 
