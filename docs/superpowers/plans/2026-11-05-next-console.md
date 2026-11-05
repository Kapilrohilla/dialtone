# Next.js console — implementation plan (3 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The ops team signs in at `http://localhost:3000` (over `make tunnel`) and runs Carrum Voice from the ten Stitch "Final" screens, light and dark, wired to the plan 1 API and the plan 2 simulator, deployed as a `console` container next to the dashboard.

**Architecture:** A Next.js App Router app in `console/` is a client-rendered single origin: `next.config.ts` rewrites `/api/*` to Django (`DJANGO_URL`, default `http://127.0.0.1:8787`), so Django session cookies and CSRF work unchanged. Every screen fetches through one `apiFetch` client and TanStack Query hooks; styling is CSS variables (one token set, light and dark) plus CSS Modules. Two shared editors carry most of the complexity: `TokenEditor` (TipTap with expression and variable chips that round-trip to the stored `[[expr:…]]` / `{{lead.…}}` text) and the workflow canvas (React Flow). A few small Django gaps found while mapping screens to the API are closed first.

**Tech Stack:** Node 22, Next.js 15.5 (App Router, `output: "standalone"`), React 19, TypeScript 5 strict, TanStack Query 5, TipTap 2 (`@tiptap/react`, `starter-kit`, `extension-table*`, `tiptap-markdown` 0.8), `@xyflow/react` 12, `@dagrejs/dagre` 1, `lucide-react` (stroke 1.5), Vitest 3 + Testing Library + MSW 2 (jsdom), Playwright 1.5x for one end-to-end smoke run. Django 5.2 + DRF (existing) for Task 1–2.

**Spec:** `docs/superpowers/specs/2026-11-05-carrum-voice-console-design.md` ("Screens", "Decisions after the builder check", visual rules). Visual source of truth: `docs/superpowers/specs/assets/final-screens.md` (tokens, copy, layout per screen) and the exported screens in `docs/superpowers/specs/assets/stitch/NN-<screen>.png|.html` (light; `02-dashboard-dark.png` for dark). The HTML exports are layout references only: never copy their invented data or Tailwind classes. Roadmap: `docs/superpowers/plans/2026-11-05-carrum-voice-console-roadmap.md` (carry-forward P19: voice selection).

## Global Constraints

- One origin: the browser only ever talks to the Next server; `/api/:path*` → `${DJANGO_URL}/api/:path*`. `DJANGO_URL` is read at build time (standalone bakes rewrites); default `http://127.0.0.1:8787`. No CORS, no tokens in JS.
- Auth: Django session cookie `sessionid`; CSRF cookie `csrftoken` from `GET /api/auth/csrf`, sent back as header `X-CSRFToken` on every non-GET. `CSRF_TRUSTED_ORIGINS` already lists `http://localhost:3000` and `http://127.0.0.1:3000`. A 403 whose `detail` is exactly `Authentication credentials were not provided.` means signed out → go to `/sign-in?next=<path>`.
- Roles: `owner`, `admin`, `editor`, `viewer`. Viewers see no edit, publish, transfer, end or invite controls (server enforces anyway). Only owners see "Owner" in role pickers. Team invite needs owner/admin.
- Tokens (exact, `final-screens.md`): LIGHT page `#FBF9F5`, panel `#FFFFFF`, border `#E4DFD6`, well/input `#F3F0EA`, sidebar `#F3F0EA`, strong rule `#CFC8BC`, ink `#1E1A16`, ink-2 `#4A443D`, muted `#6E675F`, amber text `#9A6200` on `#FBEFD6`, blue `#2F6DB5` on `#E6EEF8`, ok `#2E7D4F` on `#E5F3EA`, bad `#B4412F` on `#F9E4E0`. DARK page `#1E2228`, panel `#262B32`, border `#3A4049`, well/input `#14171B`, sidebar `#191C21`, strong rule `#545C67`, ink `#EEF0F3`, ink-2 `#C9CED6`, muted `#A3AAB5`, amber text `#F2B544` on `#4A3A1C`, blue `#7FB2F0` on `#1F3248`, ok `#6FCF8E` on `#1F3326`, bad `#F07A6A` on `#3A2220`. Primary button (both modes) fill `#F2B544`, text `#2A1F0B`.
- Expression chip tints (bg / 1px border / text). Light: happy+laugh `#FCEBDC/#F1C9A5/#8A4A12`, sad `#E8E8F8/#C5C6EC/#3F429A`, fear `#F3E6F0/#DDBFD5/#6E2F5F`, angry `#F9E4E0/#EDBDB3/#9A3324`, whisper `#EEECE8/#D6D2CB/#4F4A44`, pause `#E6EBF0/#C3CDD8/#3A4B5E`, excited `#FBE5EE/#F0BED3/#9A2B5B`. Dark: happy+laugh `#3D2A1A/#6B4524/#F5B98A`, sad `#262845/#44477A/#B9BBF2`, fear `#352434/#5E3F5A/#E3B4D6`, angry `#3A2220/#6A3A33/#F4A89C`, whisper `#2C3036/#4A5059/#D0D4DA`, pause `#23303D/#3E5266/#A9C1DA`, excited `#3A2130/#6A3A55/#F3A9CA`. Custom expressions use the whisper tint with a dashed border; an unknown expression uses the bad tint. Variable chips use the blue pair.
- Theme: `:root` holds light; `[data-theme="dark"]` holds dark; `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { …dark… } }` for "Match system". Hue never moves between modes. The `<html data-theme>` comes from cookie `cv_theme` (`light`|`dark`, absent = system) read in the root layout, so there is no flash; the cookie is written whenever `preferences.appearance` is loaded or changed.
- Type: Hanken Grotesk (400/500/600) for everything, with Noto Sans Devanagari as the next family in the stack so Hindi renders in the same weight; JetBrains Mono ONLY for phone numbers, times, durations and counts. Body 15–16px, labels 13–14px, never below 13px, page titles 22–24px weight 500. Load with `next/font/google`.
- Layout: sidebar 232px; 24px page gutter; 16px between rows; controls 40px tall; at most two content columns; tables max 6 columns, horizontal rules only, no outer card; roundness 8px. Must not break down to 60rem wide.
- Copy and visual rules (binding): sentence case, never ALL CAPS or letter-spaced; no `·` joined strings; no decorative status dots; no cards inside cards; no gradients, shadows, purple/indigo, emoji; thin line icons; exactly ONE amber primary button per screen (dialogs may have their own); amber = a person (caller, operator, current step), blue = the agent and system values; plain words ("Outcome" not "Disposition", "Steps" not "Nodes"); hide ids, versions, token counts, latency; never invent figures — an unknown number shows `—`, prices `₹—`.
- Every data region has loading, empty, error and full states (`StateBlock`). Errors show the API's `detail` (or the first field error) in plain words plus "Try again".
- Visible focus: 2px blue outline, 2px offset, on every interactive element. `prefers-reduced-motion: reduce` disables transitions and the canvas fit animation.
- Times are shown in the user's `preferences.time_zone` (default `Asia/Kolkata`): "Today 14:32", "Yesterday 09:10", else "5 Nov 14:32".
- Display outcomes are the five groups `Interested`, `Call back`, `Not interested`, `Dropped`, `Not reached`. Chip colours: Interested ok, Call back amber, Not interested neutral (well + ink-2), Dropped bad, Not reached muted.
- Removed by the decisions: no "Send WhatsApp details", no "Listen in", no recording player until `recording_url` is non-null (plan 4). "Continue with Google" is not rendered (OAuth isn't configured; a dead button is worse than none). Workflow screen's primary is "Save", not "Publish".
- Tests: `cd console && npm test` (Vitest, `--run`) must be pristine (no act() or React key warnings); `npm run typecheck` and `npm run lint` clean. Django: `cd dashboard && .venv/bin/pytest -q` (needs `make test-db`); agent: `cd agent && .venv/bin/pytest -q`.

## Review Focus

1. **Session expires while someone is editing a script** — the autosave fails with the signed-out 403; the editor keeps the text, shows "You were signed out. Sign in again to keep your changes." and the sign-in link returns to the same page. Task 3 (`apiFetch redirects on signed-out 403 but not on permission 403`) and Task 8 (`keeps the draft and shows the signed-out message when autosave gets a signed-out 403`).
2. **Hindi text with chips next to Devanagari matras** (`[happy]नमस्ते`, a chip between two Devanagari words, `{{lead.name}} जी`) — round-trips byte-for-byte through the editor. Task 5 (`round-trips Devanagari around chips`).
3. **A workflow with a dangling path or no positions** (saved by the API or an old client) — the canvas lays it out instead of stacking every step at 0,0, and dangling paths are listed as errors, not crashes. Task 10 (`lays out steps that have no position`, `drops paths to missing steps from the canvas and shows the server error`).
4. **Publishing a second agent while one is live** — the dialog names the agent that will stop answering; after publish both rows refresh. Task 7 (`publish dialog names the live agent it replaces`).
5. **The test simulator is down** (no `agent-sim`, or no `GOOGLE_API_KEY`) — Test call / Try it show "The test simulator isn't running." and keep the typed message, never a blank panel. Task 8 (`shows the simulator-down message and keeps the typed text`).

## Rulings made while planning

- **Written rules beat the pictures.** The Stitch exports still break some of their own rules (the workflow canvas is clipped, status dots, a visible "Step #06", "Transfer to human", a dark-mode switch in place of the toggle). Where a PNG and this plan or `final-screens.md` disagree, the text wins. The `.html` exports were re-typed from the Stitch download by a helper and are not byte-verified: use them for structure only.
- **Voice Preview plays a pre-recorded sample** of each voice (`voice-samples/`, copied into `console/public/voices/`) rather than synthesising the script's first line, which the spec asked for. That would need a TTS endpoint per pipeline and a provider call per click. Cost if wrong: a later task adds `POST /api/voices/preview`.
- **Console deploy moves from plan 4 into this plan** (Task 15), because the user wants to see the console on the server. Plan 4 keeps recording (Egress), the purge schedule and the live transfer test.
- **"Continue with Google" is not rendered**, and "Forgot password?" explains the invite-link route (there is no reset email).
- **Live calls step line** shows only the steps a call has passed through plus the current one. The future path isn't known until the caller answers.
- **No autosave for knowledge or workflows**, only for agent scripts. Saving a document or workflow is a deliberate act that marks agents outdated. Script drafts can't reach callers until Publish, so autosave there is safe.

---

## File structure

```
console/
  package.json  tsconfig.json  next.config.ts  eslint.config.mjs  vitest.config.ts  vitest.setup.ts
  playwright.config.ts  Dockerfile  .dockerignore
  public/voices/                     voice samples copied from voice-samples/ (Task 2)
  src/middleware.ts                  no sessionid cookie → /sign-in?next=
  src/app/layout.tsx  globals.css    fonts, tokens, data-theme from cookie, <Providers>
  src/app/providers.tsx              QueryClientProvider
  src/app/sign-in/page.tsx
  src/app/set-password/[uid]/[token]/page.tsx
  src/app/(console)/layout.tsx       <Shell> (needs /api/me)
  src/app/(console)/page.tsx         Dashboard ("/")
  src/app/(console)/agents/page.tsx  agents/[id]/page.tsx
  src/app/(console)/workflows/page.tsx  workflows/[id]/page.tsx
  src/app/(console)/knowledge/page.tsx
  src/app/(console)/live/page.tsx
  src/app/(console)/calls/page.tsx
  src/app/(console)/settings/page.tsx  settings/team/page.tsx  settings/phone-numbers/page.tsx
  src/app/(console)/integrations/page.tsx
  src/lib/api.ts          apiFetch, ApiError, csrf
  src/lib/types.ts        API response types (one place)
  src/lib/queries.ts      TanStack Query keys + hooks, one section per API area
  src/lib/tokens.ts       parse/serialize of script tokens (mirror of dashboard/voiceagents/tokens.py)
  src/lib/format.ts       phone, duration, times, relative time
  src/lib/outcomes.ts     outcome groups, chip tones, 14 codes with plain labels
  src/lib/theme.ts        appearance ↔ cookie ↔ data-theme
  src/lib/roles.ts        canEdit, canManageTeam, isOwner
  src/components/ui/      Button Chip Panel Table Switch Segmented Dialog Menu Field Tabs Disclosure SlideOver StateBlock Toast
  src/components/shell/   Shell Sidebar TopBar ThemeToggle
  src/components/editor/  TokenEditor ExprChipNode VarChipNode ExpressionMenu VariableMenu NewExpressionDialog markdown.ts
  src/components/sim/     Simulator (Test call / Try it chat panel)
  src/components/workflow/ Canvas StepNode StepPanel graph.ts layout.ts
  src/test/               msw server + handlers per area, renderWithProviders, fixtures
  e2e/smoke.spec.ts
scripts/console-e2e.sh    disposable Django + Next for Playwright
```

Each screen's components live next to its page (`src/app/(console)/<screen>/_components/*`). Shared pieces live in `src/components/`. Tests sit next to the file they test as `*.test.ts(x)`.

---

### Task 1: Django gaps the screens need

Close the API gaps found while mapping screens: live calls need the step path and captured details, "Call again"/"Call back" must be able to *mark* a call, the "Driver onboarding" workflow from the designs should exist in seed data, and Django's old `/` page hands over to the console.

**Files:**
- Modify: `dashboard/calls/api.py` (`LiveListView`, `NeedsPersonView`)
- Modify: `dashboard/calls/views.py` (`index`), delete `dashboard/calls/templates/calls/index.html` and any static file only it used
- Modify: `dashboard/voiceagents/management/commands/seed_carrum.py`
- Test: `dashboard/tests/test_calls_api.py`, `dashboard/tests/test_seed.py` (extend the existing files; match their fixtures)

**Interfaces:**
- Produces: `GET /api/live` rows gain `step_path: list[str]` (step names from `step_entered` events in seq order, consecutive duplicates collapsed) and `captured: dict[str, str]` (`captured_fields(events)` from `calls/serializers.py`). `POST /api/calls/<room>/needs-person` accepts either `{"handled": bool}` (unchanged) or `{"needs_person": true}` → sets `needs_person=True`, `needs_person_handled_at=None`; a body with neither key, or a non-bool, → 400 `{"needs_person": ["Must be true or false."]}` / existing `handled` error. Response unchanged: `{room, needs_person, handled_at}`.
- Produces: `seed_carrum` creates (idempotently, by name) workflow "Driver onboarding" whose graph matches screen 5, with `position: {x, y}` on every step, NOT linked to any agent. Steps (id → type, name): `greeting` start "Greeting"; `ask_city` prompt "Ask city"; `ask_licence` collect "Ask licence and experience" field `licence`; `explain_plan` prompt "Explain the plan" (prompt `[[expr:excited]]{{lead.city}} में हमारे plan के बारे में बताऊँ?[[expr:pause:1]]`); `end_interested` end "End: interested" outcome `INTERESTED`; `schedule_callback` end "Schedule a call back" outcome `CBR`; `transfer` transfer "Transfer to a telecaller"; `end_city` end "End: not in your city" outcome `NE`; `end_no_licence` end "End: not eligible" outcome `NE`. Paths (label): greeting→ask_city "Next"; ask_city→ask_licence "Pune or Delhi"; ask_city→end_city "Other city"; ask_licence→explain_plan "Has licence"; ask_licence→end_no_licence "No licence"; explain_plan→end_interested "Interested"; explain_plan→schedule_callback "Busy"; explain_plan→transfer "Upset". Every prompt is one plain Hinglish line the agent says (no prices). The graph must pass `workflows.graph.validate` with no errors.
- Produces: `GET /` on Django returns 302 to `settings.CONSOLE_URL` (new setting, env `CONSOLE_URL`, default `http://localhost:3000/`). `/api/state`, `/webhook`, `/api/report*` unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_live_rows_carry_step_path_and_captured(member_client, live_call_with_events):
    # events: step_entered Greeting, Greeting, Ask city; field_captured city=Pune, licence=""
    row = member_client.get("/api/live").json()[0]
    assert row["step_path"] == ["Greeting", "Ask city"]
    assert row["captured"] == {"city": "Pune"}

def test_mark_needs_person_sets_flag_and_clears_handled(editor_client, handled_call):
    r = editor_client.post(f"/api/calls/{handled_call.room}/needs-person", {"needs_person": True}, format="json")
    assert r.status_code == 200 and r.json()["needs_person"] is True and r.json()["handled_at"] is None

def test_mark_needs_person_rejects_non_bool(editor_client, call):
    r = editor_client.post(f"/api/calls/{call.room}/needs-person", {"needs_person": "yes"}, format="json")
    assert r.status_code == 400 and r.json() == {"needs_person": ["Must be true or false."]}

def test_viewer_cannot_mark_needs_person(viewer_client, call):
    assert viewer_client.post(f"/api/calls/{call.room}/needs-person", {"needs_person": True}, format="json").status_code == 403

def test_seed_creates_valid_driver_onboarding_workflow(db):
    call_command("seed_carrum"); call_command("seed_carrum")
    wf = Workflow.objects.get(name="Driver onboarding")          # exactly one after two runs
    graph = wf.current.graph
    assert validate(graph, set(KnowledgeDocument.objects.values_list("id", flat=True))) == []
    assert all(isinstance(s.get("position"), dict) for s in graph["steps"])
    assert not Agent.objects.filter(workflow=wf).exists()

def test_index_redirects_to_console(client, settings):
    settings.CONSOLE_URL = "http://localhost:3000/"
    r = client.get("/")
    assert r.status_code == 302 and r["Location"] == "http://localhost:3000/"
```

- [ ] **Step 2: Run to verify they fail** — `cd dashboard && .venv/bin/pytest -q tests/test_calls_api.py tests/test_seed.py -k "step_path or needs_person or driver_onboarding or redirects_to_console"` → FAIL (KeyError `step_path`, 400 on `needs_person`, `Workflow.DoesNotExist`, 200 not 302).
- [ ] **Step 3: Implement** the three API changes, the seed workflow (create through the same model path the workflows API uses so a revision 1 exists) and the redirect. Remove the old index template and its test; keep `views.state`.
- [ ] **Step 4: Run** `cd dashboard && .venv/bin/pytest -q` → all pass.
- [ ] **Step 5: Commit** `git commit -m "feat(dashboard): live step path and captures, mark for call back, seed onboarding workflow, / → console"`

---

### Task 2: Voice choice per pipeline (carry-forward P19)

The agent's voice dropdown must only offer voices the running pipeline can speak, and the chosen voice must actually be used on calls.

**Files:**
- Create: `dashboard/voiceagents/voices.json`, `dashboard/voiceagents/voices.py`
- Modify: `dashboard/voiceagents/serializers.py` (`AgentWriteSerializer.validate_voice_id`), `dashboard/voiceagents/api.py` (`VoicesView`), `dashboard/voiceagents/urls.py`, `dashboard/config/settings.py` (`AGENT_PIPELINE = os.getenv("AGENT_PIPELINE", "gemini-live")`)
- Create: `agent/voices.json` (identical copy), `agent/voices.py`
- Modify: `agent/agent.py` (`gemini_live_session`, `sarvam_tts`, `elevenlabs_tts` take `voice: str | None`)
- Create: `console/public/voices/` — copy `voice-samples/female_Kore.wav → kore.wav`, `female_Aoede.wav → aoede.wav`, `female_Leda.wav → leda.wav`, `male_Charon.wav → charon.wav`, `male_Orus.wav → orus.wav`, `male_Puck.wav → puck.wav`, `voice-samples/elevenlabs/{sarah,alice,jessica,laura,lily,matilda}.mp3` as-is. (`console/` may not exist yet; create just this folder.)
- Test: `dashboard/tests/test_voices.py`, `agent/tests/test_voices.py`

**Interfaces:**
- `voices.json` (both copies byte-identical):
  ```json
  {"gemini-live": [
     {"id": "Kore", "name": "Kore", "description": "Female, firm", "sample": "/voices/kore.wav"},
     {"id": "Aoede", "name": "Aoede", "description": "Female, light", "sample": "/voices/aoede.wav"},
     {"id": "Leda", "name": "Leda", "description": "Female, youthful", "sample": "/voices/leda.wav"},
     {"id": "Charon", "name": "Charon", "description": "Male, informative", "sample": "/voices/charon.wav"},
     {"id": "Orus", "name": "Orus", "description": "Male, firm", "sample": "/voices/orus.wav"},
     {"id": "Puck", "name": "Puck", "description": "Male, upbeat", "sample": "/voices/puck.wav"}],
   "sarvam": [{"id": "priya", "name": "Priya", "description": "Female, Hindi", "sample": null}],
   "elevenlabs": [
     {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah", "description": "Female, soft", "sample": "/voices/sarah.mp3"},
     {"id": "Xb7hH8MSUJpSbSDYk0k2", "name": "Alice", "description": "Female, clear", "sample": "/voices/alice.mp3"},
     {"id": "cgSgspJ2msm6clMCkdW9", "name": "Jessica", "description": "Female, expressive", "sample": "/voices/jessica.mp3"},
     {"id": "FGY2WhTYpPnrIDTdsKH5", "name": "Laura", "description": "Female, upbeat", "sample": "/voices/laura.mp3"},
     {"id": "pFZP5JQG7iQjIQuC4Bku", "name": "Lily", "description": "Female, warm", "sample": "/voices/lily.mp3"},
     {"id": "XrExE9yKIg1WjnMxR4Ji", "name": "Matilda", "description": "Female, friendly", "sample": "/voices/matilda.mp3"}]}
  ```
  The implementer confirms each ElevenLabs id against the ElevenLabs premade voice list (`GET https://api.elevenlabs.io/v1/voices` with the `.env` key if available); drop any id that doesn't match its sample file's name and say so in the report.
- Dashboard: `voices.for_pipeline(pipeline: str) -> list[dict]`; `GET /api/voices` (members) → `{"pipeline": settings.AGENT_PIPELINE, "voices": [...]}`. `AgentWriteSerializer` rejects a non-empty `voice_id` not in `for_pipeline(settings.AGENT_PIPELINE)` with `"Choose a voice from the list."`; `""` stays allowed (= worker default).
- Agent: `voices.resolve(pipeline: str, voice_id: str | None, default: str) -> str` returns `voice_id` when it is in that pipeline's list, else `default` (and logs a warning when a non-empty id was dropped). `entrypoint` passes `cfg.snapshot["voice_id"]` (or None for built-in) through `resolve` with the existing env default (`GEMINI_VOICE`, `TTS_SPEAKER`, `ELEVENLABS_VOICE_ID`) into the session builders. The simulator ignores voice.

- [ ] **Step 1: Write the failing tests**

```python
# dashboard/tests/test_voices.py
def test_voices_endpoint_lists_current_pipeline(member_client, settings):
    settings.AGENT_PIPELINE = "gemini-live"
    body = member_client.get("/api/voices").json()
    assert body["pipeline"] == "gemini-live" and [v["id"] for v in body["voices"]][:2] == ["Kore", "Aoede"]

def test_agent_rejects_voice_from_other_pipeline(editor_client, agent, settings):
    settings.AGENT_PIPELINE = "gemini-live"
    r = editor_client.patch(f"/api/agents/{agent.id}", {"voice_id": "EXAVITQu4vr4xnSDxMaL"}, format="json")
    assert r.status_code == 400 and r.json()["voice_id"] == ["Choose a voice from the list."]

def test_agent_accepts_blank_voice(editor_client, agent):
    assert editor_client.patch(f"/api/agents/{agent.id}", {"voice_id": ""}, format="json").status_code == 200

def test_catalog_matches_agent_copy():
    here = Path(__file__).resolve().parents[1] / "voiceagents" / "voices.json"
    there = Path(__file__).resolve().parents[2] / "agent" / "voices.json"
    assert here.read_bytes() == there.read_bytes()

def test_every_sample_file_exists():
    root = Path(__file__).resolve().parents[2] / "console" / "public"
    for v in voices.for_pipeline("gemini-live") + voices.for_pipeline("elevenlabs"):
        if v["sample"]: assert (root / v["sample"].lstrip("/")).is_file()
```

```python
# agent/tests/test_voices.py
def test_resolve_known_voice(): assert voices.resolve("gemini-live", "Puck", "Kore") == "Puck"
def test_resolve_unknown_falls_back(caplog):
    assert voices.resolve("gemini-live", "Sarah", "Kore") == "Kore" and "voice" in caplog.text
def test_resolve_empty_uses_default(): assert voices.resolve("sarvam", "", "priya") == "priya"
def test_gemini_session_uses_resolved_voice(monkeypatch): ...  # patch google.realtime.RealtimeModel, assert voice="Puck"
```

- [ ] **Step 2: Run** both suites' new tests → FAIL (404 on `/api/voices`, ImportError `voices`).
- [ ] **Step 3: Implement** as in Interfaces. `voices.py` loads the JSON next to it once at import.
- [ ] **Step 4: Run** `cd dashboard && .venv/bin/pytest -q` and `cd agent && .venv/bin/pytest -q` → all pass.
- [ ] **Step 5: Commit** `git commit -m "feat: voice choice per pipeline, applied on calls (P19)"`

---

### Task 3: Console scaffold — tokens, API client, test harness

**Files:**
- Create: `console/package.json`, `tsconfig.json` (strict, `@/*` → `src/*`), `next.config.ts`, `eslint.config.mjs` (next/core-web-vitals + typescript), `vitest.config.ts`, `vitest.setup.ts`, `.gitignore` (`.next`, `node_modules`, `test-results`, `playwright-report`), `src/app/layout.tsx`, `src/app/providers.tsx`, `src/app/globals.css`, `src/middleware.ts`, `src/lib/api.ts`, `src/lib/types.ts`, `src/lib/theme.ts`, `src/lib/roles.ts`, `src/lib/format.ts`, `src/lib/outcomes.ts`, `src/components/ui/*`, `src/test/{server.ts,handlers.ts,render.tsx,fixtures.ts}`
- Modify: `Makefile` (`console-dev`, `test` runs console tests), `.gitignore` (root, `console/node_modules`)
- Test: `src/lib/api.test.ts`, `src/lib/format.test.ts`, `src/lib/theme.test.ts`, `src/components/ui/ui.test.tsx`

**Interfaces:**
- `package.json` scripts: `dev` (`next dev -p 3000`), `build`, `start`, `test` (`vitest --run`), `test:watch`, `typecheck` (`tsc --noEmit`), `lint` (`eslint .`), `e2e` (`playwright test`). Pin exact versions (no `^`) and commit `package-lock.json`.
- `next.config.ts`: `output: "standalone"`, `rewrites()` → `[{source: "/api/:path*", destination: \`${process.env.DJANGO_URL ?? "http://127.0.0.1:8787"}/api/:path*\`}]`, `skipTrailingSlashRedirect: true`, `poweredByHeader: false`.
- `src/lib/api.ts`:
  - `class ApiError extends Error { status: number; detail: string; fields: Record<string, string[]> }` — `detail` = body `detail`, else first field error, else `"Something went wrong. Try again."`; for `{"errors": [...]}` (publish) `fields.errors` holds the list.
  - `apiFetch<T>(path: string, init?: RequestInit & { json?: unknown }) => Promise<T>` — `credentials: "same-origin"`; JSON body when `json` given; on non-GET ensures the `csrftoken` cookie (calls `GET /api/auth/csrf` once if missing) and sends `X-CSRFToken`; 204 → `undefined`; signed-out 403 (exact detail in Global Constraints) → `window.location.assign("/sign-in?next=" + encodeURIComponent(location.pathname + location.search))` and throws `ApiError` with `status 401`; other errors throw `ApiError`.
  - `isSignedOut(e: unknown): boolean` (status 401 from the rule above).
- `src/lib/types.ts`: one exported type per API shape used by the screens, named after the resource: `Me`, `Preferences`, `TeamMember`, `KnowledgeListItem`, `KnowledgeDoc`, `Revision`, `WorkflowListItem`, `Workflow`, `Graph`, `Step` (`{id, name, type: "start"|"prompt"|"collect"|"knowledge"|"transfer"|"end", prompt?, field?, knowledge_id?, outcome?, position?: {x, y}}`), `Path` (`{id?, from, to, label}`), `AgentListItem`, `Agent` (incl. `settings: {mood_adaptation, dead_air: {enabled, nudge_s, second_nudge_s, hang_up_s}}`, `script: {id, title, body}[]`, `custom_expressions: Record<string, string>`), `AgentVersion`, `Expression`, `Voice`, `CallRow`, `CallDetail`, `CallPage`, `LiveCall` (incl. Task 1's `step_path`, `captured`), `Dashboard`, `PhoneNumber`, `SimResponse` (`{reply, state, step: {id, name} | null, outcome, ended}`). Field names exactly as the serializers quoted in the Task 1 brief context (`dashboard/*/serializers.py`, `calls/api.py`).
- `src/lib/theme.ts`: `type Appearance = "light" | "dark" | "system"`; `applyAppearance(a: Appearance): void` sets/removes `document.documentElement.dataset.theme` and writes/clears cookie `cv_theme` (path `/`, 1 year, `SameSite=Lax`); `themeFromCookie(value: string | undefined): "light" | "dark" | undefined`.
- `src/lib/format.ts`: `formatPhone("+918047182290") → "+91 80 4718 2290"` (Indian numbers: `+91 AA BBBB CCCC`; anything else unchanged); `formatDuration(125) → "2:05"`, `(3725) → "1:02:05"`, `(null) → "—"`; `formatWhen(iso, tz, now) → "Today 14:32" | "Yesterday 09:10" | "5 Nov 14:32"`; `timeAgo(iso, now) → "just now" | "5 minutes ago" | "2 hours ago" | "3 days ago" | "5 Nov"`; `formatElapsed(fromIso, now) → "02:14"` (mm:ss, then h:mm:ss).
- `src/lib/outcomes.ts`: `OUTCOME_GROUPS` (the five, in order), `outcomeTone(group) → "ok" | "amber" | "neutral" | "bad" | "muted"`, `DISPOSITIONS: {code, group, label}[]` with labels: INTERESTED "Interested", CBR "Asked to talk later", NI "Not interested", NE "Not eligible", ISUDO "Missing documents", ISUID "Uber ID blocked", HND "Not a driver", WRGN "Wrong number", OWNVA "Has own vehicle", ABULR "Abusive", LANGUAGE_BARRIER "No shared language", CDRP "Call cut off", UNRESOLVED "No clear outcome", NOT_CONNECTED "No conversation".
- `src/lib/roles.ts`: `canEdit(role)`, `canManageTeam(role)` (owner|admin), `isOwner(role)`.
- UI primitives (`src/components/ui/`), each a small component + CSS Module using only token variables: `Button` (`variant: "primary" | "outline" | "danger" | "text"`, `size` default 40px; `loading` shows a spinner and disables), `Chip` (`tone: "ok" | "amber" | "blue" | "bad" | "neutral" | "muted"`), `Panel`, `Table` (+ `Th`, `Td`, row height prop), `Switch` (role="switch"), `Segmented`, `Dialog` (native `<dialog>`, focus trap, Esc closes, returns focus), `Menu` ("…" trigger, roving focus, Esc), `Field` (label, hint, error, input/select/textarea), `Tabs`, `Disclosure` ("Advanced"), `SlideOver` (420px right, Esc closes), `StateBlock` (`state: "loading" | "empty" | "error"`, `title`, `body`, `onRetry`), `Toast` (one polite live region, `useToast().show(text, tone)`).
- `src/middleware.ts`: paths other than `/sign-in`, `/set-password/*`, `/api/*`, `/_next/*`, `/voices/*`, `/favicon.ico` without a `sessionid` cookie → 307 to `/sign-in?next=<path+search>`.
- Test harness: MSW `setupServer` in `vitest.setup.ts` with `onUnhandledRequest: "error"`; `renderWithProviders(ui, {route?})` wraps a fresh `QueryClient` (retries off) and a `next/navigation` mock (`useRouter`, `usePathname`, `useSearchParams` driven by `route`); `fixtures.ts` exports realistic objects built from the seed (`Driver lead qualifier`, `+918047182290`, Devanagari script lines from `final-screens.md`).
- Makefile: `console-dev` (`cd console && DJANGO_URL=http://127.0.0.1:8787 npm run dev`), and `test` gains `cd console && npm ci --prefer-offline && npm test && npm run typecheck && npm run lint`.

- [ ] **Step 1: Scaffold** with `npx create-next-app@15.5 console --ts --app --src-dir --eslint --no-tailwind --import-alias "@/*" --use-npm`, then remove the starter page content and add the dependencies listed in Tech Stack with exact versions.
- [ ] **Step 2: Write the failing tests**

```ts
// src/lib/api.test.ts
it("sends the csrf token on writes, fetching it once if missing", ...)   // expect GET /api/auth/csrf then POST with X-CSRFToken
it("apiFetch redirects on signed-out 403 but not on permission 403", ...) // detail "Authentication credentials were not provided." → location.assign("/sign-in?next=%2Fagents%2F3"); detail "You do not have permission…" → ApiError 403, no redirect
it("turns field errors into detail", ...)        // 400 {"name": ["A name is required."]} → e.detail === "A name is required."
it("keeps publish errors as a list", ...)        // 400 {"errors": ["End step \"X\" needs an outcome."]} → e.fields.errors[0]
// src/lib/format.test.ts
it("formats Indian numbers", () => expect(formatPhone("+918047182290")).toBe("+91 80 4718 2290"))
it("formats durations", () => { expect(formatDuration(125)).toBe("2:05"); expect(formatDuration(null)).toBe("—") })
it("formats call times in the user's time zone", ...) // 2026-11-05T09:02:00Z, tz Asia/Kolkata, now same day → "Today 14:32"
// src/lib/theme.test.ts
it("dark sets data-theme and the cookie; system clears both", ...)
// src/components/ui/ui.test.tsx
it("Dialog closes on Escape and returns focus to the opener", ...)
it("Switch toggles aria-checked with Space", ...)
it("StateBlock error calls onRetry", ...)
```

- [ ] **Step 3: Run** `cd console && npm test` → FAIL (modules missing).
- [ ] **Step 4: Implement** the files above. `globals.css` defines every token from Global Constraints as `--page`, `--panel`, `--border`, `--well`, `--sidebar`, `--rule-strong`, `--ink`, `--ink-2`, `--muted`, `--amber`, `--amber-tint`, `--blue`, `--blue-tint`, `--ok`, `--ok-tint`, `--bad`, `--bad-tint`, `--primary-fill`, `--primary-ink`, `--expr-<name>-bg|border|ink`, plus `--font-sans`, `--font-mono`, `--radius: 8px`, `--gutter: 24px`, `--row-gap: 16px`, `--control-h: 40px`, and the base element styles (body background `--page`, ink, 15px).
- [ ] **Step 5: Run** `npm test && npm run typecheck && npm run lint && npm run build` → pass, build succeeds.
- [ ] **Step 6: Commit** `git commit -m "feat(console): Next.js scaffold, tokens, API client, UI primitives, test harness"`

---

### Task 4: Sign in, set password, and the shell

**Files:**
- Create: `src/app/sign-in/page.tsx` (+ module CSS), `src/app/set-password/[uid]/[token]/page.tsx`, `src/app/(console)/layout.tsx`, `src/components/shell/{Shell,Sidebar,TopBar,ThemeToggle}.tsx`, `src/lib/queries.ts` (section "me": `useMe`, `useUpdateMe`, `useLogout`; section "live": `useLiveCalls(refetchMs)`)
- Test: `src/app/sign-in/page.test.tsx`, `src/app/set-password/[uid]/[token]/page.test.tsx`, `src/components/shell/Shell.test.tsx`

**Interfaces:**
- Consumes: `apiFetch`, `ApiError`, `applyAppearance`, UI primitives (Task 3).
- Produces: `(console)/layout.tsx` renders `<Shell>` (sidebar + main area). Each page renders `<TopBar title | breadcrumb={[{label, href?}]} chip? status? secondary={…} primary={…} />` as the first thing in its content. `useMe()` returns `Me` (query key `["me"]`); `useLiveCalls(ms)` (key `["live"]`) is shared with Task 11.
- Sign in (screen 1): centred 400px panel; wordmark "Carrum Voice"; heading "Sign in"; fields "Work email" (placeholder `name@company.com`, `autocomplete="username"`) and "Password" (show/hide toggle, `autocomplete="current-password"`); text button "Forgot password?" reveals the muted line "Ask your workspace admin for a new invite link."; one amber full-width "Sign in"; below, muted "No account? Ask your workspace admin for an invite." `POST /api/auth/login {email, password}` → on success write the `me` query, apply appearance, `router.replace(next ?? "/")` (only same-origin paths starting with `/` and not `//`). 400 → the API's "Wrong email or password." under the form. 429 → "Too many attempts. Wait a minute and try again."
- Set password: heading "Set your password", two password fields, amber "Set password" → `POST /api/auth/set-password {uid, token, new_password}`; 204 → "Password set." + link "Sign in"; errors from `new_password` list or `detail`.
- Sidebar (232px, `--sidebar`): "Carrum Mobility" (from `me.workspace.name`), nav: Dashboard `/`, Agents `/agents`, Workflows `/workflows`, Knowledge base `/knowledge`, Live calls `/live` with a blue count chip when `useLiveCalls(10000)` returns ≥ 1 (no chip at 0 or on error), Call history `/calls`, Integrations `/integrations` with a muted "Soon" chip, Settings `/settings`. Active item: `aria-current="page"`, ink text on `--panel`. Bottom: user's name, `ThemeToggle` (sun/moon icon button, label "Switch to dark" / "Switch to light"; flips between light and dark and `PATCH /api/me {preferences: {appearance}}`), "Sign out" in the user menu (`POST /api/auth/logout` → `/sign-in`).
- Console layout loading `me`: full-page quiet skeleton (no spinner flash under 300ms); error → StateBlock with retry.
- Root layout reads `cookies().get("cv_theme")` and sets `<html lang="en" data-theme>`; Shell calls `applyAppearance(me.preferences.appearance)` when `me` loads (keeps cookie in sync across devices).

- [ ] **Step 1: Write the failing tests**

```tsx
it("signs in and goes to the next page", ...)          // MSW login 200 → router.replace("/agents") for ?next=/agents
it("refuses an off-site next", ...)                     // ?next=//evil.example → replace("/")
it("shows the API's wrong-password message", ...)       // 400 {"detail":"Wrong email or password."}
it("shows the throttle message on 429", ...)
it("set-password posts uid and token from the URL", ...) // body {uid:"Mw", token:"abc", new_password}
it("sidebar shows the live count only when calls are live", ...) // [] → no chip; 2 rows → chip "2"
it("marks the current page in the sidebar", ...)         // route /calls → Call history aria-current="page"
it("theme toggle switches to dark and saves the preference", ...) // data-theme="dark", PATCH body {preferences:{appearance:"dark"}}
it("renders no Google button", ...)                       // queryByText(/google/i) === null
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `npm test && npm run typecheck && npm run lint` → pass.
- [ ] **Step 5: Commit** `git commit -m "feat(console): sign in, set password, shell with live count and theme toggle"`

---

### Task 5: Token editor (expression and variable chips)

**Files:**
- Create: `src/lib/tokens.ts`, `src/components/editor/{TokenEditor.tsx,ExprChipNode.ts,VarChipNode.ts,ExpressionMenu.tsx,VariableMenu.tsx,NewExpressionDialog.tsx,markdown.ts,editor.module.css}`
- Test: `src/lib/tokens.test.ts`, `src/components/editor/TokenEditor.test.tsx`

**Interfaces:**
- `src/lib/tokens.ts` mirrors `dashboard/voiceagents/tokens.py` exactly: regex `/\[\[expr:([a-z_]+)(?::(\d+(?:\.\d+)?))?\]\]|\{\{\s*(lead\.[a-z_]+)\s*\}\}/g`; `BUILTIN_EXPRESSIONS = ["happy","laugh","sad","fear","angry","whisper","pause","excited"]`; `type Token = {kind:"text", text} | {kind:"expr", name, seconds?: number} | {kind:"var", path}`; `parse(body: string): Token[]`; `serialize(tokens: Token[]): string` (expr → `[[expr:name]]` or `[[expr:pause:1.2]]`; var → `{{lead.city}}`); `exprLabel(t) → "pause 1.2s" | "laugh"`; `MAX_PAUSE_S = 5` (check `long_pause_errors` in tokens.py and use its value).
- `markdown.ts`: `toEditorHtml(markdown: string): string` — replaces each token with `<span data-expr="laugh">` / `<span data-expr="pause" data-seconds="1.2">` / `<span data-var="lead.city">` before handing Markdown to `tiptap-markdown` (`html: true`); `ExprChipNode` / `VarChipNode` (inline, atom, selectable) parse those spans and serialize back to the token text in `toMarkdown`. `fromEditor(editor) => string` = `editor.storage.markdown.getMarkdown()`.
- `<TokenEditor value onChange mode="script" | "document" | "line" customExpressions={Record<string,string>} onCreateExpression?(name, hint) readOnly? aria-label>` — `script`: paragraphs, bold, italic, bullet list; `document`: adds headings (H2/H3) and tables; `line`: single paragraph (workflow prompts). Toolbar per mode with icon buttons labelled "Bold", "Italic", "List", "Heading", "Table", "Variable", "Expression". `onChange` fires with the serialized string, debounced by the caller (not here).
- Chips render lowercase `[laugh]`, `[pause 1.2s]`, `{{lead.name}}` styled with the tint tokens; backspace deletes a chip whole; arrow keys move across it. Clicking a pause chip opens a small popover to change seconds (0.2–5, step 0.1).
- `ExpressionMenu`: the 8 built-ins with their hint as secondary text (from `GET /api/expressions`, falls back to the constant list), then the agent's custom expressions, then "New expression…" (only when `onCreateExpression` given) → `NewExpressionDialog` with "Name" (lowercase letters and underscores, ≤ 32, not a built-in: inline errors with the server's wording) and "How to say it" (≤ 200 chars). Choosing "pause" inserts `pause 1s`.
- `VariableMenu`: "Lead name" `lead.name`, "Lead city" `lead.city`, then "Other…" (input `lead.` + `[a-z_]+`). Note under the menu, muted: "Filled from the lead when the call has one; otherwise the agent says it without the name."
- Unknown expression names (not built-in, not custom) render with the bad tint and `title="Unknown expression"`.

- [ ] **Step 1: Write the failing tests**

```ts
it("parses and serializes every token kind", () => {
  const s = "[[expr:happy]]नमस्ते! [[expr:pause:1.2]]क्या मेरी बात {{lead.name}} जी से हो रही है?"
  expect(serialize(parse(s))).toBe(s)
  expect(parse(s).filter(t => t.kind !== "text")).toEqual([
    {kind:"expr", name:"happy"}, {kind:"expr", name:"pause", seconds:1.2}, {kind:"var", path:"lead.name"}])
})
it("treats malformed tokens as text", () => expect(parse("[[expr:Laugh]] {{lead}}")).toEqual([{kind:"text", text:"[[expr:Laugh]] {{lead}}"}]))
it("normalises spaces inside variables", () => expect(serialize(parse("{{ lead.city }}"))).toBe("{{lead.city}}"))
```
```tsx
it("round-trips Devanagari around chips", ...)   // value from the test above → render → onChange not called; fromEditor === value
it("inserts an expression from the menu at the cursor", ...) // click Expression ▾ → "laugh" → onChange gets "...[[expr:laugh]]..."
it("inserts pause with one second", ...)          // → "[[expr:pause:1]]"
it("creates a custom expression", ...)            // name "calm", hint → onCreateExpression("calm", "...") then chip [calm] inserted
it("rejects a built-in name for a custom expression", ...) // "laugh" → "\"laugh\" is a built-in expression; pick another name."
it("marks unknown expressions", ...)              // "[[expr:sing]]" → chip has title "Unknown expression"
it("keeps bold and lists as Markdown in script mode", ...) // "**Pune** only\n\n- one" round-trips
it("round-trips a knowledge table", ...)          // document mode, GFM table with ₹— cells
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** If `tiptap-markdown` changes whitespace on round-trip (trailing newline, `*` vs `-` lists), normalise in `fromEditor` so an untouched document reports no change; the round-trip tests are the contract.
- [ ] **Step 4: Run** `npm test` → pass, no warnings.
- [ ] **Step 5: Commit** `git commit -m "feat(console): token editor with expression and variable chips"`

---

### Task 6: Dashboard (screen 2)

**Files:**
- Create: `src/app/(console)/page.tsx`, `_components/{Readings,NeedsPerson,OutcomesWeek,LiveAgentLine}.tsx`
- Modify: `src/lib/queries.ts` (section "dashboard": `useDashboard()`, `useMarkHandled()`)
- Test: `src/app/(console)/page.test.tsx`

**Interfaces:**
- Consumes: `GET /api/dashboard` (`calls_today`, `connected_pct | null`, `interested`, `avg_duration_s | null`, `needs_person[]: {room, caller, reason, at}`, `outcomes_week[]: {outcome, count}`, `live_agent: {id, name, phone_number} | null`); `POST /api/calls/<room>/needs-person {handled: true}`.
- Top bar: title "Today", one amber "Open live calls" (→ `/live`).
- Row 1: one panel, four readings split by 1px rules: "Calls today", "Connected" (`81%` or `—`), "Interested", "Average call" (`formatDuration`). Labels above numbers, numbers large mono. No icons, arrows or sparklines.
- Row 2 left "Needs a person": rows of phone (mono, formatted), one-line reason (muted when empty: "No reason given"), time (`formatWhen`), amber text button "Call back" → marks handled, row leaves optimistically, toast "Marked as handled." with "Undo" (posts `handled: false`). Empty: "No one is waiting for a call back." Viewers see no button.
- Row 2 right "Outcomes this week": horizontal bars, width ∝ count / max, Interested bar `--blue`, the others `--rule-strong`; count in mono at the end. All zero → "No calls this week yet."
- Row 3: "Live agent" line: agent name, ok "Live" chip, phone (mono), text link "Manage agents" → `/agents`. `null` → "No agent is answering calls." + link "Publish an agent".
- Loading: skeleton blocks of the same size; error: one StateBlock for the whole page with retry.

- [ ] **Step 1: Write the failing tests** — `shows the four readings with dashes for missing values` (`connected_pct: null` → "—"), `call back marks the call handled and offers undo`, `hides call back for viewers`, `shows the empty states`, `shows no live agent line when none is published`, `shows an error with retry`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `git commit -m "feat(console): dashboard"`

---

### Task 7: Agents list (screen 3)

**Files:**
- Create: `src/app/(console)/agents/page.tsx`, `_components/{LivePanel,AgentsTable,PublishDialog}.tsx`
- Modify: `src/lib/queries.ts` (section "agents": `useAgents`, `useAgent(id)`, `useCreateAgent`, `useUpdateAgent(id)`, `usePublish`, `useUnpublish`, `useDuplicate`, `useArchive`, `useRestore`, `useExpressions`, `useVoices`)
- Test: `src/app/(console)/agents/page.test.tsx`

**Interfaces:**
- Consumes: `GET /api/agents` (`AgentListItem[]`), `POST /api/agents {name}` (201 detail), `POST /api/agents/<id>/{publish,unpublish,duplicate,archive,restore}`; publish 400 `{"errors": [...]}`, state actions 400 `{"detail"}`; `GET /api/dashboard` for "Calls today".
- Produces: the agents query hooks used by Task 8 (`useAgent`, `useUpdateAgent`, `usePublish`, `useExpressions`, `useVoices`). Every agent mutation invalidates `["agents"]`, `["agent", id]` and `["dashboard"]`.
- Top bar: "Agents", one amber "New agent" → `POST /api/agents {name: "Untitled agent"}` → `router.push(/agents/<id>)`.
- "Answering calls now" panel (only when an agent is `published`): name 22px, ok "Live" chip, phone (mono), "Calls today N", outlined "Unpublish" (confirm dialog: "Stop Driver lead qualifier answering calls? Callers will hear the built-in script until you publish an agent."), text link "Open". When none is published: "No agent is answering calls. Callers hear the built-in script." (that is what plan 2 does).
- Tabs All / Live / Drafts / Archived (filter client-side on `status`; All excludes archived).
- Table (5 columns, 56px rows): Agent (name + muted description, one line, truncated), Status chip (Live ok, Draft neutral, Archived muted; plus amber "Older version" chip when `is_outdated`), Last edited (`timeAgo(updated_at)` + `updated_by_name` in amber), Calls this week (mono), actions: outlined "Publish" on drafts (and "Republish" when the live agent `is_outdated`), "…" menu: Open, Duplicate, Archive (non-published) or Restore (archived), Unpublish (published).
- `PublishDialog`: when another agent is live, "Publish Callback follow-up? Driver lead qualifier will stop answering calls." Otherwise "Publish Callback follow-up? It will answer the next call." Publish errors render as a list inside the dialog under "Fix these first:".
- Empty states per tab ("No drafts."), loading skeleton rows, error StateBlock.

- [ ] **Step 1: Write the failing tests** — `publish dialog names the live agent it replaces`, `publish errors are listed in the dialog`, `new agent creates and opens the editor`, `tabs filter by status and All hides archived`, `shows the outdated chip and Republish`, `archive and restore from the menu`, `viewer sees no publish or menu actions`, `shows built-in script note when nothing is live`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `git commit -m "feat(console): agents list with publish, unpublish, duplicate, archive"`

---

### Task 8: Agent script editor and Test call (screen 4)

**Files:**
- Create: `src/app/(console)/agents/[id]/page.tsx`, `_components/{ScriptDocument,SectionEditor,SidePanel,VoiceSection,KnowledgeSection,BehaviourSection,AdvancedSection,AttachKnowledgeDialog,SaveStatus}.tsx`, `src/components/sim/Simulator.tsx`, `src/lib/useAutosave.ts`
- Modify: `src/lib/queries.ts` (section "knowledge": `useKnowledgeList()`; section "workflows": `useWorkflows()`; section "sim": `useSimulate(kind: "agent" | "workflow", id)`)
- Test: `src/app/(console)/agents/[id]/page.test.tsx`, `src/components/sim/Simulator.test.tsx`, `src/lib/useAutosave.test.ts`

**Interfaces:**
- Consumes: `useAgent`, `useUpdateAgent`, `usePublish`, `useExpressions`, `useVoices` (Task 7), `TokenEditor` (Task 5), `PATCH /api/agents/<id>` (partial: `name`, `description`, `phone_number`, `persona_name`, `voice_id`, `settings` (deep-merged server-side), `script`, `custom_expressions`, `knowledge`, `workflow`), `POST /api/agents/<id>/simulate {messages, state}` → `SimResponse`; 503 `{"detail": "The test simulator isn't running."}`, 502 `{"detail": "The test simulator failed."}`.
- Produces: `useAutosave<T>(value: T, save: (v: T) => Promise<unknown>, delayMs = 800) → {status: "idle" | "saving" | "saved" | "error", error?: ApiError, flush(): Promise<void>}` — one save in flight at a time; changes made while saving are saved next; `flush` saves now and resolves when done. `<Simulator kind id title onClose>` used by Task 10.
- Top bar: breadcrumb "Agents / {name} / Script" (name is an inline-editable text button; Enter or blur saves), status chip (Draft / Live / Archived), `SaveStatus` text ("Saving…", "Saved", or the error), outlined "Test call", one amber "Publish" (or "Republish" when live and `is_outdated`; disabled with tooltip "Up to date" when live and not outdated). Publish = `flush()` then `PublishDialog` from Task 7.
- Banner when `status === "published" && is_outdated`: "Uses an older version. Callers hear the last published version until you republish."
- Main panel: the script as one clean document, 16px, sections separated by thin rules; each section has a plain heading input ("Greeting") and a `TokenEditor mode="script"`; section "…" menu: Move up, Move down, Delete (confirm when the body isn't empty). "+ Add section" at the end (new section `{id: crypto.randomUUID(), title: "New section", body: ""}`). Any change autosaves the whole `script` array.
- Side panel 320px, rule-separated, in this order:
  - "Voice": "Agent's name" field (`persona_name`), voice dropdown from `useVoices()` labelled `{name}, {description}` with first option "Default for this line" (`""`), outlined "Preview" (plays `sample` with an `<audio>` element; hidden when the voice has no sample); muted note "Voices for {pipeline label}." (`gemini-live` → "Gemini Live", `sarvam` → "Sarvam", `elevenlabs` → "ElevenLabs").
  - "Knowledge": linked docs as plain rows (title only, no counts), each with a remove "×" (aria-label "Remove {title}"), + "Attach" → `AttachKnowledgeDialog` (checkbox list of `useKnowledgeList()`), saves `knowledge` ids. Muted line: "The agent only quotes what is written in these documents."
  - "Workflow": dropdown of `useWorkflows()` with first option "None, script only"; link "Open workflow" when set.
  - "Behaviour": switch "Adjust to caller's mood" (`settings.mood_adaptation`); switch "Check in when the caller goes quiet" (`settings.dead_air.enabled`).
  - "Advanced" (`Disclosure`, collapsed): "Phone number" (mono input, `phone_number`), dead-air timings "First check-in after (s)", "Second check-in after (s)", "Hang up after (s)" (numbers; server error "Dead-air timings must increase…" shown under the group), "Pipeline" read-only text from `useVoices().pipeline`, "Description" textarea.
- Expressions: `customExpressions = agent.custom_expressions`; `onCreateExpression` PATCHes `custom_expressions` with the new entry before inserting the chip.
- Signed-out autosave (`isSignedOut`): keep local state, stop autosaving, show "You were signed out. Sign in again to keep your changes." with a link to `/sign-in?next=/agents/<id>`; the text stays in a `sessionStorage` draft (`cv-draft-agent-<id>`, try/catch) that the page offers to restore ("Restore unsaved changes") on next load when it differs from the server.
- Viewer: everything read-only, no Publish/Test call.
- `Simulator` (a 420px `SlideOver` titled "Test call" / "Try it"): note "Type as the caller. Nothing is saved and nobody is called."; on open sends `{messages: [], state: null}` to get the agent's opening line; transcript with "Caller" (amber label) and "Agent" (blue label) lines, agent text rendered with expression chips when it contains tokens; under the header the current step ("Step: Explain the plan", amber) when `step` is non-null; input + "Send" (Enter sends, Shift+Enter newline, max 2000 chars); `ended: true` → "The call ended." with outcome label from `DISPOSITIONS` and "Start again". Errors: show `detail` above the input, keep the typed text, "Try again" resends.

- [ ] **Step 1: Write the failing tests**

```ts
// useAutosave.test.ts
it("debounces and saves the latest value once", ...)        // 3 changes in 500ms → 1 save with the last value after 800ms
it("queues a change made during a save", ...)
it("flush saves immediately", ...)
```
```tsx
// page.test.tsx
it("loads sections into editors and autosaves edits", ...)  // type in Greeting → PATCH {script:[...]} after 800ms, "Saved"
it("adds, reorders and deletes sections", ...)
it("publish flushes pending edits first", ...)               // PATCH resolves before POST /publish
it("keeps the draft and shows the signed-out message when autosave gets a signed-out 403", ...)
it("picks a voice and previews it", ...)                    // PATCH {voice_id:"Puck"}; audio src "/voices/puck.wav"
it("shows the server's dead-air error under the timings", ...)
it("attaches and removes knowledge", ...)                   // PATCH {knowledge:[1,2]} then [2]
it("creates a custom expression and saves it on the agent", ...)
it("shows the older-version banner and Republish", ...)
it("is read-only for viewers", ...)
// Simulator.test.tsx
it("opens with the agent's first line", ...)                // POST {messages:[],state:null} → reply shown as Agent
it("sends caller text with the previous state", ...)        // second POST carries state from first reply
it("shows the current step", ...)
it("shows the simulator-down message and keeps the typed text", ...) // 503
it("shows the end of the call with the outcome", ...)       // ended:true, outcome {disposition:"INTERESTED"} → "Interested"
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `git commit -m "feat(console): agent script editor, side panel and test call simulator"`

---

### Task 9: Knowledge base (screen 6)

**Files:**
- Create: `src/app/(console)/knowledge/page.tsx`, `_components/{DocList,DocEditor,VersionHistory,UploadButton}.tsx`
- Modify: `src/lib/queries.ts` (section "knowledge": `useKnowledgeDoc(id)`, `useCreateDoc`, `useSaveDoc(id)`, `useUploadDoc`, `useRevisions(id)`, `useRevision(id, n)`)
- Test: `src/app/(console)/knowledge/page.test.tsx`

**Interfaces:**
- Consumes: `GET /api/knowledge` (`{id, title, updated_at, current_revision, used_by}[]`), `POST /api/knowledge {title, body_md}`, `GET|PATCH /api/knowledge/<id>`, `POST /api/knowledge/upload` (multipart field `file`; 400 details: "Attach a .md file in the 'file' field.", "Only .md (Markdown) files are supported.", "File is too large; the limit is 1 MB.", "File must be UTF-8 text."), `GET /api/knowledge/<id>/revisions` (`{number, edited_by, created_at}[]`), `GET /api/knowledge/<id>/revisions/<n>` (+ `body_md`).
- Selected doc in the URL: `/knowledge?doc=<id>` (first doc when absent).
- Top bar: "Knowledge base", outlined "Upload .md", one amber "Save" (disabled until there are unsaved changes; Ctrl/Cmd+S saves). Saving does not autosave here: documents change what agents quote, so saving is deliberate.
- Left 260px: "+ New document" at top (creates "Untitled document" and selects it), rows with title and muted "Used by N agents" ("Not used by any agent" at 0, "Used by 1 agent"); selected row has the amber left edge.
- Main (max 760px, centred): title input (24px); toggle "Rich text | Markdown" (`Segmented`); `TokenEditor mode="document"` in Rich text, a monospace `<textarea>` with the raw Markdown in Markdown mode (both edit the same string); pale amber note "The agent only quotes what is written here."; footer "Last edited by {edited_by of the newest revision}, {formatWhen}" (name in amber) + text button "Version history".
- `VersionHistory` SlideOver: revisions newest first ("Version 4", editor, time — the word "version" is fine here; no ids); selecting one shows its body read-only in a TokenEditor and a button "Restore this version" → loads that body into the editor as an unsaved change (user then Saves).
- Unsaved changes: switching docs or leaving the page asks "Discard unsaved changes to {title}?" (`beforeunload` + in-app confirm).
- After save, toast: when `used_by > 0`, "Saved. Agents using this document need republishing before callers hear the change." else "Saved."

- [ ] **Step 1: Write the failing tests** — `selects the first document and shows its body`, `save sends title and markdown and shows the republish hint`, `switching documents with unsaved changes asks first`, `markdown mode edits the same text`, `upload selects the new document`, `upload shows the API's file error`, `restores an old version as an unsaved change`, `new document is created and selected`, `empty workspace shows "No documents yet" with New document`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `git commit -m "feat(console): knowledge base editor with markdown, upload and version history"`

---

### Task 10: Workflows list and builder (screen 5)

**Files:**
- Create: `src/app/(console)/workflows/page.tsx`, `src/app/(console)/workflows/[id]/page.tsx`, `src/components/workflow/{Canvas.tsx,StepNode.tsx,StepPanel.tsx,AddStepMenu.tsx,graph.ts,layout.ts,workflow.module.css}`
- Modify: `src/lib/queries.ts` (section "workflows": `useWorkflow(id)`, `useCreateWorkflow`, `useSaveWorkflow(id)`)
- Test: `src/components/workflow/graph.test.ts`, `src/components/workflow/layout.test.ts`, `src/app/(console)/workflows/[id]/page.test.tsx`, `src/app/(console)/workflows/page.test.tsx`

**Interfaces:**
- Consumes: `GET /api/workflows` (`{id, name, updated_at, current_revision}[]`), `POST /api/workflows {name}`, `GET /api/workflows/<id>` (`{id, name, updated_at, current_revision, graph, errors: string[]}`), `PATCH /api/workflows/<id> {name?, graph?}` (returns the same detail with fresh `errors`), `<Simulator kind="workflow">` (Task 8), `TokenEditor mode="line"` (Task 5), `useKnowledgeList` (Task 8), `DISPOSITIONS` (Task 3).
- `graph.ts` (pure): `toFlow(graph: Graph, selectedId?: string) → {nodes, edges}` (edges get `id = p.id ?? \`${from}->${to}:${label}\``; paths whose `from` or `to` step is missing are left out); `edgeTone(path, steps) → "ok" | "amber" | "bad" | "neutral"` (to an `end` step whose outcome group is Interested → ok; Call back → amber; to a `transfer` step → bad; else neutral); `addStep(graph, type, near?: Step) → {graph, step}` (id = slug of the default name + short random suffix, position 220px below `near` or the lowest step); `removeStep(graph, id)` (also removes its paths; refuses to remove the only `start` step); `addPath(graph, from, to, label)`, `updatePath`, `removePath`; `stepSays(step) → string` (the prompt rendered as plain text with chips shown as `[laugh]`, first line only, for the card).
- `layout.ts`: `layoutMissing(graph) → Graph` — when any step lacks `position`, run dagre (`rankdir: "TB"`, `nodesep: 48`, `ranksep: 72`, node 260×88) over all steps and fill only the missing positions.
- Workflows list (`/workflows`): top bar "Workflows", one amber "New workflow" (creates "Untitled workflow" with graph `{steps: [{id:"start", type:"start", name:"Greeting", prompt:"", position:{x:0,y:0}}], paths: []}` and opens it); table: Name, Last edited (`timeAgo`), Used by (agents whose `workflow` is this id, from `useAgents()`; "Not used"), "…" menu Open. Empty: "No workflows yet. A workflow splits a call into steps, each with its own prompt."
- Builder top bar: breadcrumb "Workflows / {name}" (inline-editable name), outlined "Try it" (`Simulator kind="workflow"`; tries the **saved** revision, so it flushes first), one amber "Save". Save PATCHes `{graph}`; the response's `errors` show in a panel "Fix these before an agent can use this workflow:" (list; clicking an error that names a step selects it). Save also toasts "Saved. Agents using this workflow need republishing before callers hear the change." when any agent uses it. No autosave; unsaved-changes guard as in Task 9.
- Canvas: React Flow with a faint dot grid (`Background variant="dots"`, colour `--rule-strong` at low opacity), `fitView` on load (whole flow visible, nothing clipped, padding 0.15), zoom controls bottom-right, "+ Add step" button bottom-left opening `AddStepMenu`: "Say something" (prompt), "Collect an answer" (collect), "Answer from knowledge" (knowledge), "Transfer to a telecaller" (transfer), "End the call" (end). Step cards 260px wide, 1px border, 15px title, one muted line of what the agent says; selected card has an amber 2px outline; type shown as a small muted word ("Start", "Collect", "End: Interested") under the title, never an icon soup. Edges are thin smoothstep lines with short labels, coloured by `edgeTone` (`--ok`, `--amber`, `--bad`, `--rule-strong`). Dragging a card stores its new `position`. Connecting two handles adds a path labelled "New path" and selects the source step so the label can be edited. Delete/Backspace on a selected step asks to confirm.
- Side panel 340px (selected step): "Step name"; "What the agent says" (`TokenEditor mode="line"` with Expression ▾); type-specific: collect → "Save the answer as" (field name; inline hint "Lowercase letters, digits and underscores"), knowledge (and prompt, optional) → "Use knowledge" dropdown (`knowledge_id`), end → "Outcome" select grouped by display outcome showing `DISPOSITIONS` labels, transfer → muted "Hands the caller to the telecalling team."; "Then go to" rows: label input + target step select + remove, then "Add path" (hidden for end steps); "Advanced" disclosure: "Step type" (change type; start only when there is no other start) and "Delete step". Empty selection: "Select a step to edit it."
- Viewers: canvas read-only (no drag/connect), panel read-only, no Save/Add.

- [ ] **Step 1: Write the failing tests**

```ts
// graph.test.ts
it("colours paths by where they lead", ...)        // → end INTERESTED ok, end CBR amber, transfer bad, prompt neutral
it("drops paths to missing steps from the canvas and shows the server error", ...) // toFlow omits; page lists errors[0]
it("removing a step removes its paths and keeps the only start", ...)
it("adds a step below its neighbour with a unique id", ...)
// layout.test.ts
it("lays out steps that have no position", ...)   // 3 steps no position → 3 distinct positions; a step with position keeps it
```
```tsx
// [id]/page.test.tsx
it("renders the seeded onboarding graph with every step visible", ...) // 9 step titles present
it("edits a step's prompt and saves the whole graph", ...)             // PATCH body graph.steps[i].prompt contains "[[expr:excited]]"
it("adds a path from the side panel", ...)
it("shows save errors and selects the step an error names", ...)
it("end steps choose an outcome from the 14 codes", ...)
it("try it flushes unsaved changes first", ...)                       // PATCH before POST /api/workflows/<id>/simulate
it("is read-only for viewers", ...)
// page.test.tsx (list)
it("lists workflows with who uses them", ...)
it("new workflow opens the builder", ...)
```
  React Flow in jsdom needs `ResizeObserver` and `DOMMatrixReadOnly` stubs in `vitest.setup.ts`; drag/connect behaviour is covered by `graph.ts` tests and the Playwright smoke run, not jsdom.

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `git commit -m "feat(console): workflow list and builder canvas with step panel and try it"`

---

### Task 11: Live calls (screen 7)

**Files:**
- Create: `src/app/(console)/live/page.tsx`, `_components/{LiveList,LiveCallView,StepLine,Transcript,Details}.tsx`, `src/components/Transcript.tsx` (shared with Task 12)
- Modify: `src/lib/queries.ts` (section "live": `useTransfer`, `useEndCall`)
- Test: `src/app/(console)/live/page.test.tsx`, `src/components/Transcript.test.tsx`

**Interfaces:**
- Consumes: `useLiveCalls(2000)` (Task 4) → `LiveCall[]` (`room, caller, city, started_at, current_step, mood, transcript_tail[]: {speaker, text, expressions, at}, step_path, captured`); `POST /api/live/<room>/transfer` (409 "Live transfer isn't set up.", 404 "This call isn't live." / "No caller on this call.", 502 "Couldn't reach the call server." / "The call server refused that; try again."), `POST /api/live/<room>/end`.
- Produces: `<Transcript lines={…}/>` — "Caller" label amber, "Agent" label blue, 15px text, expression chips (from `expressions`, rendered with Task 5's chip style) before the agent's line; auto-scrolls to the newest line only when the reader is already at the bottom.
- Top bar: "Live calls" (no primary: the screen's actions are per call; the End call button is red-outline, Transfer outlined).
- Left 300px: one row per call: phone (mono), city (muted, "—"), elapsed (`formatElapsed`, ticking every second, mono), one-word mood chip (labels capitalised; frustrated/angry/upset → bad, interested/happy/positive → ok, else neutral; no chip when empty). Selected row (URL `?room=`; first call when absent) has the amber left edge.
- Main: header with phone (mono 20px), city, big mono timer, outlined "Transfer to a telecaller" (confirm: "Transfer this caller to the telecalling team?"), red-outline "End call" (confirm: "End this call now? The caller will be disconnected."). Results toast the API `detail`. Then the step line: `step_path` items, past ones with a ✓ in muted ink, the last (= current) in amber; nothing when empty. Then `<Transcript>` of `transcript_tail`. Then a collapsible "Details" (`Disclosure`, open by default): `captured` as label/value rows using the answer labels from Task 12 (`ANSWER_LABELS`).
- A call that disappears from the list while selected: keep its last state greyed with the line "This call has ended." and a link "Open in call history" (`/calls?room=<room>`).
- Empty: "No calls right now. Calls show up here as soon as someone calls {live agent phone or 'your number'}." Loading: skeleton. Error (LiveKit down → API 500/502): "Couldn't reach the call server." + retry; polling continues.
- Viewers: no Transfer/End buttons.

- [ ] **Step 1: Write the failing tests** — `polls and shows new transcript lines`, `selects the first call and switches by click`, `step line marks the current step in amber`, `transfer confirms and shows the API message` (409 text), `end call confirms and posts`, `keeps an ended call visible with a history link`, `hides actions for viewers`, `empty and error states`; Transcript: `labels caller and agent and renders chips`.
- [ ] **Step 2: Run** → FAIL (use Vitest fake timers for polling and the elapsed clock). **Step 3: Implement.** **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `git commit -m "feat(console): live calls with transcript, steps, details, transfer and end"`

---

### Task 12: Call history (screen 8)

**Files:**
- Create: `src/app/(console)/calls/page.tsx`, `_components/{Filters,CallsTable,CallSlideOver,DateRange}.tsx`, `src/lib/answers.ts`
- Modify: `src/lib/queries.ts` (section "calls": `useCalls(filters)`, `useCall(room)`, `useMarkNeedsPerson`)
- Test: `src/app/(console)/calls/page.test.tsx`, `src/lib/answers.test.ts`

**Interfaces:**
- Consumes: `GET /api/calls?q&outcome&agent&mood&city&from&to&page` → `{results: CallRow[], count, page, pages}` (page size 25; 400 field errors on bad filters); `GET /api/calls/<room>` → `CallDetail` (`…CallRow, reason, answers, step_path, transcript, recording_url`); `GET /api/calls/export.csv?<same filters>`; `POST /api/calls/<room>/needs-person {needs_person: true}` (Task 1); `useAgents()` for the Agent filter; `<Transcript>` (Task 11).
- Produces: `src/lib/answers.ts`: `ANSWER_LABELS = {callback_time: "Call back at", city: "City", licence: "Licence", experience: "Experience", uber_id: "Uber ID", preferred_plan: "Preferred plan", main_question: "Main question"}`; `answerLabel(key)` falls back to sentence-casing the key (`driving_years` → "Driving years").
- All filter state lives in the URL query (shareable, back button works). Defaults: last 7 days (`from` = today − 6 in the user's time zone, `to` = today).
- Top bar: "Call history", date control (`DateRange`: Today, Last 7 days, Last 30 days, Custom with two date inputs), outlined "Export" (an `<a download>` to `/api/calls/export.csv?…`). No amber primary in the page (the slide-over has one).
- Filters row: search "Search by phone number" (debounced 300ms → `q`), "Outcome" select (five groups + "Any outcome"), "Agent" select (+ "Any agent"), button "More filters" toggles a row with "Mood" and "City" text fields. "Clear filters" text button when any filter is set.
- Table (6 columns, 52px rows): When (`formatWhen`), Caller (mono), Outcome chip (tone from `outcomeTone`; empty outcome → muted "—"), Mood (plain text, capitalised, "—"), Duration (mono `formatDuration`), Summary (one truncated line, muted "No summary" when empty). Rows are buttons (Enter opens). Pagination: "Page 2 of 7" with Previous/Next.
- `CallSlideOver` (420px, `?room=`): phone (mono 20px), outcome chip, when; audio player only when `recording_url` is non-null; "What happened" (summary, else reason, else "No summary for this call."); "Steps" (step path as one muted line joined with " → "; hidden when empty); "Answers" label/value rows (hidden when empty); "Transcript" (`<Transcript>`; empty: "No transcript. Transcripts are kept for 90 days."); footer one amber "Mark for call back" → `needs_person: true`; on success the button is replaced by the text "Marked for a call back. It shows on the dashboard under Needs a person." (The detail response doesn't say whether a call is already marked, so the button is always offered; marking twice is harmless.) Viewers: no footer button.
- Empty results: "No calls match these filters." + "Clear filters"; workspace with no calls at all: "No calls yet." Error with retry; a 400 filter error shows next to the filters.

- [ ] **Step 1: Write the failing tests** — `defaults to the last 7 days in the URL and request`, `search debounces into q`, `outcome and agent filters update the URL and request`, `export link carries the same filters`, `opens the slide-over from a row and the URL`, `slide-over hides the player without a recording`, `mark for call back posts needs_person`, `paginates`, `shows empty, filtered-empty and error states`, `answer labels fall back to sentence case`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `git commit -m "feat(console): call history with filters, export and call slide-over"`

---

### Task 13: Settings and Integrations (screens 9 and 10)

**Files:**
- Create: `src/app/(console)/settings/{page.tsx,layout.tsx,_components/SettingsNav.tsx,_components/PasswordDialog.tsx}`, `src/app/(console)/settings/team/page.tsx`, `src/app/(console)/settings/phone-numbers/page.tsx`, `src/app/(console)/integrations/{page.tsx,_components/RequestDialog.tsx}`
- Modify: `src/lib/queries.ts` (sections "team": `useTeam`, `useInvite`, `useSetRole`; "numbers": `usePhoneNumbers`; "integrations": `useRequestIntegration`)
- Test: `src/app/(console)/settings/page.test.tsx`, `team/page.test.tsx`, `phone-numbers/page.test.tsx`, `src/app/(console)/integrations/page.test.tsx`

**Interfaces:**
- Consumes: `GET|PATCH /api/me` (`{name?, phone?, preferences?: {appearance, notify_needs_person, notify_daily_summary, time_zone}}`), `POST /api/me/password {current_password, new_password}` (field errors), `GET /api/team` (`{id, name, email, role, last_login}[]`), `POST /api/team {email, name, role}` → `{set_password_url}` (a path; show as `${location.origin}${set_password_url}`), `PATCH /api/team/<id> {role}` (403 "Only an owner can do that."), `GET /api/phone-numbers` (`{number, trunk_name, agent_name}[]`), `POST /api/integrations/requests {tool, note}`.
- Settings layout: left 220px nav: Profile (`/settings`), Team, Phone numbers, Appearance (`/settings#appearance`, scrolls to the section), Billing (disabled, muted "Soon" chip).
- Profile page (max 720px, one panel with rule-separated sections): "Profile": initials avatar (no upload in this release, so no "Change" button), "Full name", "Work email" (read-only, muted note "Ask an owner to change your email."), text button "Change password" → `PasswordDialog` (current, new, confirm; client checks match; server errors under fields; success toast "Password changed."), "Phone" (mono), "Time zone" select (`Intl.supportedValuesOf("timeZone")`, default Asia/Kolkata). "Appearance" (`id="appearance"`): `Segmented` "Light | Dark | Match system" applied instantly (preview) and saved with the form; note "Switch the console between light and dark." "Notifications": switches "Email me when a call needs a person", "Send a daily summary" (muted note: "Emails start once email sending is set up." — the server stores the preference; sending isn't built). Footer: outlined "Cancel" (resets, including the previewed theme), one amber "Save changes" (disabled when nothing changed).
- Team page: table Name, Email, Role (select for owner/admin viewers of the page, else text; "Owner" option only for owners; you can't change your own role), Last signed in (`timeAgo`, "Never"); top-bar amber "Invite someone" (owner/admin only) → dialog (Name, Work email, Role) → shows the link with "Copy link" and the note "Send this link to {name}. It works once." Others see no button.
- Phone numbers page: table Number (mono), Line (trunk_name), Answered by (agent name or muted "No agent"); muted note "Numbers are set up by your admin." Empty: "No numbers found on the call server." Error: "Couldn't reach the call server."
- Integrations (screen 10): title "Integrations", one amber "Request an integration"; muted line "Connect your agents to the tools your team already uses. These are coming soon."; table 3 columns, roomy rows: Integration (monochrome lucide icon + name), What it will do, Status (muted "Coming soon" chip). Rows (exact): Google Sheets "Add each call as a row" (Sheet icon); Webhooks "Send an event when a call ends" (Webhook); WhatsApp Business "Send details after a call" (MessageCircle); Salesforce "Update the lead with the outcome" (Cloud); HubSpot "Sync contacts and outcomes" (Users); LeadSquared "Update leads" (ListChecks); Slack "Alert a channel when a call needs a person" (Hash); Your own phone number (SIP) "Bring your existing number" (Phone). No logos, no connect buttons. `RequestDialog`: "Which tool?" (text, required, ≤100), "What should it do?" (textarea, ≤2000) → POST → toast "Request sent." Integrations stays reachable for viewers (requesting is allowed for members — check `IntegrationRequestView` permissions; if editors only, hide the button for viewers).

- [ ] **Step 1: Write the failing tests** — profile: `saves name, phone, time zone and notification switches in one PATCH`, `appearance previews instantly and Cancel restores it`, `change password shows the server's field error`, `save is disabled until something changes`; team: `owner sees Owner in the role picker, admin doesn't`, `invite shows the full set-password link`, `editor sees no invite button`, `role change shows the owner-only error`; phone numbers: `lists numbers with their agent and the empty state`; integrations: `lists the eight coming-soon integrations`, `request posts tool and note`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `git commit -m "feat(console): settings (profile, appearance, notifications, team, numbers) and integrations"`

---

### Task 14: End-to-end smoke run against the real API

**Files:**
- Create: `console/playwright.config.ts`, `console/e2e/smoke.spec.ts`, `scripts/console-e2e.sh`
- Modify: `Makefile` (`console-e2e`), `README.md` (how to run the console locally)

**Interfaces:**
- `scripts/console-e2e.sh`: requires `make test-db` (Postgres on 127.0.0.1:55432); drops and creates database `console_e2e`; runs Django with `POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55432 POSTGRES_DB=console_e2e POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres DASHBOARD_PORT=8788` (`migrate`, `seed_carrum`, then a `manage.py shell -c` snippet creating owner `e2e@carrum.test` with password `$E2E_PASSWORD`, default a random value generated by the script and exported to Playwright), then `uvicorn`/`runserver` on 127.0.0.1:8788; builds and starts Next with `DJANGO_URL=http://127.0.0.1:8788` on port 3100; runs `npx playwright test`; kills both servers on exit (trap). LiveKit and the simulator are not running: the smoke run asserts the console handles that.
- `smoke.spec.ts`, one test per screen, light theme, plus one dark pass:
  1. Sign in with the e2e user → lands on "Today"; readings show `0`/`—`.
  2. Agents: "Driver lead qualifier" with "Live"; open it; Greeting section shows the seeded Devanagari text; insert `[laugh]` via Expression ▾; "Saved" appears; reload → the chip is still there.
  3. Test call → "The test simulator isn't running."
  4. Knowledge: edit a document, Save → toast; Version history lists two versions.
  5. Workflows: "Driver onboarding" opens; all 9 step titles visible inside the viewport; select "Explain the plan"; side panel shows the `[excited]` chip; Save → no errors panel.
  6. Live calls → "Couldn't reach the call server." (LiveKit down) or the empty state; no crash.
  7. Call history → "No calls yet."; Export link has `from=`/`to=`.
  8. Settings → Appearance Dark → Save → `html[data-theme=dark]`; reload keeps it; screenshot each of the ten screens in dark into `test-results/dark/` for the human check.
  9. Integrations → eight rows; Sign out → back on Sign in; visiting `/agents` redirects to `/sign-in?next=%2Fagents`.

- [ ] **Step 1: Write** the config, script and spec.
- [ ] **Step 2: Run** `make test-db && make console-e2e` → every test passes. Fix console bugs it finds in the owning screen's files (with a unit test for each fix) — note each in the report.
- [ ] **Step 3: Visual check** — open the `test-results/` screenshots (light from the per-screen tests, dark from step 8) next to `docs/superpowers/specs/assets/stitch/NN-*.png`; fix gross departures from the layout rules (column count, primary button count, chip colours, fonts) and list remaining differences in the report.
- [ ] **Step 4: Commit** `git commit -m "test(console): end-to-end smoke run against the real API"`

---

### Task 15: Console container and deploy wiring

**Files:**
- Create: `console/Dockerfile`, `console/.dockerignore`
- Modify: `docker-compose.yml` (service `console`), `scripts/deploy.sh`, `scripts/tests/test-deploy-rollback.sh`, `Makefile` (`tunnel`), `README.md`, `.env.example` (`CONSOLE_URL`), `docs/superpowers/plans/2026-11-05-carrum-voice-console-roadmap.md` (plan 3 outcome; plan 4 shrinks to recording + purge schedule + transfer test)

**Interfaces:**
- `console/Dockerfile`: multi-stage `node:22.11-alpine`: `deps` (`npm ci`), `build` (`ARG DJANGO_URL=http://127.0.0.1:8787`, `npm run build`), `run` (non-root `node` user, copies `.next/standalone`, `.next/static`, `public`; `ENV PORT=3000 HOSTNAME=127.0.0.1 NODE_ENV=production`; `CMD ["node", "server.js"]`). Image under 250 MB.
- Compose: `console: {build: ./console, image: ai-calling-console:local, network_mode: host, restart: unless-stopped, depends_on: [dashboard], environment: {PORT: "3000", HOSTNAME: 127.0.0.1}}`. Listens on 127.0.0.1 only, like the dashboard.
- `scripts/deploy.sh`: builds and starts `console` with the other services; after `wait-dashboard`, waits up to 60 s for `curl -fsS -o /dev/null http://127.0.0.1:3000/sign-in` on the VM, else fails the deploy (and the existing rollback path runs). Rollback brings `console` up only when the rolled-back tree has a `console` service (same pattern as `agent-sim`).
- `make tunnel`: forwards both `-L 3000:127.0.0.1:3000 -L 8787:127.0.0.1:8787` and prints "Console: http://localhost:3000".
- README "Console": local dev (`make console-dev` with the dashboard running), tests, e2e, deploy, first sign-in (create the first owner with `docker compose exec dashboard python manage.py create_member you@carrum.co.in --name "…" --role owner`).

- [ ] **Step 1: Write the failing script test** — extend `scripts/tests/test-deploy-rollback.sh` with stubbed cases: `deploy waits for the console and fails when it never answers`; `rollback skips console when the old tree has no console service`.
- [ ] **Step 2: Run** `scripts/tests/test-deploy-rollback.sh` → FAIL.
- [ ] **Step 3: Implement.** Then build locally: `docker build -t ai-calling-console:local console` → succeeds; `docker run --rm --network host ai-calling-console:local` serves `/sign-in` 200.
- [ ] **Step 4: Run** `make test` → everything passes (agent, dashboard, console, scripts).
- [ ] **Step 5: Commit** `git commit -m "feat: console container, deploy wiring and tunnel on port 3000"`

**Not in this task:** running the production deploy. After the branch is merged, the controller asks the user before `scripts/deploy.sh` (it also ships plan 2 to production for the first time; run the plan 2 staging checklist items that need a real call right after, with `ROLLBACK=1 make deploy` ready).
