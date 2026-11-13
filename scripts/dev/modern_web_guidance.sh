#!/usr/bin/env bash
# Development-only queries. Keep the version explicit; review upgrades before use.
set -euo pipefail

case "${1:-}" in
  search | retrieve | list | --help | -h | --version | -v) ;;
  *)
    echo 'usage: modern_web_guidance.sh {search <query>|retrieve <ids>|list|--help|--version}' >&2
    exit 2
    ;;
esac

# Always use the repository's .mwgrc, including when called from a subdirectory.
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
export DISABLE_TELEMETRY=1
cli=ci/modern-web-guidance/node_modules/modern-web-guidance/skills/modern-web-guidance/modern-web.mjs
if [ ! -f "$cli" ]; then
  echo 'Install the locked CLI first: DISABLE_TELEMETRY=1 npm ci --ignore-scripts --prefix ci/modern-web-guidance' >&2
  exit 2
fi
exec node "$cli" "$@"
