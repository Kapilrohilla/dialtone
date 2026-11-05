# Carrum Voice console — roadmap

Spec: `docs/superpowers/specs/2026-11-05-carrum-voice-console-design.md` (approved 2026-11-05).

The spec spans four subsystems. Each gets its own plan, written when the previous one has landed (later plans consume the earlier ones' real interfaces). Each plan ends in working, tested software.

| # | Plan | Delivers | Depends on |
|---|---|---|---|
| 1 | **Console API foundation** — `2026-11-05-console-api-foundation.md` | Django REST API: workspaces, auth, preferences, knowledge, workflows (+ validation), agents, publish/versions, runtime config + events endpoints, calls/live/dashboard APIs, retention, seed data. Old dashboard keeps working. | — |
| 2 | Agent runtime | Agent fetches the published config (cache + fallback), assembles system layer + script + step prompt, expression hints, variable fill, workflow engine (step agents, path tools, caps), posts events, version id in report, recording consent line; text "Try it"/"Test call" simulation endpoint using the same engine. | 1 |
| 3 | Next.js console | `console/` app: tokens (light/dark), shell, the ten screens from the Stitch "Final" project wired to plan 1's API, chip editor, workflow canvas, live calls polling, call history slide-over; Next rewrites to Django; retire `calls/templates/calls/index.html`. | 1 (2 for Try it) |
| 4 | Recording + deploy | LiveKit Egress service in compose, audio recordings to `/data/recordings`, Django-served playback for members, retention of recordings, console container in compose, `scripts/deploy.sh` + `make tunnel` for port 3000, README. | 1, 2, 3 |

## Plan 1 outcome (2026-11-05)

Built on branch feature/console-api-foundation (main..HEAD), every task reviewed, final whole-branch review + one fix wave clean. Dashboard suite 219 passed on PostgreSQL.

### Carry forward to later plans

- Plan 2: render `[[expr:…]]` tokens inside `snapshot.knowledge[].body_md` with `snapshot.custom_expressions` (only script and step prompts are pre-rendered); replace the seeded draft script with today's real BASE_INSTRUCTIONS content; cap pause seconds; tell 404 "no published agent" apart from "API down" for the fallback; agents-list / is_outdated N+1 queries.
- Plan 4: run `copy_from_sqlite --dry-run` against a copy of the production SQLite file before the first Postgres deploy; schedule `purge_old_call_data` daily; test live transfer against the real SIP trunk (REFER); trust X-Forwarded-For only behind the proxy (login throttle is keyed by IP and everything arrives from 127.0.0.1); consider connection pooling under ASGI; POSTGRES_PORT is not applied to the postgres service; ROLLBACK=1 doesn't wait for the dashboard; deploy scripts only stub-tested.
- Later: `connected_pct` counts calls with no report as connected; /api/state and the old index page are not workspace-scoped (fine with one workspace).
