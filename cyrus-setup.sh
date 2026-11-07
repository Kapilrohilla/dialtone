#!/usr/bin/env bash
# Run by Cyrus (the Linear coding agent) in each new issue worktree on the VM, so scripts/ci-check.sh can
# run there. Python envs are shared between worktrees, keyed by the requirements files, so only a changed
# requirements file costs a fresh install. Needs `uv` (https://docs.astral.sh/uv/) on PATH.
set -euo pipefail

cache=${XDG_CACHE_HOME:-$HOME/.cache}/ai-calling-envs
mkdir -p "$cache"

# Keep the links out of commits: .venv/ in .gitignore only matches directories, not symlinks.
exclude=$(git rev-parse --git-common-dir)/info/exclude
mkdir -p "$(dirname "$exclude")"
for p in /agent/.venv /dashboard/.venv; do
  grep -qxF "$p" "$exclude" 2>/dev/null || echo "$p" >> "$exclude"
done

for d in agent dashboard; do
  key=$(cat "$d/requirements.txt" "$d/requirements-dev.txt" | sha256sum | cut -c1-12)
  env=$cache/$d-$key
  if [ ! -e "$env/.complete" ]; then
    rm -rf "$env"
    uv venv --quiet --python 3.12 "$env"
    (cd "$d" && uv pip install --quiet --python "$env/bin/python" -r requirements-dev.txt)
    touch "$env/.complete"
  fi
  ln -sfn "$env" "$d/.venv"
done

(cd console && npm ci --prefer-offline --no-audit --no-fund >/dev/null)
echo "cyrus-setup: venvs linked, console deps installed"
