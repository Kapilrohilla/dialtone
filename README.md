# Dialtone

**Self-hosted AI voice agents that answer your phone line.**

Dialtone runs on your own Linux machine or VM. Callers ring a number on your SIP trunk; a
[LiveKit](https://livekit.io)-based agent picks up, talks to them in their language, follows the script and
workflow your team built in the console, and reports how each call went.

- **Build agents in a web console:** persona, script, knowledge documents and a visual workflow, with
  versioned publishing.
- **Test without a phone line:** chat with a draft as text, or talk to it in the browser over WebRTC.
- **Choose your speech stack:** Gemini Live speech-to-speech, or Sarvam STT + OpenAI + Sarvam or ElevenLabs
  TTS. Strong support for Hindi, Hinglish and other Indian languages.
- **Run real calls:** dead-air handling, caller-mood adaptation, live handoff to a person, call recording
  with consent, live calls and call history with outcomes and summaries.
- **Own your data:** everything (PostgreSQL, recordings, LiveKit) runs on your host. Provider keys are
  optional; use only the ones your pipeline needs.

<!-- TODO: add a console screenshot at docs/public/screenshot.png and reference it here:
     ![Dialtone console](docs/public/screenshot.png) -->

**Documentation:** <https://kapilrohilla.github.io/dialtone/>

## Quickstart

Requires **Linux** with Docker and the compose plugin (every service uses host networking; Docker Desktop
on macOS/Windows won't work).

```bash
git clone https://github.com/Kapilrohilla/dialtone.git && cd dialtone
make init     # creates .env with generated secrets; then set GOOGLE_API_KEY in .env
make up       # LiveKit, SIP, Redis, PostgreSQL, server and console
make agent    # the agent worker and text simulator

# A demo agent for the fictional "Northwind Car Rentals", and your console login (prompts for a password)
docker compose -f deploy/docker-compose.yml --env-file .env exec dialtone-server python manage.py seed_demo
docker compose -f deploy/docker-compose.yml --env-file .env exec dialtone-server \
  python manage.py create_member you@example.com --role owner

make server-admin   # optional: Django superuser for /admin/ and instance settings
```

Open <http://localhost:3000> (from a remote VM: `make tunnel GCP_PROJECT=…`, or an SSH tunnel for ports
3000, 8787 and 7880), sign in, and try the demo agent with **Voice test**. To take real phone calls, see
[SIP telephony](https://kapilrohilla.github.io/dialtone/docs/guides/sip-telephony/).

## Repository

| Path | What |
|---|---|
| `agent/` | Python LiveKit Agents worker and text simulator |
| `server/` | Django REST API, admin, LiveKit webhooks, call history |
| `console/` | Next.js console |
| `deploy/` | Docker Compose stack, VM bootstrap and deploy scripts, optional Terraform |
| `scripts/` | Setup, SIP, LiveKit CLI and CI scripts |
| `docs/` | Documentation site |
| `examples/` | Example agents |

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md); report security issues privately as described in
[SECURITY.md](SECURITY.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## License

[Apache License 2.0](LICENSE).
