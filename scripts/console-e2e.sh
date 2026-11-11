#!/usr/bin/env bash
# End-to-end smoke run of the console against a real, disposable Django + Postgres.
#
# Needs `make test-db` (Postgres on 127.0.0.1:55432), server/.venv and console/node_modules.
# Drops and re-creates the database `console_e2e`, seeds it, creates the owner e2e@carrum.test,
# starts Django on 127.0.0.1:8788 and the built console on 127.0.0.1:3100, then runs Playwright.
# LiveKit and the agent simulator are deliberately not running: the run checks the console copes.
#
# E2E_PASSWORD sets the owner's password; by default a random one is generated (never stored).
# Extra arguments go to `playwright test`, e.g. scripts/console-e2e.sh --grep Knowledge
set -euo pipefail
cd "$(dirname "$0")/.."
root=$(pwd)

PG_CONTAINER=dialtone-test-pg
DJANGO_PORT=8788
CONSOLE_PORT=3100
DIST_DIR=.next/e2e   # inside console/; keeps the normal .next build untouched
log_dir="$root/console/test-results/servers"

docker ps --filter "name=^${PG_CONTAINER}$" --format '{{.Names}}' | grep -q . \
  || { echo "Postgres for tests is not running; run: make test-db" >&2; exit 1; }
[[ -x server/.venv/bin/python ]] || { echo "server/.venv missing" >&2; exit 1; }
[[ -d console/node_modules ]] || { echo "console/node_modules missing; run: cd console && npm ci" >&2; exit 1; }
for port in $DJANGO_PORT $CONSOLE_PORT; do
  if curl -s -o /dev/null --max-time 1 "http://127.0.0.1:${port}/"; then
    echo "Something is already listening on 127.0.0.1:${port}; stop it first." >&2
    exit 1
  fi
done

if [[ -z "${E2E_PASSWORD:-}" ]]; then
  E2E_PASSWORD="e2e-$(openssl rand -hex 12)"
fi
export E2E_PASSWORD E2E_EMAIL=e2e@carrum.test

# Harmless local values only. LiveKit and the simulator point at closed ports so calls fail fast.
export DJANGO_SECRET_KEY="console-e2e-not-a-secret" DJANGO_DEBUG=false
export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432 POSTGRES_DB=console_e2e
export POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres DASHBOARD_PORT=$DJANGO_PORT
export LIVEKIT_URL=http://127.0.0.1:9 LIVEKIT_API_KEY=e2e-key LIVEKIT_API_SECRET=e2e-secret-not-real
export AGENT_SIM_URL=http://127.0.0.1:9
export DASHBOARD_DB_DIR="$root/console/test-results/dashboard-data"
export CSRF_EXTRA_TRUSTED_ORIGINS="http://127.0.0.1:${CONSOLE_PORT},http://localhost:${CONSOLE_PORT}"

pids=()
backup=""
cleanup() {
  # `next build` rewrites these to point at its distDir; put them back even if the build is interrupted.
  if [[ -n "$backup" && -d "$backup" ]]; then
    cp "$backup/tsconfig.json" "$backup/next-env.d.ts" "$root/console/"
    rm -rf "$backup"
  fi
  for pid in "${pids[@]:-}"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait_for() {  # wait_for URL NAME LOG
  for ((i = 0; i < 60; i++)); do
    curl -s -o /dev/null --max-time 2 "$1" && return 0
    sleep 1
  done
  echo "$2 did not answer on $1 in 60s; last log lines:" >&2
  tail -40 "$3" >&2
  exit 1
}

mkdir -p "$log_dir" "$DASHBOARD_DB_DIR"

echo "Re-creating database console_e2e..."
docker exec "$PG_CONTAINER" psql -U postgres -q -c "DROP DATABASE IF EXISTS console_e2e WITH (FORCE);"
docker exec "$PG_CONTAINER" psql -U postgres -q -c "CREATE DATABASE console_e2e;"

cd "$root/server"
.venv/bin/python manage.py migrate --noinput >"$log_dir/migrate.log"
.venv/bin/python manage.py seed_carrum --knowledge "$root/console/e2e/fixtures/knowledge.md"
.venv/bin/python manage.py shell -c '
import os
from django.contrib.auth import get_user_model
from voiceagents.models import Agent
from voiceagents.publish import publish
from workspaces.models import Membership, UserPreference, Workspace
email = os.environ["E2E_EMAIL"]
user = get_user_model().objects.create_user(username=email, email=email, first_name="E2E Owner",
                                            password=os.environ["E2E_PASSWORD"])
Membership.objects.create(user=user, workspace=Workspace.objects.get(slug="carrum"), role=Membership.OWNER)
UserPreference.objects.get_or_create(user=user)
publish(Agent.objects.get(name="Driver lead qualifier"), user)  # the seed leaves it a draft
print(f"Created {email} as owner; published the seeded agent.")
'

echo "Starting Django on 127.0.0.1:${DJANGO_PORT}..."
.venv/bin/uvicorn config.asgi:application --host 127.0.0.1 --port "$DJANGO_PORT" >"$log_dir/django.log" 2>&1 &
pids+=($!)
wait_for "http://127.0.0.1:${DJANGO_PORT}/api/auth/csrf" Django "$log_dir/django.log"

cd "$root/console"
echo "Building the console against Django on :${DJANGO_PORT}..."
# `next build` rewrites tsconfig.json and next-env.d.ts to point at its distDir; the EXIT trap restores them.
backup=$(mktemp -d)
cp tsconfig.json next-env.d.ts "$backup/"
NEXT_DIST_DIR=$DIST_DIR DJANGO_URL="http://127.0.0.1:${DJANGO_PORT}" npx next build >"$log_dir/next-build.log" 2>&1 \
  || { tail -40 "$log_dir/next-build.log" >&2; exit 1; }
# The standalone server serves static files and public/ from next to itself.
standalone="$DIST_DIR/standalone"
rm -rf "$standalone/$DIST_DIR/static" "$standalone/public"
mkdir -p "$standalone/$DIST_DIR"
cp -R "$DIST_DIR/static" "$standalone/$DIST_DIR/static"
cp -R public "$standalone/public"
# console/package.json says "type": "module" and the standalone server.js is CommonJS.
cp "$standalone/server.js" "$standalone/server.cjs"

echo "Starting the console on 127.0.0.1:${CONSOLE_PORT}..."
PORT=$CONSOLE_PORT HOSTNAME=127.0.0.1 NODE_ENV=production node "$standalone/server.cjs" >"$log_dir/next.log" 2>&1 &
pids+=($!)
wait_for "http://127.0.0.1:${CONSOLE_PORT}/sign-in" Console "$log_dir/next.log"

# localhost, not 127.0.0.1: Next rewrites 127.0.0.1 to localhost in middleware redirects (NextURL), and
# people reach the console as http://localhost:3000 through the tunnel anyway.
E2E_BASE_URL="http://localhost:${CONSOLE_PORT}" npx playwright test "$@"
