#!/usr/bin/env bash
# Runs the pinned LiveKit CLI in Docker against this server, so `lk` doesn't
# need to be installed. Usage: scripts/lk.sh sip inbound list
set -euo pipefail
cd "$(dirname "$0")/.."

. scripts/lib.sh && load_env

# The CLI talks HTTP to the server API; LIVEKIT_URL may be ws:// for agents.
url=${LIVEKIT_URL/#ws:/http:}
url=${url/#wss:/https:}

exec docker run --rm -i --network host \
  -v "$PWD/sip:/work/sip:ro" -w /work \
  -e LIVEKIT_URL="$url" \
  -e LIVEKIT_API_KEY -e LIVEKIT_API_SECRET \
  "livekit/livekit-cli:${LK_CLI_VERSION}" "$@"
