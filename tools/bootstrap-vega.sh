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

if [[ ! -f "$target/package.json" ]]; then
  if [[ -e "$target" ]]; then
    echo "$target already exists but is not a generated Vega project." >&2
    exit 1
  fi

  vega project generate \
    --template helloWorld \
    --name kinetiqv \
    --packageId com.riippex.kinetiqv.vega \
    --outputDir "$target"
fi

cp "$repo_root/platforms/vega/App.tsx" "$target/src/App.tsx"

cd "$target"
vega project install --fix --os-min 1.2 --os-version 1.2
npm install
vega project doctor

echo "Vega project is ready at $target. Run npm run build:app to produce VPKG artifacts."
