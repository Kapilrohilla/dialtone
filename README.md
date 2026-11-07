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
- **Live handoff (optional):** set `HANDOFF_SIP_URI` and, when mood is on and a driver is frustrated or angry, the agent offers to connect them to a telecaller and transfers the call if they agree. Your SIP trunk must support call transfer (REFER); test it by setting the URI to your own mobile first.
- **Outcome:** every call logs one `call ended` line (`make logs s=agent`) with the disposition (INTERESTED, NI, NE, CBR, …), the reason, interest strength, the qualification answers, the summary, `do_not_call` and any dead-air check-ins. If the driver hangs up before the agent records an outcome, the call is logged as `CDRP`, or as `NOT_CONNECTED` if the driver never spoke.

## Layout

| Path | What |
|---|---|
| `docker-compose.yml` | Redis, PostgreSQL, LiveKit server, LiveKit SIP, dashboard, console, and the agent + simulator (`agent` profile) |
| `.env.example` | All config: pinned versions, keys, SIP trunk, agent settings |
| `agent/` | Python agent (`agent.py`), pinned deps, Dockerfile |
| `dashboard/` | Calls dashboard: live calls, call history, trunks/dispatch rules; the console's API |
| `console/` | Carrum Voice console (Next.js): agents, scripts, knowledge, workflows, live calls, history |
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
make deploy              # ships HEAD to the VM, rebuilds, waits for the dashboard, console and agent
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
- call history, recorded from LiveKit webhooks into PostgreSQL
- today's stats
- the configured trunks and dispatch rules
- per-call mood reports from the agent: outcome, final mood (worst mood on hover) and dead-air nudges; click a row for the mood readings over the call, latency p50s and dead-air events

It listens on the VM's localhost only, because it shows caller phone numbers, and every page needs a login. From your laptop, run:

```bash
make tunnel      # then open http://localhost:8787 and log in
```

The dashboard is a Django app (`dashboard/`). Call history lives in PostgreSQL (the `postgres` service, data in the `postgres-data` volume, localhost only; `scripts/init.sh` generates `POSTGRES_PASSWORD` in `.env`), and `/admin/` lists and searches all calls.

`make deploy` adds a `DJANGO_SECRET_KEY` to the VM's `.env` if it doesn't have one. After the first deploy of the Django dashboard, run these once on the VM (from `~/ai-calling`):

```bash
make dashboard-admin            # create your /admin/ login (a Django superuser; it has no console access)
docker compose exec dashboard python manage.py create_member you@example.com --name "Your Name" --role owner   # first console user
docker compose cp agent/knowledge.md dashboard:/tmp/knowledge.md   # knowledge.md is not inside the dashboard image
docker compose exec dashboard python manage.py seed_carrum --knowledge /tmp/knowledge.md
```

`make dashboard-admin` only creates a superuser for `/admin/`; the console API needs a workspace member, which `create_member` makes (it prompts for a password). `seed_carrum` creates the draft Carrum agent and adds the approved pricing file as a knowledge document.

Only if you are coming from the old aiohttp dashboard (`/data/calls.db`), also run once:

```bash
docker compose exec dashboard python manage.py import_legacy_calls --path /data/calls.db
```

The import copies the history recorded by the old dashboard and assigns every imported call to a workspace (the one whose agent has the called number, else the only workspace). Running it again creates no duplicates. "Calls today" counts from midnight India time (it used to be UTC).

**Moving from SQLite to PostgreSQL.** Earlier Django versions of the dashboard kept history in `/data/dashboard.sqlite3`. The cutover is automatic: when the dashboard container starts it runs `migrate`, then `copy_from_sqlite --if-needed`, before the server accepts anything. That copies only if the SQLite file exists, `/data/.copied-to-postgres` does not, and PostgreSQL has no calls; it then writes the marker. Copied calls are assigned to a workspace the same way as imported ones (the copy prints `calls assigned to a workspace: N`). `make deploy` waits up to 60 s for the dashboard to answer and prints the copy summary, or fails with its last log lines if it does not come up. If PostgreSQL already has calls and there is no marker it logs a WARNING and skips (it never overwrites). The copy keeps ids and only reads the SQLite file, which stays in the `dashboard-data` volume as a backup.

Before the first deploy, make sure the VM's `.env` has `POSTGRES_PASSWORD` (`scripts/init.sh`), and rehearse the copy against a copy of the production file (never the live one):

```bash
docker compose run --rm --no-deps -v /path/to/copy-dir:/old:ro dashboard python manage.py copy_from_sqlite --path /old/dashboard.sqlite3 --dry-run
```

`--dry-run` does the whole copy inside a transaction, prints the counts and rolls back. `scripts/migrate-dashboard-to-postgres.sh` is an optional manual check (`COPY_ARGS=--dry-run` supported) that prints counts from both sides; once `/data/.copied-to-postgres` exists it only prints the counts, and a real copy it makes writes that marker.

**Rollback caveat.** `ROLLBACK=1 make deploy` returns to code that reads SQLite, so calls recorded in PostgreSQL after the deploy are not shown by the old version (the SQLite file only holds history up to the cutover). They are not lost: they stay in the `postgres-data` volume. To recover, deploy the PostgreSQL version again. To bring them into SQLite instead there is no tool; export them from PostgreSQL first (`docker compose exec postgres pg_dump -U dashboard dashboard > backup.sql`).

**Console API.** The dashboard also serves the console's JSON API under `/api/`: auth and team, agents, knowledge, workflows, calls and live calls, the dashboard summary, settings and integration requests, plus runtime endpoints the agent calls. Management commands (run with `docker compose exec dashboard python manage.py ...`):

- `create_member EMAIL [--name N] [--role editor] [--workspace carrum]` creates a console user (prompts for a password).
- `seed_carrum [--knowledge PATH]` creates the Carrum workspace and a draft "Driver lead qualifier" agent; if `PATH` (default `../agent/knowledge.md`) exists it also adds that file as the "Approved pricing and rules" knowledge document. Safe to repeat; it never publishes.
- `purge_old_call_data [--days 90] [--dry-run]` deletes transcripts older than 90 days (turn events and report `turns`) and blanks the caller's words on labelled turns, keeping the telecaller labels; outcomes, summaries, answers and metrics stay. Nothing schedules it yet; plan 4 adds a daily run.
- `copy_from_sqlite` is the SQLite to PostgreSQL copy described above.

Run the tests locally with `make test` (needs `dashboard/.venv` with `dashboard/requirements-dev.txt`). The dashboard tests run on PostgreSQL: `make test-db` starts a disposable container on `127.0.0.1:55432` (needs Docker; `make test` does it for you). To use another server set `TEST_POSTGRES_HOST`, `TEST_POSTGRES_PORT`, `TEST_POSTGRES_USER` and `TEST_POSTGRES_PASSWORD`.

The agent POSTs its report to `/api/report` when a call ends, if `DASHBOARD_REPORT_URL` is set (on the VM: `http://127.0.0.1:8787/api/report`). The request carries a LiveKit-signed token with identity `agent-report` instead of a login. A report may arrive before LiveKit's `room_finished` webhook, and a later report for the same room replaces the earlier one. `/admin/` filters calls by final mood and outcome and shows each full report.

## Console

The Carrum Voice console (`console/`, Next.js) is where the team edits agents, scripts, knowledge and workflows, and watches live calls and call history. Its server is the only thing the browser talks to: it proxies `/api/*` to the dashboard (`DJANGO_URL`, read at build time; default `http://127.0.0.1:8787`), so there is no CORS and no token in the page. Django's `/` redirects to it (`CONSOLE_URL`).

**On the server.** `make up` and `make deploy` build and start the `console` service (image `ai-calling-console:local`, about 230 MB). Like the dashboard it listens on the VM's localhost only (127.0.0.1:3000). From your laptop:

```bash
make tunnel      # Console: http://localhost:3000 (the dashboard stays on :8787)
```

**First sign-in.** The console signs in workspace members, not Django superusers. Create the first owner once on the VM (from `~/ai-calling`; it prompts for the password), then sign in at http://localhost:3000 with that email:

```bash
docker compose exec dashboard python manage.py create_member you@carrum.co.in --name "Your Name" --role owner
```

Owners and admins invite everyone else from Settings, Team.

**Deploy.** `make deploy` builds the console image on the VM next to the others (the build needs network access: `npm ci`, and `next/font/google` downloads the fonts), then waits up to 60 s for `http://127.0.0.1:3000/sign-in` after the dashboard answers. If it doesn't answer, the deploy fails with the console's last log lines; undo with `ROLLBACK=1 make deploy`. Rolling back to a version without the console removes its container.

**Local development.** With the dashboard running on :8787:

```bash
cd console && npm ci
make console-dev                 # http://localhost:3000
cd console && npm test && npm run typecheck && npm run lint
```

Sign in with a workspace member (`python manage.py create_member you@example.com --role owner`). To try the production image locally: `docker build -t ai-calling-console:local console`. On Linux, `docker run --rm --network host ai-calling-console:local` serves http://127.0.0.1:3000; on macOS, Docker Desktop's host network is its VM's, so use `docker run --rm -p 3000:3000 -e HOSTNAME=0.0.0.0 ai-calling-console:local` instead.

**End-to-end smoke run.** `make test-db && make console-e2e` re-creates the database `console_e2e` on the test Postgres (127.0.0.1:55432), seeds it, creates the owner `e2e@carrum.test` with a random password (or `E2E_PASSWORD`), starts Django on 127.0.0.1:8788 and a production build of the console on 127.0.0.1:3100, and runs Playwright (`console/e2e/smoke.spec.ts`) through every screen. LiveKit and the simulator are not started, so the run also checks that the console says so. The build goes to `console/.next/e2e`, leaving `console/.next` alone. Screenshots land in `console/test-results/light/` and `console/test-results/dark/`, server logs in `console/test-results/servers/`, the HTML report in `console/playwright-report/`. First time: `cd console && npx playwright install chromium`. Extra arguments go to Playwright, e.g. `scripts/console-e2e.sh --grep Knowledge`.

## How a call picks its agent

When a call starts, the agent asks the console for the published agent of the number that was called (`DASHBOARD_URL`, 1.5 s budget):

1. Published agent for that number: its fresh config is used, and the call keeps that version until it ends.
2. Console down or slow: the last saved copy for that number (`/cache`, the `agent-cache` volume).
3. No published agent, or it was unpublished: today's built-in script and `knowledge.md`.

A publish takes effect on the next call; calls already running are not changed. During a call the agent streams turns, step changes, mood and captured fields to `/api/runtime/events` for the live calls screen.

Dead-air and mood settings come from the published agent. Mood also needs `MOOD_ENABLED=true` on the worker. The voice chosen in the console is not applied yet (it arrives with plan 3); the voice still comes from the worker's env (`GEMINI_VOICE`, `TTS_SPEAKER`, `ELEVENLABS_VOICE_ID`).

On a VM that runs only the agent (no dashboard), set `DASHBOARD_URL=` (empty) in `.env`. The `.env.example` value `http://127.0.0.1:8787` points at a dashboard that isn't there, so every call's config fetch and live events would fail; empty turns both off and calls use the built-in agent.

`RECORDING_ENABLED=true` makes the agent speak the recording consent line after its opening. It does not record anything; recording arrives with the recording plan.

**Simulator.** The `agent-sim` service (127.0.0.1:8790, same image as the agent, started with `--profile agent`) runs the same prompt and workflow engine as text. The console's Try it and Test call use it through `AGENT_SIM_URL`. It needs `GOOGLE_API_KEY`; `SIM_PORT` and `SIM_LLM_MODEL` change the port and model.

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

## Running the agent tests

The agent tests in `agent/tests` use pytest (configured by `agent/pytest.ini`) and need no running services:

```bash
cd agent && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q   # same command `make test` runs for the agent
```
