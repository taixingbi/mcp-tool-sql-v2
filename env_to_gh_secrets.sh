#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=".env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "❌ $ENV_FILE not found"
  exit 1
fi

echo "🔐 Loading secrets from $ENV_FILE"

while IFS='=' read -r key value; do
  # skip empty lines and comments
  [[ -z "$key" || "$key" =~ ^# ]] && continue

  # trim whitespace
  key="$(echo "$key" | xargs)"
  value="$(echo "$value" | xargs)"

  if [[ -z "$key" || -z "$value" ]]; then
    continue
  fi

  echo "➡️  Setting GitHub secret: $key"
  gh secret set "$key" --body "$value"

done < "$ENV_FILE"

echo "✅ All secrets uploaded to GitHub"
