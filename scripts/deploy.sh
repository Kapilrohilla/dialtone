#!/usr/bin/env bash
# Deploys the committed code (HEAD) from your laptop to the VM and restarts what changed.
#
# Usage: scripts/deploy.sh            (or: make deploy)
#   FORCE=1     deploy even with uncommitted changes or calls in progress
#   ROLLBACK=1  swap back to the previously deployed version
#
# The VM keeps its own .env (keys, SIP config) and Docker volumes (Redis, call
# history); only code is replaced. The previous code stays in ~/ai-calling.prev.
set -euo pipefail
cd "$(dirname "$0")/.."

VM=${VM:-ai-calling}
GCP_PROJECT=${GCP_PROJECT:-carrum-agent-pilot-dev}
GCP_ZONE=${GCP_ZONE:-asia-south1-c}
ssh_vm() { gcloud compute ssh "$VM" --project "$GCP_PROJECT" --zone "$GCP_ZONE" --quiet --command "$1"; }

if [[ "${ROLLBACK:-}" == 1 ]]; then
  echo "Rolling back to the previous deploy..."
  # One command per line: set -e does not stop on a failure inside an && list.
  ssh_vm 'set -e; [ -d ~/ai-calling.prev ] || { echo "no previous deploy to roll back to"; exit 1; }
    mv ~/ai-calling ~/ai-calling.rollback-tmp
    mv ~/ai-calling.prev ~/ai-calling
    mv ~/ai-calling.rollback-tmp ~/ai-calling.prev
    cd ~/ai-calling
    # Older trees have no agent-sim and/or console service: start only what this tree has, and remove
    # the orphaned containers of the rest.
    services=$(docker compose --profile agent config --services)
    # One image at a time: parallel builds can run the 4 GB VM out of memory next to live calls.
    for s in dashboard console; do echo "$services" | grep -qx $s && docker compose build $s; done
    docker compose up -d --build   # also starts console when this tree defines it
    sim=; echo "$services" | grep -qx agent-sim && sim=agent-sim
    orphans=--remove-orphans
    [ -n "$sim" ] && echo "$services" | grep -qx console && orphans=
    docker compose --profile agent up -d --build $orphans agent $sim
    echo "now running: $(cat DEPLOYED_COMMIT 2>/dev/null || echo unknown)"'
  exit 0
fi

if [[ -n "$(git status --porcelain)" && "${FORCE:-}" != 1 ]]; then
  echo "Uncommitted changes; deploy ships only committed code (HEAD). Commit first, or FORCE=1." >&2
  git status --short >&2
  exit 1
fi

commit=$(git rev-parse --short HEAD)
echo "Deploying ${commit} ($(git log -1 --format=%s)) to ${VM}..."

bundle=$(mktemp -t ai-calling-deploy).tgz
trap 'rm -f "$bundle"' EXIT
extra=()
# knowledge.md holds approved pricing; ship it even if you keep it out of git.
[[ -f agent/knowledge.md ]] && ! git ls-files --error-unmatch agent/knowledge.md >/dev/null 2>&1 && extra+=(agent/knowledge.md)
COPYFILE_DISABLE=1 tar czf "$bundle" $(git ls-files | grep -v '^infra/') ${extra[@]+"${extra[@]}"}
gcloud compute scp "$bundle" "$VM:~/ai-calling-deploy.tgz" --project "$GCP_PROJECT" --zone "$GCP_ZONE" --quiet >/dev/null

ssh_vm "set -euo pipefail
cd ~
# Refuse to cut off callers: restarting the agent drops calls in progress.
if [ '${FORCE:-}' != 1 ] && [ -d ai-calling ]; then
  live=\$(cd ai-calling && scripts/lk.sh room list 2>/dev/null | grep -c 'call-' || true)
  if [ \"\$live\" -gt 0 ]; then echo \"\$live call(s) in progress; retry when they end, or FORCE=1.\"; rm -f ai-calling-deploy.tgz; exit 1; fi
fi

# One command per line: set -e does not stop on a failure inside an && list (only on its last command).
rm -rf ai-calling.new
mkdir ai-calling.new
tar xzf ai-calling-deploy.tgz -C ai-calling.new 2>/dev/null
rm ai-calling-deploy.tgz
echo ${commit} > ai-calling.new/DEPLOYED_COMMIT
# Carry over VM-only state: secrets and generated SIP config.
cp ai-calling/.env ai-calling.new/.env
# Fill in settings newer code needs (e.g. DJANGO_SECRET_KEY); never overwrites existing values.
(cd ai-calling.new && scripts/init.sh >/dev/null)
grep -qE '^DJANGO_SECRET_KEY=.+' ai-calling.new/.env || { echo 'DJANGO_SECRET_KEY missing from .env; not deploying.'; exit 1; }
cp ai-calling.new/.env ai-calling/.env
[ -d ai-calling/sip/generated ] && cp -r ai-calling/sip/generated ai-calling.new/sip/ || true

# Build new images while the old containers keep serving calls, one at a time: parallel builds can run
# the 4 GB VM out of memory next to the live call processes.
cd ai-calling.new
for s in dashboard console; do
  docker compose build \$s || { echo 'build failed; nothing changed, the old version is still running'; exit 1; }
done
for s in agent agent-sim; do
  docker compose --profile agent build \$s || { echo 'build failed; nothing changed, the old version is still running'; exit 1; }
done
cd ~

rm -rf ai-calling.prev
mv ai-calling ai-calling.prev
mv ai-calling.new ai-calling
cd ai-calling
start=\$(date -u +%Y-%m-%dT%H:%M:%SZ)
docker compose up -d
docker compose --profile agent up -d agent agent-sim

# The agent (the live-call path) first, so a dashboard or console failure never hides whether it came up.
echo 'Waiting for the agent to register...'
for i in \$(seq 1 30); do
  docker compose logs --since \"\$start\" agent 2>&1 | grep -q 'registered worker' && { echo 'agent registered'; break; }
  sleep 2
  [ \$i = 30 ] && { echo 'agent did not register in 60s; check: make logs s=agent (rollback: ROLLBACK=1 make deploy)'; exit 1; }
done

# Fails the deploy (non-zero) if the dashboard crash-loops, e.g. the SQLite history copy failing at startup.
scripts/wait-dashboard.sh \"\$start\"
# Same for the console: its /sign-in must answer within about 60 s.
scripts/wait-console.sh \"\$start\"
docker image prune -f >/dev/null; docker builder prune -af >/dev/null
docker compose --profile agent ps --format '{{.Service}}: {{.Status}}'
echo \"deployed \$(cat DEPLOYED_COMMIT); disk \$(df -h / | awk 'NR==2{print \$5}') used\""
