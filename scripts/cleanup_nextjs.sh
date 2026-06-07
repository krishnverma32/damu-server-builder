#!/usr/bin/env bash
set -euo pipefail

files=(
  "next-env.d.ts"
  "next.config.ts"
  "eslint.config.mjs"
  "package.json"
  "package-lock.json"
  "postcss.config.js"
  "tailwind.config.ts"
  "tsconfig.json"
)

dirs=(
  "src/app"
)

for file in "${files[@]}"; do
  if [ -f "$file" ]; then
    rm "$file"
    echo "deleted $file"
  fi
done

for dir in "${dirs[@]}"; do
  if [ -d "$dir" ]; then
    rm -rf "$dir"
    echo "deleted $dir"
  fi
done
