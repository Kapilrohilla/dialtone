#!/usr/bin/env bash
# One-off, on the VM (from ~/ai-calling): move the dashboard's call history from
# /data/dashboard.sqlite3 into PostgreSQL. The SQLite file is only read; it stays
# in the dashboard-data volume as a backup and this script never deletes it.
# Needs POSTGRES_PASSWORD in .env (run scripts/init.sh first).
set -euo pipefail
cd "$(dirname "$0")/.."

SQLITE_PATH=${SQLITE_PATH:-/data/dashboard.sqlite3}
run() { docker compose run --rm --no-deps dashboard "$@"; }

docker compose up -d postgres
echo "waiting for postgres..."
until [[ $(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q postgres)") == healthy ]]; do sleep 2; done

run python manage.py migrate --noinput
# Optional verification tool: deploys copy automatically at dashboard start. This refuses if
# PostgreSQL already has calls (it never overwrites unless you add --force yourself).
run python manage.py copy_from_sqlite --path "$SQLITE_PATH" ${COPY_ARGS:-}

echo
echo "SQLite side (opened read-only, $SQLITE_PATH):"
docker compose run --rm --no-deps -T dashboard python - "$SQLITE_PATH" <<'PY'
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
for t in ("calls_call", "calls_callreport", "calls_turnlabel", "auth_user"):
    print(f"  {t}: {c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
PY
echo "PostgreSQL side:"
run python manage.py shell -c "
from django.contrib.auth.models import User
from calls.models import Call, CallReport, TurnLabel
for m in (Call, CallReport, TurnLabel, User):
    print(f'  {m._meta.db_table}: {m.objects.count()}')
"
echo
echo "Done. $SQLITE_PATH was only read and is still in place as a backup. (Run with COPY_ARGS=--dry-run to check without writing.)"
