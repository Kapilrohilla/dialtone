#!/usr/bin/env bash
# Creates .env from .env.example and generates a LiveKit API key/secret.
# Safe to re-run: never overwrites existing values.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
  echo "created .env from .env.example"
fi

set_if_empty() {
  local key=$1 value=$2
  if grep -qE "^${key}=$" .env; then
    # '|' delimiter: generated values are alphanumeric, so this is safe.
    sed -i.bak "s|^${key}=$|${key}=${value}|" .env && rm -f .env.bak
    echo "generated ${key}"
  fi
}

set_if_empty LIVEKIT_API_KEY "API$(openssl rand -hex 6)"
set_if_empty LIVEKIT_API_SECRET "$(openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c 48)"

missing=()
for key in SIP_NUMBERS SIP_ALLOWED_ADDRESSES SARVAM_API_KEY OPENAI_API_KEY; do
  val=$(grep -E "^${key}=" .env | cut -d= -f2- || true)
  [[ -z "$val" || "$val" == *XXXX* ]] && missing+=("$key")
done

if ((${#missing[@]})); then
  echo
  echo "Fill these in .env before continuing: ${missing[*]}"
else
  echo ".env looks complete"
fi
