# Carrum Voice console — roadmap

Spec: `docs/superpowers/specs/2026-11-05-carrum-voice-console-design.md` (approved 2026-11-05).

The spec spans four subsystems. Each gets its own plan, written when the previous one has landed (later plans consume the earlier ones' real interfaces). Each plan ends in working, tested software.

| # | Plan | Delivers | Depends on |
|---|---|---|---|
| 1 | **Console API foundation** — `2026-11-05-console-api-foundation.md` | Django REST API: workspaces, auth, preferences, knowledge, workflows (+ validation), agents, publish/versions, runtime config + events endpoints, calls/live/dashboard APIs, retention, seed data. Old dashboard keeps working. | — |
| 2 | Agent runtime | Agent fetches the published config (cache + fallback), assembles system layer + script + step prompt, expression hints, variable fill, workflow engine (step agents, path tools, caps), posts events, version id in report, recording consent line; text "Try it"/"Test call" simulation endpoint using the same engine. | 1 |
| 3 | Next.js console | `console/` app: tokens (light/dark), shell, the ten screens from the Stitch "Final" project wired to plan 1's API, chip editor, workflow canvas, live calls polling, call history slide-over; Next rewrites to Django; retire `calls/templates/calls/index.html`. | 1 (2 for Try it) |
| 4 | Recording + purge + transfer | LiveKit Egress service in compose, audio recordings to `/data/recordings`, Django-served playback for members (the console's recording player appears once `recording_url` is set), retention of recordings; `purge_old_call_data` on a daily schedule; live transfer tested against the real SIP trunk (REFER). The console container and deploy wiring moved into plan 3. | 1, 2, 3 |

## Plan 1 outcome (2026-11-05)

Built on branch feature/console-api-foundation (main..HEAD), every task reviewed, final whole-branch review + one fix wave clean. Dashboard suite 219 passed on PostgreSQL.

### Carry forward to later plans

- Plan 2 (done: knowledge token rendering, real script seed, pause cap, 404 vs down): ~~render `[[expr:…]]` tokens inside `snapshot.knowledge[].body_md`~~; ~~replace the seeded draft script with today's real BASE_INSTRUCTIONS content~~; ~~cap pause seconds~~; ~~tell 404 "no published agent" apart from "API down" for the fallback~~. Still open: agents-list / is_outdated N+1 queries.
- Plan 4: run `copy_from_sqlite --dry-run` against a copy of the production SQLite file before the first Postgres deploy; schedule `purge_old_call_data` daily; test live transfer against the real SIP trunk (REFER); trust X-Forwarded-For only behind the proxy (login throttle is keyed by IP and everything arrives from 127.0.0.1); consider connection pooling under ASGI; POSTGRES_PORT is not applied to the postgres service; ROLLBACK=1 doesn't wait for the dashboard; deploy scripts only stub-tested.
- Later: `connected_pct` counts calls with no report as connected; /api/state and the old index page are not workspace-scoped (fine with one workspace).

## Plan 2 outcome (2026-11-06)

Built on branch feature/agent-runtime: config fetch with cache and built-in fallback, prompt layers, workflow engine, events, version id in reports, recording consent line, and the `agent-sim` text simulator. Not yet verified:

- Live calls on both pipelines. Needs a staging test call through several workflow steps, especially on Gemini Live.
- The simulator against real Gemini (needs `GOOGLE_API_KEY`).
- Greeting delay after the config fetch (1.5 s budget).

### Carry forward from plan 2

- ~~Plan 3: voice selection per pipeline (validated list) — P19.~~ Done in plan 3, Task 2.
- Gemini start-step block stays in the system prompt; consider wording it as "later steps arrive as tool results".

### Plan 2 staging checklist (before the first production deploy of feature/agent-runtime)

- Greeting latency: time to first agent audio now includes the config fetch (≤ 1.5 s) and session start after the caller joins; check a caller's early "hello" isn't lost.
- Gemini Live multi-step workflow: path tools with and without `value`, step blocks arriving as tool results, wrong-step paths refused, end step → record_outcome → end_call, a looping graph hitting the cap, an end-step outcome override.
- Sarvam/ElevenLabs: a step change while a mood note is set.
- Events reach Live calls; version id, step path and captured answers land on the Call/report.
- Fallback drill: stop the dashboard (cached config used), then unpublish (built-in, cache deleted).
- Containers: /cache writable by the agent user on a fresh volume; agent-sim answers with GOOGLE_API_KEY set (real Gemini text round trip).
- Rollback drill: `ROLLBACK=1 make deploy` back to the plan-1 tree, then forward again.

## Plan 3 outcome (2026-11-05)

Built on branch feature/next-console (main..HEAD), every task reviewed. Shipped:

- Voice choice per pipeline (P19): validated voice list, `GET /api/voices`, applied on calls, recorded voice samples for Preview.
- Dashboard additions for the console: live step path and captured answers, mark for call back, the seeded "Driver onboarding" workflow, Django `/` redirects to `CONSOLE_URL`, optional `CSRF_EXTRA_TRUSTED_ORIGINS`.
- `console/` (Next.js 15, standalone): light/dark tokens and theme cookie, sign in and set password, shell with live count; Today dashboard; agents list with publish, unpublish, duplicate, archive; script editor with expression and variable chips, autosave and the test call simulator; knowledge editor with markdown, upload and version history; workflow list and canvas with step panel and Try it; live calls with transcript, steps, details, transfer and end; call history with filters, export and the call slide-over; settings (profile, appearance, notifications, team, numbers) and integrations.
- Tests: Vitest suite, typecheck and lint in `make test`; `make console-e2e` runs Playwright through every screen against a real, disposable Django + Postgres.
- Deploy: the `console` service (image `ai-calling-console:local`, Node 22 Alpine, about 230 MB) on 127.0.0.1:3000; `make deploy` builds it and waits up to 60 s for `/sign-in` (`scripts/wait-console.sh`); `ROLLBACK=1` removes the console container when the older tree has no console; `make tunnel` forwards 3000 and 8787.

Not yet verified:

- Real calls through plan 2's runtime (plan 2 had not reached production when plan 3 finished; the first `make deploy` of this branch ships both). Run the plan 2 staging checklist above right after it, with `ROLLBACK=1 make deploy` ready.
- The console in a browser on the VM through `make tunnel` (checked locally only: e2e run, and the image serving `/sign-in` 200).
- The console image build on the VM (needs network for `npm ci` and `next/font/google`; `next build` memory on the VM size is untested).
- ElevenLabs voice ids in `voices.json`: taken from the brief, never checked against the live API (no ElevenLabs key was available).

### Carry forward from plan 3

- Plan 4: recording (Egress) and the console's recording player; schedule `purge_old_call_data` daily; live transfer test against the real SIP trunk (REFER).
- Later (minor, deferred in review): agents list has no query-count guard (N+1 from plan 1 still open); a workflow whose post-create save failed has no start step until one is added; a background refetch error on Settings, Profile replaces the form and loses the draft; custom date inputs in call history push a history entry per change; the React Flow attribution stays visible (hiding it is a licensing call).
