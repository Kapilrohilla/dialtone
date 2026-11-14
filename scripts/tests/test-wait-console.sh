#!/usr/bin/env bash
# deploy/wait-console.sh against a console that hangs every request (curl takes its full 2 s): gives up after about
# WAIT_SECS of wall-clock time, not after WAIT_SECS/2 polls of 4 s each. Uses the real sleep.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/deploy" "$tmp/bin" && cp "$root/deploy/wait-console.sh" "$tmp/deploy/"
printf '#!/bin/sh\nsleep 2\nexit 28\n' > "$tmp/bin/curl"
printf '#!/bin/sh\necho "console log line"\n' > "$tmp/bin/docker"
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:$PATH"
fail() { echo "FAIL: $1"; echo "$out"; exit 1; }

start=$SECONDS
if out=$(WAIT_SECS=6 "$tmp/deploy/wait-console.sh" 2>&1); then fail "a hanging console reported as answering"; fi
took=$((SECONDS - start))
grep -q 'console did not answer in 6s' <<<"$out" || fail "timeout not reported"
((took <= 9)) || fail "waited ${took}s for WAIT_SECS=6"
echo "wait-console.sh: ok (gave up after ${took}s)"
