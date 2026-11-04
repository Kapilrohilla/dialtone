# AI Calling

Self-hosted inbound voice agent for Indian languages, built on LiveKit.

You choose how the agent listens and speaks with `AGENT_PIPELINE` in `.env`:
- **`gemini-live`** (default): Gemini Live speech-to-speech. One model listens, thinks and speaks, handles Hindi and regional languages natively, and needs only `GOOGLE_API_KEY`.
- **`sarvam`**: Sarvam speech-to-text, then an OpenAI LLM, then Sarvam text-to-speech. Needs `SARVAM_API_KEY` and `OPENAI_API_KEY`.
- **`elevenlabs`**: like `sarvam`, but ElevenLabs speaks. Also needs `ELEVEN_API_KEY`; pick the voice with `ELEVENLABS_VOICE_ID`. Free ElevenLabs plans only get premade voices over the API and don't allow commercial use.

```
Caller ─► SIP provider ─► livekit-sip ─► livekit-server ◄─► agent worker
                          (5060, RTP)    (rooms, Redis)      Gemini Live (or Sarvam STT → LLM → TTS)
```

Every inbound call gets its own room (`call-…`), and the dispatch rule sends the `phone-agent` worker into it.

## What the agent does

It's Carrum Mobility's AI calling assistant for driver-partner leads. It speaks Hindi/Hinglish, checks city, licence, driving experience and Uber ID, pitches the fitting plan (Uber Go rental, Uber Black salary, Double Driver), and confirms whether the driver wants a telecaller follow-up.

- **Approved pricing and rules:** put city-wise deposits, fees, offers, plan-routing and VDC/WTHINK rules in `agent/knowledge.md`, then run `make agent`. The agent quotes only what's in that file. Without it, the agent quotes no figures and refers those questions to the telecalling team.
- **Lead record (optional):** dispatch the agent with JSON metadata, e.g. `{"lead_id": "L123", "city": "Pune", "previously_interested": true}`. The agent skips questions the record answers. `previously_interested` picks the "aapne interest dikhaya tha" opening.
- **Dead air:** if the driver goes quiet, the agent checks in after 4 s and again after 9 s, then says goodbye and hangs up at 15 s, logged as `UNRESOLVED` (or `NOT_CONNECTED` if they never spoke). The agent's own speech doesn't restart the count; the driver speaking does. "Ek minute", "ruko" or "wait" triples the timings for that pause. Tune or turn off with the `DEAD_AIR_*` settings.
- **Caller mood (off by default):** with `MOOD_ENABLED=true`, a small model labels each driver reply (interested, confused, frustrated, rushed, suspicious, angry, disengaged or neutral). Once two replies agree (or one is clearly angry), the agent adjusts: shorter and calmer when the driver is frustrated, slower and simpler when confused, straight to the point when rushed. On `sarvam`/`elevenlabs` it also changes speaking pace. It never tells the driver it noticed their mood. Leave it off until the accuracy check has passed.
- **Outcome:** every call logs one `call ended` line (`make logs s=agent`) with the disposition (INTERESTED, NI, NE, CBR, …), the reason, interest strength, the qualification answers, the summary, `do_not_call` and any dead-air check-ins. If the driver hangs up before the agent records an outcome, the call is logged as `CDRP`, or as `NOT_CONNECTED` if the driver never spoke.

## Layout

| Path | What |
|---|---|
| `docker-compose.yml` | Redis, LiveKit server, LiveKit SIP, and the agent (`agent` profile) |
| `.env.example` | All config: pinned versions, keys, SIP trunk, agent settings |
| `agent/` | Python agent (`agent.py`), pinned deps, Dockerfile |
| `dashboard/` | Calls dashboard: live calls, call history, trunks/dispatch rules |
| `scripts/init.sh` | Creates `.env` and generates the LiveKit API key/secret |
| `scripts/bootstrap-server.sh` | Fresh Debian/Ubuntu VM: installs Docker (plus ufw if given provider IPs) |
| `scripts/setup-sip.sh` | Creates the inbound trunk and dispatch rule (safe to re-run) |
| `scripts/lk.sh` | Pinned LiveKit CLI via Docker, so there's nothing to install |
| `infra/terraform/` | GCP VM, static IP and firewall rules (see its README) |

## Pinned versions

| Component | Version |
|---|---|
| livekit-server | v1.13.9 |
| livekit/sip | v1.18.0 |
| livekit-cli | v2.18.8 |
| livekit-agents | 1.8.5 |

To upgrade, bump the tag in `.env` (or `agent/requirements.txt`), test on staging, then deploy. Never use `:latest`.

## Deploy (phase 1: one VM, ~2 concurrent calls)

Use a Linux VM in Mumbai (4 vCPU / 8 GB, Ubuntu 24.04) with a static public IP.

```bash
git clone <this repo> ai-calling && cd ai-calling
sudo scripts/bootstrap-server.sh <provider-signalling-ip> [<more-ips>]   # then log out/in for docker group
make init        # creates .env; fill SIP_* and GOOGLE_API_KEY (or the sarvam keys)
make up          # redis + livekit + sip
make sip         # trunk + dispatch rule; prints the SIP URI for your provider
make agent       # build and start the agent worker
```

In your SIP provider's dashboard, route the number to `sip:<public-ip>:5060`, with codec G.711 (PCMA/PCMU). Then call the number.

Debugging:

```bash
make logs s=sip                # INVITEs, auth/IP rejections
make logs s=agent              # agent sessions
make lk a="sip inbound list"
make lk a="room list"
```

| Symptom | Likely cause |
|---|---|
| No INVITE in sip logs | Provider not pointed at the right IP, or firewall blocking 5060 |
| INVITE rejected / 403 | Provider IP not in `SIP_ALLOWED_ADDRESSES`, or number not in `SIP_NUMBERS` |
| Call connects, silence | UDP 10000–20000 blocked, or wrong external IP |
| Room created, no agent | Agent not running, or `AGENT_NAME` mismatch |

## Deploying changes

From your laptop, after committing:

```bash
make deploy              # ships HEAD to the VM, rebuilds, waits for the agent to register
ROLLBACK=1 make deploy   # back to the previous version
```

- It deploys only committed code. The VM keeps its own `.env` and its Docker volumes (Redis, call history).
- It refuses to run while a call is in progress, because restarting the agent drops the call (`FORCE=1` overrides).
- New images are built while the old containers keep serving. Even so, the agent is offline for about 20 s while it restarts.

## Test call without dialing abroad

If your mobile can't dial the agent's number (e.g. a US number from India), have Twilio ring you and bridge the call:

```bash
scripts/test-call.sh +91XXXXXXXXXX "<twilio-profile>"
```

On a Twilio **trial** account:
- your mobile must be a verified caller ID
- you must press a key during the trial message
- set `AGENT_SIP_HOST=<public-ip>` to dial the server over SIP, because trial accounts can't dial unverified numbers

## Calls dashboard

`make up` also starts the dashboard. It shows:
- live calls: caller number, timer, whether the agent joined
- call history, recorded from LiveKit webhooks into SQLite
- today's stats
- the configured trunks and dispatch rules
- per-call mood reports from the agent: outcome, final mood (worst mood on hover) and dead-air nudges; click a row for the mood readings over the call, latency p50s and dead-air events

It listens on the VM's localhost only, because it shows caller phone numbers, and every page needs a login. From your laptop, run:

```bash
make tunnel      # then open http://localhost:8787 and log in
```

The dashboard is a Django app (`dashboard/`). Call history lives in `/data/dashboard.sqlite3` in the `dashboard-data` volume, and `/admin/` lists and searches all calls.

After the first deploy of the Django dashboard, run these once on the VM:

```bash
scripts/init.sh                 # adds DJANGO_SECRET_KEY to an older .env
docker compose up -d dashboard  # restart it with the new key
make dashboard-admin            # create your login
docker compose exec dashboard python manage.py import_legacy_calls --path /data/calls.db
```

The import copies the history recorded by the old dashboard. Running it again creates no duplicates. "Calls today" counts from midnight India time (it used to be UTC).

Run the tests locally with `make test` (needs `dashboard/.venv` with `dashboard/requirements-dev.txt`).

The agent POSTs its report to `/api/report` when a call ends, if `DASHBOARD_REPORT_URL` is set (on the VM: `http://127.0.0.1:8787/api/report`). The request carries a LiveKit-signed token with identity `agent-report` instead of a login. A report may arrive before LiveKit's `room_finished` webhook, and a later report for the same room replaces the earlier one. `/admin/` filters calls by final mood and outcome and shows each full report.

## Evaluating caller mood

Keep `MOOD_ENABLED=false` until telecaller labels show the mood readings are good enough.

1. Set `MOOD_ENABLED=true MOOD_EVAL_CAPTURE=true` for one week of real calls. Reports then include the caller's turns, and each caller turn becomes a row to label.
2. Create telecaller accounts in `/admin/auth/user/` with **Staff status** on and only the `calls | turn label` "Can view" and "Can change" permissions.
3. Telecallers label 300 or more turns in `/admin/calls/turnlabel/`. Pick the mood from the dropdown in the list and press Save at the bottom of the page. Use `unclear` when you can't tell; those turns are not scored.
4. Score them:

   ```bash
   docker compose exec dashboard python manage.py mood_eval              # all labels
   docker compose exec dashboard python manage.py mood_eval --since 2026-11-10
   ```

   It prints accuracy, precision/recall per mood, a confusion matrix and a PASS/FAIL line.

**Go-live gate:** precision of at least 0.7 for `angry`, `frustrated` and `confused`. Below that, tighten `CLASSIFIER_PROMPT` and re-score, or keep `MOOD_ENABLED=false`.

Afterwards, set `MOOD_EVAL_CAPTURE=false` and delete the captured speech, because the turns hold what callers said:

```bash
docker compose exec dashboard python manage.py purge_turns
```

Also compare the CDRP and NI rates for calls with mood on and off, using the admin's outcome and mood filters.

## Scale (phase 2: ~50 concurrent calls)

- **Media VM:** keep it as is (4–8 vCPU).
- **Agent VMs:** add 2–3 of them (4–8 vCPU each). On each one:

  ```bash
  # .env: LIVEKIT_URL=ws://<media-vm-private-ip>:7880 (+ same key/secret, API keys)
  docker compose --profile agent up -d --build agent
  ```

  Then allow 7880 from the private subnet on the media VM.
- **Before going to 50:**
  - SIP trunk has 50+ channels.
  - Sarvam and LLM plans allow 50+ concurrent streams.
  - Load test at 10, then 25, then 50 calls.
- **Metrics:** Prometheus endpoints are LiveKit `:6789` and SIP `:6790`.

## Local development

The compose stack uses host networking. It runs fully on Linux; on macOS, Docker Desktop's host networking is enough for a smoke test, but not for real calls. To iterate on the agent:

```bash
cd agent && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m livekit.agents download-files
make agent-dev   # point LIVEKIT_URL in .env at your server
```
