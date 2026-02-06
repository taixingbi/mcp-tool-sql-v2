#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=".env"
APP_PREFIX="mcp-tool-sql-v2"

usage() {
  echo "Usage: $0 <env>"
  echo "  env: dev | qa | prod"
  echo ""
  echo "Example: $0 dev   # syncs .env to mcp-tool-sql-v2-dev"
  exit 1
}

if [[ $# -lt 1 ]]; then
  usage
fi

ENV="$1"
case "$ENV" in
  dev|qa|prod) ;;
  *) echo "❌ Invalid env: $ENV (use dev, qa, or prod)" && usage ;;
esac

APP_NAME="${APP_PREFIX}-${ENV}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "❌ $ENV_FILE not found"
  exit 1
fi

echo "🔐 Loading secrets from $ENV_FILE → Fly app: $APP_NAME"

# Build secrets and run flyctl secrets set (so we can print the command)
args=()
while IFS= read -r line; do
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
  key="${line%%=*}"
  value="${line#*=}"
  key="$(echo "$key" | xargs)"
  [[ -z "$key" ]] && continue
  args+=("$key=$value")
done < "$ENV_FILE"

# Print command (values visible for verification)
echo "   flyctl secrets set -a $APP_NAME \\"
for i in "${!args[@]}"; do
  [[ $i -eq $((${#args[@]} - 1)) ]] && echo "     ${args[$i]}" || echo "     ${args[$i]} \\"
done

flyctl secrets set -a "$APP_NAME" "${args[@]}"

echo "✅ All secrets synced to $APP_NAME"
