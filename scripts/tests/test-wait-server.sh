#!/usr/bin/env bash
# deploy/wait-server.sh with stubbed curl/docker/sleep: prints the copy summary on success; on a server that
# never answers (crash loop) prints the logs and the rollback command and exits non-zero.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/deploy" "$tmp/bin" && cp "$root/deploy/wait-server.sh" "$tmp/deploy/"
printf 'DASHBOARD_PORT=9999\n' > "$tmp/.env"

cat > "$tmp/bin/curl" <<'STUB'
#!/usr/bin/env bash
echo "$@" >> "$STUB_DIR/curl.args"
n=$(( $(cat "$STUB_DIR/curl.n" 2>/dev/null || echo 0) + 1 )); echo $n > "$STUB_DIR/curl.n"
[[ "$CURL_OK_AFTER" != never && $n -ge $CURL_OK_AFTER ]]
STUB
cat > "$tmp/bin/docker" <<'STUB'
#!/usr/bin/env bash
printf 'Operations to perform:\ncalls: 12\nreports: 3\ncalls assigned to a workspace: 12\nWARNING: SQLite history not copied (PostgreSQL already has calls)\nTraceback (most recent call last):\nINFO: Uvicorn running\n'
STUB
printf '#!/bin/sh\ntrue\n' > "$tmp/bin/sleep"
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:$PATH" STUB_DIR="$tmp"
fail() { echo "FAIL: $1"; echo "$out"; exit 1; }

export CURL_OK_AFTER=3
out=$("$tmp/deploy/wait-server.sh" 2>&1) || fail "success case exited non-zero"
grep -q '127.0.0.1:9999/admin/login/' "$tmp/curl.args" || fail "did not poll DASHBOARD_PORT from .env"
grep -qx 'calls: 12' <<<"$out" || fail "copy counts not printed"
grep -qx 'calls assigned to a workspace: 12' <<<"$out" || fail "assigned count not printed"
grep -q '^WARNING' <<<"$out" || fail "WARNING line not printed"
grep -q 'Uvicorn' <<<"$out" && fail "printed unrelated log lines on success"

rm -f "$tmp/curl.n"
export CURL_OK_AFTER=never
if out=$("$tmp/deploy/wait-server.sh" 2>&1); then fail "crash loop reported as success"; fi
grep -q 'Traceback' <<<"$out" || fail "server logs not printed on failure"
grep -q 'ROLLBACK=1 make deploy' <<<"$out" || fail "rollback command not printed"
[[ $(cat "$tmp/curl.n") -le 31 ]] || fail "waited longer than 60s worth of polls"
echo "wait-server.sh: ok"
