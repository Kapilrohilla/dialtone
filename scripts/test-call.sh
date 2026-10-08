#!/usr/bin/env bash
# Rings your phone from Twilio and, when you answer, bridges you to the AI agent's
# number. Useful when your mobile plan can't dial the agent's (international) number.
#
# Usage: scripts/test-call.sh <your-mobile> [twilio-profile] [agent-number]
#   your-mobile    E.164, must be a verified caller ID on that Twilio account
#   twilio-profile Twilio CLI profile that places the call (needs dialing permission
#                  for your country). Default: active profile.
#   agent-number   Default: SIP_NUMBERS from .env (first number)
#
# Set AGENT_SIP_HOST (e.g. 34.93.218.151) to dial the LiveKit server over SIP
# directly instead of the phone number. Needed on Twilio trial accounts, which
# can only dial verified phone numbers.
set -euo pipefail
cd "$(dirname "$0")/.."

mobile=${1:?usage: $0 <your-mobile> [twilio-profile] [agent-number]}
profile=${2:-}
agent=${3:-}
if [[ -z "$agent" && -f .env ]]; then
  . scripts/lib.sh && load_env
  agent=${SIP_NUMBERS%%,*}
fi
[[ -n "$agent" ]] || { echo "pass the agent number or set SIP_NUMBERS in .env" >&2; exit 1; }

p=()
[[ -n "$profile" ]] && p=(-p "$profile")

# Any Twilio number on the account works as the caller ID for the leg to your phone.
from=$(twilio phone-numbers:list "${p[@]}" --properties phoneNumber --no-header | head -1 | xargs)
[[ -n "$from" ]] || { echo "no phone number on this Twilio account" >&2; exit 1; }

# The leg to the agent shows your mobile as caller ID (allowed because it's verified).
if [[ -n "${AGENT_SIP_HOST:-}" ]]; then
  target="<Sip>sip:${agent}@${AGENT_SIP_HOST}:5060</Sip>"
else
  target="<Number>${agent}</Number>"
fi
twiml="<Response><Say>Connecting you to the A I agent.</Say><Dial callerId=\"${mobile}\" timeout=\"30\">${target}</Dial></Response>"

echo "Calling ${mobile} from ${from}; on answer, bridging to ${target}..."
twilio api:core:calls:create "${p[@]}" --to "$mobile" --from "$from" --twiml "$twiml" \
  --properties sid,status
