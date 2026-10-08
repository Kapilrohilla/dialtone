#!/usr/bin/env bash
# Creates the inbound SIP trunk and the dispatch rule that sends every call
# to the agent. Idempotent: reuses the trunk/rule if they already exist.
# Run on the media VM after `docker compose up -d`.
set -euo pipefail
cd "$(dirname "$0")/.."

. scripts/lib.sh && load_env

TRUNK_NAME=inbound-main
RULE_NAME=inbound-to-${AGENT_NAME}
OUT=sip/generated
mkdir -p "$OUT"

# "a, b,c" -> "a", "b", "c"
json_list() {
  local IFS=, out=() item
  for item in $1; do
    item=$(echo "$item" | xargs)
    [[ -n "$item" ]] && out+=("\"$item\"")
  done
  (IFS=,; echo "${out[*]}")
}

[[ -z "${SIP_NUMBERS:-}" || "$SIP_NUMBERS" == *XXXX* ]] && { echo "set SIP_NUMBERS in .env" >&2; exit 1; }
[[ -z "${SIP_ALLOWED_ADDRESSES:-}" ]] && { echo "set SIP_ALLOWED_ADDRESSES in .env (your provider's signalling IPs)" >&2; exit 1; }

lk() { scripts/lk.sh "$@"; }

# --- Inbound trunk ---
trunk_id=$(lk sip inbound list 2>/dev/null | grep -w "$TRUNK_NAME" | grep -oE 'ST_[A-Za-z0-9]+' | head -1 || true)
if [[ -n "$trunk_id" ]]; then
  echo "inbound trunk exists: $trunk_id (delete it with 'scripts/lk.sh sip inbound delete $trunk_id' to recreate)"
else
  auth=""
  if [[ -n "${SIP_AUTH_USERNAME:-}" ]]; then
    auth=",
    \"auth_username\": \"${SIP_AUTH_USERNAME}\",
    \"auth_password\": \"${SIP_AUTH_PASSWORD}\""
  fi
  cat > "$OUT/inbound-trunk.json" <<EOF
{
  "trunk": {
    "name": "${TRUNK_NAME}",
    "numbers": [$(json_list "$SIP_NUMBERS")],
    "allowed_addresses": [$(json_list "$SIP_ALLOWED_ADDRESSES")]${auth}
  }
}
EOF
  trunk_id=$(lk sip inbound create "$OUT/inbound-trunk.json" | grep -oE 'ST_[A-Za-z0-9]+' | head -1)
  echo "created inbound trunk: $trunk_id"
fi

# --- Dispatch rule: one room per call, agent dispatched explicitly ---
rule_id=$(lk sip dispatch list 2>/dev/null | grep -w "$RULE_NAME" | grep -oE 'SDR_[A-Za-z0-9]+' | head -1 || true)
if [[ -n "$rule_id" ]]; then
  echo "dispatch rule exists: $rule_id"
else
  cat > "$OUT/dispatch-rule.json" <<EOF
{
  "dispatch_rule": {
    "name": "${RULE_NAME}",
    "trunk_ids": ["${trunk_id}"],
    "rule": { "dispatchRuleIndividual": { "roomPrefix": "call-" } },
    "room_config": { "agents": [{ "agent_name": "${AGENT_NAME}" }] }
  }
}
EOF
  rule_id=$(lk sip dispatch create "$OUT/dispatch-rule.json" | grep -oE 'SDR_[A-Za-z0-9]+' | head -1)
  echo "created dispatch rule: $rule_id"
fi

public_ip=$(curl -s --max-time 3 https://checkip.amazonaws.com || echo "<public-ip>")
echo
echo "Done. In your SIP provider's dashboard, route ${SIP_NUMBERS} to:"
echo "  sip:${public_ip}:5060   (codec: G.711 PCMA/PCMU)"
