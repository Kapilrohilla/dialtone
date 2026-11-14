#!/usr/bin/env bash
# Deploys the committed code (HEAD) from your laptop to a GCP VM and restarts what changed.
#
# Usage: GCP_PROJECT=my-project deploy/deploy.sh      (or: make deploy GCP_PROJECT=my-project)
#   GCP_PROJECT  GCP project of the VM (required)
#   VM           VM name (default: dialtone)
#   GCP_ZONE     VM zone (default: asia-south1-c)
#   REMOTE_DIR   checkout directory under the VM user's home (default: dialtone). VMs set up before
#                the Dialtone rename use ~/ai-calling: deploy with REMOTE_DIR=ai-calling.
#   FORCE=1      deploy even with uncommitted changes or calls in progress
#   ROLLBACK=1   swap back to the previously deployed version
#
# The VM keeps its own .env (keys, SIP config) and Docker volumes (Redis, call
# history); only code is replaced. The previous code stays in ~/$REMOTE_DIR.prev.
set -euo pipefail
cd "$(dirname "$0")/.."

VM=${VM:-dialtone}
GCP_PROJECT=${GCP_PROJECT:?set GCP_PROJECT to the GCP project of the VM, e.g. GCP_PROJECT=my-project make deploy}
GCP_ZONE=${GCP_ZONE:-asia-south1-c}
REMOTE_DIR=${REMOTE_DIR:-dialtone}
[[ "$REMOTE_DIR" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "REMOTE_DIR must be a plain directory name" >&2; exit 1; }
ssh_vm() { gcloud compute ssh "$VM" --project "$GCP_PROJECT" --zone "$GCP_ZONE" --quiet --command "$1"; }
# On the VM: docker compose for the tree in the current directory. Trees from before the move to deploy/
# (rollback targets) keep docker-compose.yml at their root.
remote_dc='dc() { if [ -f deploy/docker-compose.yml ]; then docker compose -f deploy/docker-compose.yml --env-file .env "$@"; else docker compose "$@"; fi; }'

if [[ "${ROLLBACK:-}" == 1 ]]; then
  echo "Rolling back to the previous deploy..."
  # One command per line: set -e does not stop on a failure inside an && list.
  ssh_vm "set -e; ${remote_dc}
    d=${REMOTE_DIR}
    "'[ -d ~/$d.prev ] || { echo "no previous deploy to roll back to"; exit 1; }
    mv ~/$d ~/$d.rollback-tmp
    mv ~/$d.prev ~/$d
    mv ~/$d.rollback-tmp ~/$d.prev
    cd ~/$d
    # Older trees use the old service names (dashboard, console, agent, agent-sim) and some have no
    # agent-sim and/or console service: build only what this tree has.
    services=$(dc --profile agent config --services)
    pick() { for n in "$@"; do echo "$services" | grep -qx "$n" && { echo "$n"; return; }; done; }
    # One image at a time: parallel builds can run the 4 GB VM out of memory next to live calls.
    for s in $(pick dialtone-server dashboard) $(pick dialtone-console console); do dc build $s; done
    # --remove-orphans: drops containers of services this tree does not define (including the other
    # naming scheme), which would otherwise hold the host-network ports.
    dc --profile agent up -d --build --remove-orphans
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

# A temp dir works the same with BSD (macOS) and GNU (Linux) mktemp.
bundle_dir=$(mktemp -d)
bundle=$bundle_dir/dialtone-deploy.tgz
trap 'rm -rf "$bundle_dir"' EXIT
extra=()
# knowledge.md holds approved pricing; ship it even if you keep it out of git.
[[ -f agent/knowledge.md ]] && ! git ls-files --error-unmatch agent/knowledge.md >/dev/null 2>&1 && extra+=(agent/knowledge.md)
COPYFILE_DISABLE=1 tar czf "$bundle" $(git ls-files | grep -v '^deploy/terraform/') ${extra[@]+"${extra[@]}"}
gcloud compute scp "$bundle" "$VM:~/${REMOTE_DIR}-deploy.tgz" --project "$GCP_PROJECT" --zone "$GCP_ZONE" --quiet >/dev/null

ssh_vm "set -euo pipefail
${remote_dc}
d=${REMOTE_DIR}
cd ~
if [ ! -f \$d/.env ]; then
  echo \"~/\$d/.env not found on the VM. VMs set up before the Dialtone rename: deploy with REMOTE_DIR=ai-calling.\"
  rm -f \$d-deploy.tgz; exit 1
fi
# Refuse to cut off callers: restarting the agent drops calls in progress.
if [ '${FORCE:-}' != 1 ]; then
  live=\$(cd \$d && scripts/lk.sh room list 2>/dev/null | grep -c 'call-' || true)
  if [ \"\$live\" -gt 0 ]; then echo \"\$live call(s) in progress; retry when they end, or FORCE=1.\"; rm -f \$d-deploy.tgz; exit 1; fi
fi

# One command per line: set -e does not stop on a failure inside an && list (only on its last command).
rm -rf \$d.new
mkdir \$d.new
tar xzf \$d-deploy.tgz -C \$d.new 2>/dev/null
rm \$d-deploy.tgz
echo ${commit} > \$d.new/DEPLOYED_COMMIT
# Carry over VM-only state: secrets and generated SIP config.
cp \$d/.env \$d.new/.env
# Fill in settings newer code needs (e.g. DJANGO_SECRET_KEY); never overwrites existing values.
(cd \$d.new && scripts/init.sh >/dev/null)
grep -qE '^DJANGO_SECRET_KEY=.+' \$d.new/.env || { echo 'DJANGO_SECRET_KEY missing from .env; not deploying.'; exit 1; }
# The compose project is now named dialtone; installs made before the rename used the directory name.
# Keep their volumes (call history, Redis, recordings) by pinning the old project name.
if [ \$d != dialtone ] && ! grep -qE '^COMPOSE_PROJECT_NAME=' \$d.new/.env && docker volume inspect \${d}_postgres-data >/dev/null 2>&1; then
  echo \"COMPOSE_PROJECT_NAME=\$d\" >> \$d.new/.env
  echo \"pinned COMPOSE_PROJECT_NAME=\$d in .env (keeps the existing volumes)\"
fi
cp \$d.new/.env \$d/.env
[ -d \$d/sip/generated ] && cp -r \$d/sip/generated \$d.new/sip/ || true

# Build new images while the old containers keep serving calls, one at a time: parallel builds can run
# the 4 GB VM out of memory next to the live call processes.
cd \$d.new
for s in dialtone-server dialtone-console; do
  dc build \$s || { echo 'build failed; nothing changed, the old version is still running'; exit 1; }
done
for s in dialtone-agent dialtone-agent-sim; do
  dc --profile agent build \$s || { echo 'build failed; nothing changed, the old version is still running'; exit 1; }
done
cd ~

rm -rf \$d.prev
mv \$d \$d.prev
mv \$d.new \$d
cd \$d
start=\$(date -u +%Y-%m-%dT%H:%M:%SZ)
# --remove-orphans: drops containers left from the old service names (dashboard, console, agent,
# agent-sim), which would otherwise hold the host-network ports.
dc --profile agent up -d --remove-orphans

# The agent (the live-call path) first, so a server or console failure never hides whether it came up.
echo 'Waiting for the agent to register...'
for i in \$(seq 1 30); do
  dc logs --since \"\$start\" dialtone-agent 2>&1 | grep -q 'registered worker' && { echo 'agent registered'; break; }
  sleep 2
  [ \$i = 30 ] && { echo 'agent did not register in 60s; check: make logs s=dialtone-agent (rollback: ROLLBACK=1 make deploy)'; exit 1; }
done

# Fails the deploy (non-zero) if the server crash-loops, e.g. the SQLite history copy failing at startup.
deploy/wait-server.sh \"\$start\"
# Same for the console: its /sign-in must answer within about 60 s.
deploy/wait-console.sh \"\$start\"
docker image prune -f >/dev/null; docker builder prune -af >/dev/null
dc --profile agent ps --format '{{.Service}}: {{.Status}}'
echo \"deployed \$(cat DEPLOYED_COMMIT); disk \$(df -h / | awk 'NR==2{print \$5}') used\""
