#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="$repo_root/apps/vega"

command -v vega >/dev/null 2>&1 || {
  echo "Vega CLI is required. Install Vega SDK 0.24 on Ubuntu before running this script." >&2
  exit 1
}

command -v npm >/dev/null 2>&1 || {
  echo "npm is required." >&2
  exit 1
}

command -v node >/dev/null 2>&1 || {
  echo "Node.js is required." >&2
  exit 1
}

node_major="$(node --version | sed -E 's/^v([0-9]+).*/\1/')"
if [[ ! "$node_major" =~ ^[0-9]+$ ]] || ((node_major < 18)); then
  echo "Vega SDK 0.24 requires Node.js 18 or later." >&2
  exit 1
fi

[[ -f "$target/package.json" && -f "$target/manifest.toml" ]] || {
  echo "$target is missing. Restore the versioned Vega application from Git." >&2
  exit 1
}

cd "$target"
npm ci
vega project doctor

echo "Vega project is ready at $target. Run npm run build:app to produce VPKG artifacts."
