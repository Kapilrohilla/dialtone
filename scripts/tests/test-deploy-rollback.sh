#!/usr/bin/env bash
# deploy.sh ROLLBACK=1 with stubbed gcloud/docker (the "VM" is a temp HOME): brings agent-sim up only
# when the rolled-back compose defines it, and removes an orphaned agent-sim container otherwise.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"

cat > "$tmp/bin/gcloud" <<'STUB'
#!/usr/bin/env bash
# gcloud compute ssh ... --command SCRIPT: run SCRIPT here.
while [[ $# -gt 0 ]]; do [[ "$1" == --command ]] && exec bash -c "$2"; shift; done
exit 1
STUB
cat > "$tmp/bin/docker" <<'STUB'
#!/usr/bin/env bash
echo "docker $*" >> "$STUB_DIR/docker.log"
if [[ "$*" == "compose --profile agent config --services" ]]; then printf '%s\n' $SERVICES; exit 0; fi
if [[ "$*" == *agent-sim* && " $SERVICES " != *" agent-sim "* ]]; then echo "no such service: agent-sim" >&2; exit 1; fi
exit 0
STUB
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:$PATH" STUB_DIR="$tmp" HOME="$tmp/home"
fail() { echo "FAIL: $1"; echo "$out"; cat "$tmp/docker.log" 2>/dev/null; exit 1; }
setup() { rm -rf "$HOME" "$tmp/docker.log"; mkdir -p "$HOME/ai-calling" "$HOME/ai-calling.prev"
  echo new > "$HOME/ai-calling/DEPLOYED_COMMIT"; echo old > "$HOME/ai-calling.prev/DEPLOYED_COMMIT"; }

# Rolling back to a tree without agent-sim (e.g. main before the simulator).
setup
export SERVICES="redis dashboard agent"
out=$(ROLLBACK=1 "$root/scripts/deploy.sh" 2>&1) || fail "rollback without agent-sim exited non-zero"
grep -q 'now running: old' <<<"$out" || fail "did not swap to the previous deploy"
grep -q -- '--profile agent up -d --build --remove-orphans agent$' "$tmp/docker.log" || fail "orphaned agent-sim not removed"

# Rolling back to a tree that has agent-sim.
setup
export SERVICES="redis dashboard agent agent-sim"
out=$(ROLLBACK=1 "$root/scripts/deploy.sh" 2>&1) || fail "rollback with agent-sim exited non-zero"
grep -q -- '--profile agent up -d --build agent agent-sim$' "$tmp/docker.log" || fail "agent-sim not brought up"
echo "deploy.sh rollback: ok"
