#!/usr/bin/env bash
# init.sh on an older .env: adds DJANGO_SECRET_KEY without corrupting the last line, keeps values, re-runs cleanly.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/scripts" && cp "$root/scripts/init.sh" "$tmp/scripts/" && cp "$root/.env.example" "$tmp/"

# An older .env: no DJANGO_SECRET_KEY line, and no newline after the last value.
printf 'LIVEKIT_API_KEY=APIkeep\nLIVEKIT_API_SECRET=secretkeep\nTTS_SPEAKER=priya' > "$tmp/.env"
"$tmp/scripts/init.sh" >/dev/null

fail() { echo "FAIL: $1"; cat "$tmp/.env"; exit 1; }
grep -qx 'TTS_SPEAKER=priya' "$tmp/.env" || fail "last line corrupted"
grep -qx 'LIVEKIT_API_KEY=APIkeep' "$tmp/.env" || fail "existing key overwritten"
key=$(grep -E '^DJANGO_SECRET_KEY=' "$tmp/.env" | cut -d= -f2-)
[[ ${#key} -ge 40 ]] || fail "DJANGO_SECRET_KEY not generated"
pgpw=$(grep -E '^POSTGRES_PASSWORD=' "$tmp/.env" | cut -d= -f2-)
[[ ${#pgpw} -ge 24 ]] || fail "POSTGRES_PASSWORD not generated"
grep -qx 'POSTGRES_DB=dashboard' "$tmp/.env" || fail "POSTGRES_DB not added"
grep -qx 'DASHBOARD_URL=http://127.0.0.1:8787' "$tmp/.env" || fail "DASHBOARD_URL not added"
grep -qx 'RECORDING_ENABLED=false' "$tmp/.env" || fail "RECORDING_ENABLED not added"

"$tmp/scripts/init.sh" >/dev/null
[[ $(grep -E '^POSTGRES_PASSWORD=' "$tmp/.env" | cut -d= -f2-) == "$pgpw" ]] || fail "re-run changed the postgres password"
[[ $(grep -c '^DJANGO_SECRET_KEY=' "$tmp/.env") == 1 ]] || fail "re-run duplicated the key"
[[ $(grep -E '^DJANGO_SECRET_KEY=' "$tmp/.env" | cut -d= -f2-) == "$key" ]] || fail "re-run changed the key"

# Existing values are kept, not reset to the defaults.
printf 'DASHBOARD_URL=http://10.0.0.5:8787\nRECORDING_ENABLED=true\n' >> "$tmp/.env"
sed -i.bak '/^DASHBOARD_URL=http:\/\/127/d;/^RECORDING_ENABLED=false/d' "$tmp/.env" && rm -f "$tmp/.env.bak"
"$tmp/scripts/init.sh" >/dev/null
grep -qx 'DASHBOARD_URL=http://10.0.0.5:8787' "$tmp/.env" || fail "DASHBOARD_URL overwritten"
grep -qx 'RECORDING_ENABLED=true' "$tmp/.env" || fail "RECORDING_ENABLED overwritten"
[[ $(grep -c '^DASHBOARD_URL=' "$tmp/.env") == 1 ]] || fail "DASHBOARD_URL duplicated"
[[ $(grep -c '^RECORDING_ENABLED=' "$tmp/.env") == 1 ]] || fail "RECORDING_ENABLED duplicated"
echo "init.sh: ok"
