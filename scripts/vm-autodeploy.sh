#!/usr/bin/env bash
# Runs ON THE VM from the ai-calling-autodeploy systemd timer (every 2 minutes). Follows the `dev` branch:
# when origin/dev moves, deploys it the same way scripts/deploy.sh does, checks the agent, dashboard and
# console come up, and swaps the previous version back in if they don't.
#
# Installed copy: /usr/local/bin/ai-calling-autodeploy (this file is the source; reinstall after editing).
# Pause:   touch ~/.autodeploy-paused      Resume: rm ~/.autodeploy-paused
# Logs:    sudo journalctl -u ai-calling-autodeploy -f
# Retry a commit that failed: rm ~/.autodeploy-failed
set -euo pipefail

BRANCH=${AUTODEPLOY_BRANCH:-dev}
REPO_URL=${AUTODEPLOY_REPO:-https://github.com/Kapilrohilla/ai-calling.git}
MIRROR=$HOME/ai-calling.git
FAILED=$HOME/.autodeploy-failed
cd "$HOME"

exec 9>"$HOME/.autodeploy.lock"
flock -n 9 || { echo "another deploy is running"; exit 0; }
[ -e "$HOME/.autodeploy-paused" ] && { echo "paused (rm ~/.autodeploy-paused to resume)"; exit 0; }

[ -d "$MIRROR" ] || git clone --quiet --bare "$REPO_URL" "$MIRROR"
git -C "$MIRROR" fetch --quiet --prune "$REPO_URL" "+refs/heads/$BRANCH:refs/heads/$BRANCH"
target=$(git -C "$MIRROR" rev-parse --short "refs/heads/$BRANCH")
current=$(cat ai-calling/DEPLOYED_COMMIT 2>/dev/null || true)
[ "$target" = "$current" ] && exit 0
if [ "$(cat "$FAILED" 2>/dev/null || true)" = "$target" ]; then
  echo "$BRANCH@$target failed to deploy before; waiting for a new commit (or rm $FAILED to retry)"
  exit 0
fi

# Never cut off callers: restarting the agent drops calls in progress. The next timer run retries.
live=$(cd ai-calling && scripts/lk.sh room list 2>/dev/null | grep -c 'call-' || true)
if [ "${live:-0}" -gt 0 ]; then echo "$live call(s) in progress; will retry"; exit 0; fi

echo "deploying $BRANCH@$target ($(git -C "$MIRROR" log -1 --format=%s "refs/heads/$BRANCH")), replacing ${current:-nothing}"
fail() { echo "$1"; echo "$target" > "$FAILED"; exit 1; }

rm -rf ai-calling.new
mkdir ai-calling.new
git -C "$MIRROR" archive "refs/heads/$BRANCH" | tar x -C ai-calling.new
rm -rf ai-calling.new/infra
echo "$target" > ai-calling.new/DEPLOYED_COMMIT
# Carry over VM-only state: secrets, generated SIP config, and pricing knowledge kept out of git.
cp ai-calling/.env ai-calling.new/.env
(cd ai-calling.new && scripts/init.sh >/dev/null)
grep -qE '^DJANGO_SECRET_KEY=.+' ai-calling.new/.env || fail "DJANGO_SECRET_KEY missing from .env; not deploying"
cp ai-calling.new/.env ai-calling/.env
if [ -d ai-calling/sip/generated ]; then cp -r ai-calling/sip/generated ai-calling.new/sip/; fi
if [ -f ai-calling/agent/knowledge.md ] && [ ! -f ai-calling.new/agent/knowledge.md ]; then
  cp ai-calling/agent/knowledge.md ai-calling.new/agent/knowledge.md
fi

# Build while the old containers keep serving calls, one image at a time (parallel builds can run the VM
# out of memory next to live calls). A failed build changes nothing. Up to 3 tries per image: the console
# build downloads Google Fonts (next/font/google), which now and then gets a response it can't parse.
build() {
  local s=$1 i
  for i in 1 2 3; do
    docker compose --profile agent build "$s" && return 0
    echo "build of $s failed (try $i of 3)"
    sleep 20
  done
  return 1
}
cd ai-calling.new
for s in dashboard console agent agent-sim; do
  build "$s" || fail "build of $s failed; nothing changed, the old version is still running"
done
cd "$HOME"

start_and_check() {
  local since
  since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  docker compose up -d   # infra (postgres, redis, livekit, sip) only if it is down; never recreated here
  # Always recreate the app containers: compose does not reliably notice a rebuilt image under the same tag.
  docker compose --profile agent up -d --force-recreate --no-deps dashboard console agent agent-sim
  for i in $(seq 1 30); do
    docker compose logs --since "$since" agent 2>&1 | grep -q 'registered worker' && break
    sleep 2
    [ "$i" = 30 ] && { echo "agent did not register in 60s"; return 1; }
  done
  scripts/wait-dashboard.sh "$since" && scripts/wait-console.sh "$since"
}

rm -rf ai-calling.prev
mv ai-calling ai-calling.prev
mv ai-calling.new ai-calling
cd ai-calling
if start_and_check; then
  docker image prune -f >/dev/null
  docker builder prune -af >/dev/null
  rm -f "$FAILED"
  echo "deployed $BRANCH@$target; disk $(df -h / | awk 'NR==2{print $5}') used"
  exit 0
fi

# The new version did not come up: put the previous one back. Images are tagged per service, so the old
# tree has to be rebuilt (one at a time again) before it is started.
echo "$BRANCH@$target did not come up healthy; rolling back to $current"
docker compose --profile agent logs --since 5m --tail 40 agent dashboard console 2>&1 | tail -60 || true
cd "$HOME"
mv ai-calling ai-calling.failed-tmp
mv ai-calling.prev ai-calling
rm -rf ai-calling.failed
mv ai-calling.failed-tmp ai-calling.failed
cd ai-calling
for s in dashboard console agent agent-sim; do build "$s" || echo "rebuild of $s failed"; done
if start_and_check; then
  echo "rolled back; ${current:-previous version} is running again (failed tree kept in ~/ai-calling.failed)"
else
  echo "ROLLBACK ALSO FAILED; the stack needs attention now (docker compose --profile agent ps)"
fi
fail "deploy of $BRANCH@$target failed"
