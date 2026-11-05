#!/usr/bin/env bash
# One-off, on the VM (from ~/ai-calling): move the dashboard's call history from
# /data/dashboard.sqlite3 into PostgreSQL. The SQLite file is only read; it stays
# in the dashboard-data volume as a backup and this script never deletes it.
# If /data/.copied-to-postgres exists (the automatic cutover already ran) it only
# prints counts from both sides; a real copy made here writes that marker.
# Needs POSTGRES_PASSWORD in .env (run scripts/init.sh first).
set -euo pipefail
cd "$(dirname "$0")/.."

SQLITE_PATH=${SQLITE_PATH:-/data/dashboard.sqlite3}
run() { docker compose run --rm --no-deps dashboard "$@"; }

docker compose up -d postgres
echo "waiting for postgres..."
until [[ $(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q postgres)") == healthy ]]; do sleep 2; done

MARKER="$(dirname "$SQLITE_PATH")/.copied-to-postgres"

counts() {
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
}

run python manage.py migrate --noinput

# Deploys copy automatically at dashboard start and then write the marker; after that, only compare.
if run test -e "$MARKER"; then
  echo "$MARKER exists: the history was already copied. Counts only:"
  counts
  exit 0
fi

# This refuses if PostgreSQL already has calls (it never overwrites unless you add --force yourself).
run python manage.py copy_from_sqlite --path "$SQLITE_PATH" ${COPY_ARGS:-}
if [[ " ${COPY_ARGS:-} " != *" --dry-run "* ]]; then
  # Same marker the startup copy writes, so the dashboard does not try again.
  run sh -c 'echo "copied by migrate-dashboard-to-postgres.sh" > "$1"' sh "$MARKER"
fi

echo
counts
echo
echo "Done. $SQLITE_PATH was only read and is still in place as a backup. (Run with COPY_ARGS=--dry-run to check without writing.)"
