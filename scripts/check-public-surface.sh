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
