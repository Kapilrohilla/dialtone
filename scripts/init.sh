#!/usr/bin/env bash
# Creates .env from .env.example and generates a LiveKit API key/secret and Django secret key.
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
# Older .env files predate the Django dashboard; add the key so it gets generated.
if ! grep -qE "^DJANGO_SECRET_KEY=" .env; then
  # Start on a new line even if the file doesn't end with one.
  [[ -s .env && $(tail -c1 .env) != "" ]] && echo >> .env
  echo "DJANGO_SECRET_KEY=" >> .env
fi
set_if_empty DJANGO_SECRET_KEY "$(openssl rand -base64 64 | tr -dc 'A-Za-z0-9' | head -c 50)"

# Older .env files predate PostgreSQL; add the lines so the password gets generated.
for kv in POSTGRES_DB=dashboard POSTGRES_USER=dashboard POSTGRES_PASSWORD=; do
  if ! grep -qE "^${kv%%=*}=" .env; then
    [[ -s .env && $(tail -c1 .env) != "" ]] && echo >> .env
    echo "$kv" >> .env
  fi
done
set_if_empty POSTGRES_PASSWORD "$(openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c 32)"

# Older .env files predate these settings; add them with their defaults.
for kv in DASHBOARD_URL=http://127.0.0.1:8787 RECORDING_ENABLED=true EGRESS_VERSION=v1.15.0; do
  if ! grep -qE "^${kv%%=*}=" .env; then
    [[ -s .env && $(tail -c1 .env) != "" ]] && echo >> .env
    echo "$kv" >> .env
  fi
done

# Provider keys are optional; only warn about the ones the chosen AGENT_PIPELINE uses.
pipeline=$(grep -E "^AGENT_PIPELINE=" .env | cut -d= -f2- || true)
case "${pipeline:-gemini-live}" in
  sarvam)     ai_keys="SARVAM_API_KEY OPENAI_API_KEY" ;;
  elevenlabs) ai_keys="SARVAM_API_KEY OPENAI_API_KEY ELEVEN_API_KEY" ;;
  *)          ai_keys="GOOGLE_API_KEY" ;;
esac

missing=()
for key in SIP_NUMBERS SIP_ALLOWED_ADDRESSES $ai_keys; do
  val=$(grep -E "^${key}=" .env | cut -d= -f2- || true)
  [[ -z "$val" || "$val" == *XXXX* ]] && missing+=("$key")
done

if ((${#missing[@]})); then
  echo
  echo "Fill these in .env before taking calls (AGENT_PIPELINE=${pipeline:-gemini-live}): ${missing[*]}"
else
  echo ".env looks complete"
fi
