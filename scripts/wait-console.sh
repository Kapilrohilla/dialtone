#!/usr/bin/env bash
# Run on the server from the repo root after `docker compose up -d` (deploy.sh does). Waits up to
# WAIT_SECS (default 60) for the console's sign-in page on 127.0.0.1:3000, so a console that crashes
# at startup fails the deploy instead of being reported as "deployed".
#
# Usage: scripts/wait-console.sh [SINCE]   (SINCE: timestamp for `docker compose logs --since`)
set -uo pipefail
cd "$(dirname "$0")/.."

since=${1:-}
timeout=${WAIT_SECS:-60}
url="http://127.0.0.1:3000/sign-in"

echo "Waiting for the console on ${url}..."
for ((waited = 0; waited <= timeout; waited += 2)); do
  if curl -fsS -o /dev/null --max-time 2 "$url" 2>/dev/null; then
    echo 'console answering'
    exit 0
  fi
  sleep 2
done
echo "console did not answer in ${timeout}s; last 50 log lines:"
docker compose logs --no-log-prefix ${since:+--since "$since"} --tail 50 console 2>&1
echo 'rollback: ROLLBACK=1 make deploy'
exit 1
