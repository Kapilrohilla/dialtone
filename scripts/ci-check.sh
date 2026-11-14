#!/usr/bin/env bash
# CI gate: the unit tests (agent, server, console tests + typecheck + lint), the shell script tests and a
# production console build. Needs agent/.venv and server/.venv with requirements-dev.txt installed.
set -euo pipefail
cd "$(dirname "$0")/.."

make test
# Default .next dir: a custom distDir makes `next build` rewrite the tracked tsconfig.json.
# Up to 3 tries: next/font/google downloads fonts during the build and now and then fails on Google's reply.
(cd console && { npm run build || npm run build || npm run build; })
echo "ci-check: all passed"
