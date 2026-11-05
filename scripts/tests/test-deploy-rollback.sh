#!/usr/bin/env bash
# deploy.sh with stubbed gcloud/docker/curl (the "VM" is a temp HOME).
# Rollback: brings agent-sim and console up only when the rolled-back compose defines them, and removes
# their orphaned containers otherwise. Deploy: builds one image at a time, stops before swapping directories
# when a build fails, checks the agent before the console, and fails when the console never answers.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"

cat > "$tmp/bin/gcloud" <<'STUB'
#!/usr/bin/env bash
# gcloud compute ssh ... --command SCRIPT: run SCRIPT here. gcloud compute scp SRC VM:DEST: copy into HOME.
if [[ "$1 $2" == "compute scp" ]]; then cp "$3" "$HOME/${4#*:\~/}"; exit 0; fi
while [[ $# -gt 0 ]]; do [[ "$1" == --command ]] && exec bash -c "$2"; shift; done
exit 1
STUB
cat > "$tmp/bin/docker" <<'STUB'
#!/usr/bin/env bash
echo "docker $*" >> "$STUB_DIR/docker.log"
[[ -n "${BUILD_FAIL:-}" && "$*" == *" build $BUILD_FAIL" ]] && { echo "build of $BUILD_FAIL failed" >&2; exit 1; }
if [[ "$*" == "compose --profile agent config --services" ]]; then printf '%s\n' $SERVICES; exit 0; fi
if [[ "$*" == *agent-sim* && " $SERVICES " != *" agent-sim "* ]]; then echo "no such service: agent-sim" >&2; exit 1; fi
if [[ "$*" == *console* && " $SERVICES " != *" console "* ]]; then echo "no such service: console" >&2; exit 1; fi
[[ "$*" == "compose logs"*agent ]] && echo 'registered worker'
exit 0
STUB
cat > "$tmp/bin/curl" <<'STUB'
#!/usr/bin/env bash
echo "curl $*" >> "$STUB_DIR/curl.log"
[[ "$*" == *127.0.0.1:3000/* ]] && exit "${CONSOLE_CURL_EXIT:-7}"
exit 0
STUB
printf '#!/bin/sh\ntrue\n' > "$tmp/bin/sleep"
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:$PATH" STUB_DIR="$tmp" HOME="$tmp/home"
fail() { echo "FAIL: $1"; echo "$out"; cat "$tmp/docker.log" 2>/dev/null; exit 1; }
setup() { rm -rf "$HOME" "$tmp/docker.log" "$tmp/curl.log"; mkdir -p "$HOME/ai-calling" "$HOME/ai-calling.prev"
  echo new > "$HOME/ai-calling/DEPLOYED_COMMIT"; echo old > "$HOME/ai-calling.prev/DEPLOYED_COMMIT"; }

# Rolling back to a tree without agent-sim or console (e.g. main before the simulator).
setup
export SERVICES="redis dashboard agent"
out=$(ROLLBACK=1 "$root/scripts/deploy.sh" 2>&1) || fail "rollback without agent-sim exited non-zero"
grep -q 'now running: old' <<<"$out" || fail "did not swap to the previous deploy"
grep -q -- '--profile agent up -d --build --remove-orphans agent$' "$tmp/docker.log" || fail "orphaned agent-sim not removed"

# Rolling back to a tree with agent-sim but no console (plan 2): skips console and removes its container.
setup
export SERVICES="redis dashboard agent agent-sim"
out=$(ROLLBACK=1 "$root/scripts/deploy.sh" 2>&1) || fail "rollback without console exited non-zero"
grep -q -- '--profile agent up -d --build --remove-orphans agent agent-sim$' "$tmp/docker.log" \
  || fail "agent-sim not brought up, or orphaned console not removed"
grep -q console "$tmp/docker.log" && fail "rollback named the console service the old tree does not have"

# Rolling back to a tree that has agent-sim and console: nothing is orphaned.
setup
export SERVICES="redis dashboard console agent agent-sim"
out=$(ROLLBACK=1 "$root/scripts/deploy.sh" 2>&1) || fail "rollback with agent-sim exited non-zero"
grep -q -- '--profile agent up -d --build agent agent-sim$' "$tmp/docker.log" || fail "agent-sim not brought up"

# Deploying: waits for the console's /sign-in and fails when it never answers.
deploy_setup() { setup; printf 'DJANGO_SECRET_KEY=test-not-a-secret\nPOSTGRES_PASSWORD=x\n' > "$HOME/ai-calling/.env"; }
export SERVICES="redis dashboard console agent agent-sim"
deploy_setup
if out=$(FORCE=1 CONSOLE_CURL_EXIT=7 "$root/scripts/deploy.sh" 2>&1); then
  fail "deploy succeeded although the console never answered"
fi
grep -q '127.0.0.1:3000/sign-in' "$tmp/curl.log" || fail "deploy did not poll the console's /sign-in"
grep -q 'console did not answer' <<<"$out" || fail "console failure not reported"
grep -q 'ROLLBACK=1 make deploy' <<<"$out" || fail "rollback command not printed"
grep -q 'compose logs.*console' "$tmp/docker.log" || fail "console logs not printed"
grep -q 'agent registered' <<<"$out" || fail "console failure hid whether the agent registered"
[[ $(grep -c '127.0.0.1:3000/sign-in' "$tmp/curl.log") -le 31 ]] || fail "waited longer than 60s worth of polls"

# Deploying with a console that answers.
deploy_setup
out=$(FORCE=1 CONSOLE_CURL_EXIT=0 "$root/scripts/deploy.sh" 2>&1) || fail "deploy with a healthy console exited non-zero"
grep -q 'console answering' <<<"$out" || fail "console success not reported"
grep -q "deployed $(git -C "$root" rev-parse --short HEAD)" <<<"$out" || fail "deploy did not finish"
builds=$(grep -E 'compose (--profile agent )?build' "$tmp/docker.log" | sed 's/^docker //')
[[ "$builds" == $'compose build dashboard\ncompose build console\ncompose --profile agent build agent\ncompose --profile agent build agent-sim' ]] \
  || fail "images not built one at a time in order: $builds"

# Deploying when a build fails: stops with the reason, the old version keeps running, nothing is swapped.
for broken in console agent-sim; do
  deploy_setup
  if out=$(FORCE=1 BUILD_FAIL=$broken CONSOLE_CURL_EXIT=0 "$root/scripts/deploy.sh" 2>&1); then
    fail "deploy succeeded although the $broken build failed"
  fi
  grep -q 'build failed; nothing changed, the old version is still running' <<<"$out" || fail "$broken build failure not reported"
  [[ $(cat "$HOME/ai-calling/DEPLOYED_COMMIT") == new && $(cat "$HOME/ai-calling.prev/DEPLOYED_COMMIT") == old ]] \
    || fail "directories swapped after the $broken build failed"
  grep -q 'up -d' "$tmp/docker.log" && fail "containers restarted after the $broken build failed"
done
echo "deploy.sh rollback, builds and console wait: ok"
