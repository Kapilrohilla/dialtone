#!/usr/bin/env bash
# The gate Cyrus must pass before merging its PR into `dev` (dev auto-deploys to the live VM).
# Runs the unit tests (agent, dashboard, console tests + typecheck + lint) and a production console build.
# Needs agent/.venv and dashboard/.venv (cyrus-setup.sh links them in Cyrus worktrees).
set -euo pipefail
cd "$(dirname "$0")/.."

make test
# Default .next dir: a custom distDir makes `next build` rewrite the tracked tsconfig.json.
(cd console && npm run build)
echo "ci-check: all passed"
