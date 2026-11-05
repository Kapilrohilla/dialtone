#!/usr/bin/env bash
# Run on the server from the repo root after `docker compose up -d` (deploy.sh does). Waits up to
# WAIT_SECS (default 60) for the dashboard to answer HTTP, so a crash loop (e.g. copy_from_sqlite
# failing at startup) fails the deploy instead of being reported as "deployed".
#
# Usage: scripts/wait-dashboard.sh [SINCE]   (SINCE: timestamp for `docker compose logs --since`)
set -uo pipefail
cd "$(dirname "$0")/.."

since=${1:-}
timeout=${WAIT_SECS:-60}
port=$(grep -E '^DASHBOARD_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2-)
port=${DASHBOARD_PORT:-${port:-8787}}
url="http://127.0.0.1:${port}/admin/login/"
logs() { docker compose logs --no-log-prefix ${since:+--since "$since"} "$@" dashboard 2>&1; }

echo "Waiting for the dashboard on ${url}..."
for ((waited = 0; waited <= timeout; waited += 2)); do
  if curl -fsS -o /dev/null --max-time 2 "$url" 2>/dev/null; then
    echo 'dashboard answering'
    # copy_from_sqlite's summary: counts, "already copied", or the skip warning.
    logs | grep -E '^(groups|users|calls|reports|turn labels|calls assigned to a workspace): [0-9]+$|already copied|WARNING' || true
    exit 0
  fi
  sleep 2
done
echo "dashboard did not answer in ${timeout}s; last 50 log lines:"
logs --tail 50
echo 'rollback: ROLLBACK=1 make deploy'
exit 1
