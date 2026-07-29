# docs
AlopexDB concepts, design documents, and specifications

## Public Surface References

- [v0.7 公開サーフェス](guides/v0.7-surfaces.md): 実在するcluster-aware、CLI、Python、DataFrame、SQL parser/WASMの境界
- [Skulk v0.3 公開サーフェス](guides/skulk-v0.3-surfaces.md): Skulk の現行ストレージ形式、3つのingestプロトコル、未達項目の境界
- 公開情報の回帰チェック: `bash scripts/check-public-surface.sh`

## Product Lines

Alopex DB 本体と Skulk は**独立したリポジトリ・独立したバージョン系列**である。

| 製品 | 系列 | ロードマップ |
|---|---|---|
| Alopex DB（本体） | v0.7.4 公開済 | [alopex-milestones.md](roadmap/alopex-milestones.md) |
| Alopex Skulk（時系列DB） | v0.3.0 公開済 | [skulk-milestones.md](roadmap/skulk-milestones.md) |
