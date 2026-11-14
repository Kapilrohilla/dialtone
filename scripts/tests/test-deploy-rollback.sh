#!/usr/bin/env bash
# deploy/deploy.sh with stubbed gcloud/docker/curl (the "VM" is a temp HOME).
# Rollback: builds only the services the rolled-back tree defines (old or new names, compose file at the root
# or in deploy/) and removes orphaned containers. Deploy: builds one image at a time, stops before swapping directories
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
# Trees with deploy/docker-compose.yml are driven with -f/--env-file; match on the rest of the command.
args=" $* "; args=${args/ -f deploy\/docker-compose.yml --env-file .env / }; args=${args# }; args=${args% }
[[ "$args" == "volume inspect"* ]] && { [[ " ${VOLUMES:-} " == *" $3 "* ]]; exit; }
[[ -n "${BUILD_FAIL:-}" && "$args" == *" build $BUILD_FAIL" ]] && { echo "build of $BUILD_FAIL failed" >&2; exit 1; }
if [[ "$args" == "compose --profile agent config --services" ]]; then printf '%s\n' $SERVICES; exit 0; fi
for svc in ${args//--profile agent/}; do
  case $svc in dashboard|console|agent|agent-sim|dialtone-*)
    [[ " $SERVICES " == *" $svc "* ]] || { echo "no such service: $svc" >&2; exit 1; } ;;
  esac
done
[[ "$args" == "compose logs"*dialtone-agent ]] && echo 'registered worker'
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
export PATH="$tmp/bin:$PATH" STUB_DIR="$tmp" HOME="$tmp/home" GCP_PROJECT=test-project
fail() { echo "FAIL: $1"; echo "$out"; cat "$tmp/docker.log" 2>/dev/null; exit 1; }
d=dialtone
setup() { rm -rf "$HOME" "$tmp/docker.log" "$tmp/curl.log"; mkdir -p "$HOME/$d" "$HOME/$d.prev"
  echo new > "$HOME/$d/DEPLOYED_COMMIT"; echo old > "$HOME/$d.prev/DEPLOYED_COMMIT"; }
OLD="redis dashboard console agent agent-sim"
NEW="redis dialtone-server dialtone-console dialtone-agent dialtone-agent-sim"

# Rolling back to a tree from before the rename (compose file at its root, old service names), without
# agent-sim or console: builds only what it has, with plain `docker compose`, and removes orphans.
setup
export SERVICES="redis dashboard agent"
out=$(ROLLBACK=1 "$root/deploy/deploy.sh" 2>&1) || fail "rollback to an old tree exited non-zero"
grep -q 'now running: old' <<<"$out" || fail "did not swap to the previous deploy"
grep -qx 'docker compose build dashboard' "$tmp/docker.log" || fail "old tree's dashboard not built"
grep -qx 'docker compose --profile agent up -d --build --remove-orphans' "$tmp/docker.log" \
  || fail "old tree not brought up with orphans removed"
grep -q 'console\|dialtone-' "$tmp/docker.log" && fail "rollback named services the old tree does not have"

# Rolling back to a tree with all old services.
setup
export SERVICES="$OLD"
out=$(ROLLBACK=1 "$root/deploy/deploy.sh" 2>&1) || fail "rollback with all old services exited non-zero"
[[ $(grep ' build ' "$tmp/docker.log" | grep -v -- --profile) == $'docker compose build dashboard\ndocker compose build console' ]] \
  || fail "old images not built one at a time"

# Rolling back to a tree with the deploy/ layout and the new service names.
setup
mkdir -p "$HOME/$d.prev/deploy" && touch "$HOME/$d.prev/deploy/docker-compose.yml"
export SERVICES="$NEW"
out=$(ROLLBACK=1 "$root/deploy/deploy.sh" 2>&1) || fail "rollback to a new tree exited non-zero"
dc='docker compose -f deploy/docker-compose.yml --env-file .env'
[[ $(grep ' build ' "$tmp/docker.log" | grep -v -- --profile) == "$dc build dialtone-server"$'\n'"$dc build dialtone-console" ]] \
  || fail "new images not built one at a time"
grep -qx "$dc --profile agent up -d --build --remove-orphans" "$tmp/docker.log" || fail "new tree not brought up"

# Deploying: waits for the console's /sign-in and fails when it never answers.
deploy_setup() { setup; printf 'DJANGO_SECRET_KEY=test-not-a-secret\nPOSTGRES_PASSWORD=x\n' > "$HOME/$d/.env"; }
export SERVICES="$NEW"
deploy_setup
if out=$(FORCE=1 CONSOLE_CURL_EXIT=7 "$root/deploy/deploy.sh" 2>&1); then
  fail "deploy succeeded although the console never answered"
fi
grep -q '127.0.0.1:3000/sign-in' "$tmp/curl.log" || fail "deploy did not poll the console's /sign-in"
grep -q 'console did not answer' <<<"$out" || fail "console failure not reported"
grep -q 'ROLLBACK=1 make deploy' <<<"$out" || fail "rollback command not printed"
grep -q 'logs.*dialtone-console' "$tmp/docker.log" || fail "console logs not printed"
grep -q 'agent registered' <<<"$out" || fail "console failure hid whether the agent registered"
[[ $(grep -c '127.0.0.1:3000/sign-in' "$tmp/curl.log") -le 31 ]] || fail "waited longer than 60s worth of polls"

# Deploying with a console that answers.
deploy_setup
out=$(FORCE=1 CONSOLE_CURL_EXIT=0 "$root/deploy/deploy.sh" 2>&1) || fail "deploy with a healthy console exited non-zero"
grep -q 'console answering' <<<"$out" || fail "console success not reported"
grep -q "deployed $(git -C "$root" rev-parse --short HEAD)" <<<"$out" || fail "deploy did not finish"
builds=$(grep -E 'build dialtone' "$tmp/docker.log" | sed "s|^$dc ||")
[[ "$builds" == $'build dialtone-server\nbuild dialtone-console\n--profile agent build dialtone-agent\n--profile agent build dialtone-agent-sim' ]] \
  || fail "images not built one at a time in order: $builds"
grep -qx "$dc --profile agent up -d --remove-orphans" "$tmp/docker.log" || fail "old-named containers not removed"
grep -q COMPOSE_PROJECT_NAME "$HOME/$d/.env" && fail "pinned the project name on a fresh dialtone install"

# Deploying when a build fails: stops with the reason, the old version keeps running, nothing is swapped.
for broken in dialtone-console dialtone-agent-sim; do
  deploy_setup
  if out=$(FORCE=1 BUILD_FAIL=$broken CONSOLE_CURL_EXIT=0 "$root/deploy/deploy.sh" 2>&1); then
    fail "deploy succeeded although the $broken build failed"
  fi
  grep -q 'build failed; nothing changed, the old version is still running' <<<"$out" || fail "$broken build failure not reported"
  [[ $(cat "$HOME/$d/DEPLOYED_COMMIT") == new && $(cat "$HOME/$d.prev/DEPLOYED_COMMIT") == old ]] \
    || fail "directories swapped after the $broken build failed"
  grep -q 'up -d' "$tmp/docker.log" && fail "containers restarted after the $broken build failed"
done

# A VM set up before the rename (~/ai-calling): the default REMOTE_DIR stops with a hint; REMOTE_DIR=ai-calling
# deploys there and pins COMPOSE_PROJECT_NAME so the existing volumes are kept.
d=ai-calling
deploy_setup
rm -rf "$HOME/dialtone"
if out=$(FORCE=1 CONSOLE_CURL_EXIT=0 "$root/deploy/deploy.sh" 2>&1); then fail "deployed without a .env on the VM"; fi
grep -q 'REMOTE_DIR=ai-calling' <<<"$out" || fail "no REMOTE_DIR hint for a pre-rename VM"
out=$(FORCE=1 CONSOLE_CURL_EXIT=0 REMOTE_DIR=ai-calling VOLUMES=ai-calling_postgres-data "$root/deploy/deploy.sh" 2>&1) \
  || fail "deploy to ~/ai-calling exited non-zero"
grep -qx 'COMPOSE_PROJECT_NAME=ai-calling' "$HOME/ai-calling/.env" || fail "old project name not pinned"
echo "deploy.sh rollback, builds, console wait and pre-rename VMs: ok"
