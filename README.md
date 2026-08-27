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
| Alopex DB（本体） | [![Latest Alopex DB release](https://img.shields.io/github/v/release/alopex-db/alopex?sort=semver&label=latest)](https://github.com/alopex-db/alopex/releases/latest) | [alopex-milestones.md](roadmap/alopex-milestones.md) |
| Alopex Skulk（時系列DB） | [![crates.io](https://img.shields.io/crates/v/alopex-skulk.svg)](https://crates.io/crates/alopex-skulk) | [skulk-milestones.md](roadmap/skulk-milestones.md) |
