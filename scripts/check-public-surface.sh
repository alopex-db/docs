#!/usr/bin/env bash

set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
guide="$root/guides/v0.7-surfaces.md"

required=(
  '/api/admin/status'
  '/api/admin/cluster/join'
  'alopex server status'
  '[cluster]'
  'DataFrame::explode()'
  'DataFrame::implode()'
  'v1.0以降'
)

for needle in "${required[@]}"; do
  if ! grep -Fq "$needle" "$guide"; then
    printf 'public surface check failed: missing %s in %s\n' "$needle" "$guide" >&2
    exit 1
  fi
done

test -f "$root/reports/vector-benchmarks/README.md"
python3 - "$root/reports/vector-benchmarks" <<'PY'
import hashlib
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
for data_path in root.glob("v*.json"):
    markdown_path = data_path.with_suffix(".md")
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    if payload.get("schema") != "alopex.hnsw-diagnostic/v3":
        raise SystemExit(f"unexpected benchmark schema: {data_path}")
    if str(payload.get("release_version")) != data_path.stem.removeprefix("v"):
        raise SystemExit(f"benchmark version/path mismatch: {data_path}")
    digest = hashlib.sha256(markdown_path.read_bytes()).hexdigest()
    if digest != payload.get("markdown_sha256"):
        raise SystemExit(f"benchmark Markdown hash mismatch: {markdown_path}")
PY

# These were historical claims that must not return to the public roadmap.
if grep -RnE 'v0\.7\.0[[:space:]]*\|[[:space:]]*WASM|WASM[^[:cntrl:]]*v0\.7\.0' \
  "$root/roadmap" "$root/specs/alopex-sql-dialect-spec.md"; then
  echo 'public surface check failed: WASM is assigned to v0.7.0' >&2
  exit 1
fi

if grep -RnE 'alopex-dataframe[^[:cntrl:]]*v0\.4\.0[^[:cntrl:]]*(Planned|Coming|planned|coming)' \
  "$root/roadmap" "$root/concepts" "$root/specs"; then
  echo 'public surface check failed: DataFrame P3 is described as a v0.4.0 future feature' >&2
  exit 1
fi

echo 'public surface check: PASS'
