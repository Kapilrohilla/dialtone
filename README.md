# AI Calling

Self-hosted inbound voice agent for Indian languages, built on LiveKit.

You choose how the agent listens and speaks with `AGENT_PIPELINE` in `.env`:
- **`gemini-live`** (default): Gemini Live speech-to-speech. One model listens, thinks and speaks, handles Hindi and regional languages natively, and needs only `GOOGLE_API_KEY`.
- **`sarvam`**: Sarvam speech-to-text, then an OpenAI LLM, then Sarvam text-to-speech. Needs `SARVAM_API_KEY` and `OPENAI_API_KEY`.

```
Caller ─► SIP provider ─► livekit-sip ─► livekit-server ◄─► agent worker
                          (5060, RTP)    (rooms, Redis)      Gemini Live (or Sarvam STT → LLM → TTS)
```

Every inbound call gets its own room (`call-…`), and the dispatch rule sends the `phone-agent` worker into it.

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

## Calls dashboard

`make up` also starts the dashboard. It shows:
- live calls: caller number, timer, whether the agent joined
- call history, recorded from LiveKit webhooks into SQLite
- today's stats
- the configured trunks and dispatch rules

It listens on the VM's localhost only, because it shows caller phone numbers. From your laptop, run:

```bash
make tunnel      # then open http://localhost:8787
```

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
