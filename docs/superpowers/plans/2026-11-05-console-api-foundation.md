# Console API foundation — implementation plan (1 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Django REST API that the Next.js console (plan 3) and the voice agent (plan 2) build on: workspaces and roles, login, preferences, knowledge documents, workflows, agents with publish snapshots, runtime config/events for the agent, call/live/dashboard data, retention and seed data — with the existing dashboard still working.

**Architecture:** New Django apps inside `dashboard/` (`workspaces`, `knowledge`, `workflows`, `voiceagents`, `runtime`) plus extensions to `calls`. JSON over Django REST Framework with session auth for people and the existing LiveKit-signed JWT for the agent. Everything is scoped to a `Workspace`; a data migration creates "Carrum Mobility" and assigns existing calls to it.

**Tech Stack:** Python 3.12, Django 5.2.18, djangorestframework 3.15.2 (new), PostgreSQL 16 via psycopg 3 (replacing SQLite, Task 1b), pytest + pytest-django, livekit-api 1.2.1.

**Spec:** `docs/superpowers/specs/2026-11-05-carrum-voice-console-design.md` (roadmap: `docs/superpowers/plans/2026-11-05-carrum-voice-console-roadmap.md`).

## Global Constraints

- All new tables carry `workspace` (FK, `on_delete=CASCADE`); every API queryset filters by the requester's workspace. Only "Carrum Mobility" exists; no signup endpoint.
- Roles: `owner`, `admin`, `editor`, `viewer`. Viewers read only; editors edit and publish; admins/owners also manage team.
- Only publishing an **agent** changes what callers hear. A call keeps the `AgentVersion` it started with. Only **one published agent per workspace**.
- Agent→API authentication: LiveKit-signed JWT exactly as `report_ingest` does today (`api.TokenVerifier`); runtime identity is `agent-runtime` (reports keep `agent-report`).
- Existing endpoints and behaviour unchanged: `/webhook`, `/api/state`, `/api/report`, `/api/report/<room>`, `/` (old dashboard), admin.
- Outcome codes are the 14 fixed dispositions: `INTERESTED NI NE CBR CDRP ISUDO ISUID HND WRGN OWNVA ABULR LANGUAGE_BARRIER NOT_CONNECTED UNRESOLVED`. Display groups: Interested ← INTERESTED; Call back ← CBR; Not interested ← NI, NE, ISUDO, ISUID, OWNVA, ABULR, WRGN, LANGUAGE_BARRIER, HND; Dropped ← CDRP, UNRESOLVED; Not reached ← NOT_CONNECTED.
- Expressions (exact set): `happy laugh sad fear angry whisper pause excited` plus user-defined custom expressions; tokens stored as `[[expr:<name>]]` or `[[expr:pause:<seconds>]]`; variables `{{lead.<field>}}`.
- Retention: transcripts (`CallEvent` turn rows, `TurnLabel` text, report `turns`) older than **90 days** are deleted; outcomes, summaries, answers and metrics stay.
- Never invent figures: seed data and fixtures contain no prices; knowledge seed comes only from `agent/knowledge.md` if present.

## Review Focus

1. **Cross-workspace access** — a user of workspace A requesting an id from workspace B must get 404, never the object. Pinned in Task 1 (`test_other_workspace_is_404`) and reused per resource.
2. **Number with no published agent / unknown number** — `/api/runtime/config` must answer 404 with a JSON reason (the agent then falls back), not 500. Task 7.
3. **Publishing a broken workflow** (no start step, a path to a missing step, an end step without an outcome, an unreachable step) — publish refused with readable errors. Tasks 5 and 6.
4. **Events arriving before the call row exists, duplicates and out-of-order sequence numbers** — stored idempotently by `(room, seq)`, listed in `seq` order. Task 7.
5. **Concurrent publish of two agents** — exactly one ends up published (transaction + row lock on the workspace). Task 6.

---

### Task 1: Workspaces, roles, DRF setup

**Files:**
- Modify: `dashboard/requirements.txt` (add `djangorestframework==3.15.2`), `dashboard/config/settings.py` (INSTALLED_APPS, `REST_FRAMEWORK`, `CSRF_TRUSTED_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]`, `LOGIN_URL` unchanged)
- Create: `dashboard/workspaces/{__init__,apps,models,permissions,admin}.py`, `dashboard/workspaces/migrations/0001_initial.py`, `0002_carrum_workspace.py` (data)
- Test: `dashboard/tests/test_workspaces.py`, shared fixtures in `dashboard/tests/conftest.py`

**Interfaces:**
- Produces: `Workspace(name, slug)`; `Membership(user, workspace, role)` unique per (user, workspace); `UserPreference(user one-to-one, appearance in {"light","dark","system"} default "system", notify_needs_person bool default True, notify_daily_summary bool default False, time_zone str default "Asia/Kolkata", phone str blank)`.
- Produces: `workspaces.permissions.workspace_for(request) -> Workspace` (the user's single membership; raises `PermissionDenied` if none); `IsMember`, `CanEdit` (editor+), `CanManageTeam` (admin+) DRF permission classes; `WorkspaceScopedMixin` for viewsets with `get_queryset()` filtering `workspace=workspace_for(request)` and `perform_create()` setting it.
- Produces fixtures in `conftest.py`: `workspace`, `other_workspace`, `member(role="editor")` factory returning a logged-in `APIClient`.
- `REST_FRAMEWORK = {"DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"], "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated", "workspaces.permissions.IsMember"]}`.

- [ ] **Step 1: Write failing tests**: `test_data_migration_creates_carrum` (one Workspace slug `carrum`, name "Carrum Mobility"); `test_workspace_for_returns_membership_workspace`; `test_user_without_membership_is_denied` (403 on any API); `test_viewer_cannot_edit` (CanEdit false for viewer, true for editor/admin/owner); `test_other_workspace_is_404` (generic helper `assert_isolated(client, url)` used by later tasks).
- [ ] **Step 2: Run** `cd dashboard && .venv/bin/pytest tests/test_workspaces.py -v` — Expected: FAIL (no module `workspaces`).
- [ ] **Step 3: Implement** models, permissions, mixin, admin registration, migrations. Install DRF in `.venv`.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: all pass, including the existing suite.
- [ ] **Step 5: Commit** `feat(console-api): workspaces, roles and DRF setup`

### Task 1b: PostgreSQL instead of SQLite

Requested by the user on 2026-11-05: production and tests run on PostgreSQL; SQLite is removed as the app database (the legacy importer still *reads* old SQLite files).

**Files:**
- Modify: `dashboard/requirements.txt` (add `psycopg[binary]==3.2.3`), `dashboard/config/settings.py` (`DATABASES`), `dashboard/tests/conftest.py` (test DB env), `docker-compose.yml` (new `postgres` service + `postgres-data` volume; `dashboard` `depends_on: [livekit, postgres]`), `.env.example` (`POSTGRES_*`), `scripts/init.sh` (generate `POSTGRES_PASSWORD` like the LiveKit secret), `Makefile` (`test` target needs `TEST_POSTGRES_*` or a local server), `README.md` (dashboard section)
- Create: `dashboard/calls/management/commands/copy_from_sqlite.py`, `scripts/migrate-dashboard-to-postgres.sh`
- Test: `dashboard/tests/test_database.py`, `dashboard/tests/test_copy_from_sqlite.py`

**Interfaces:**
- Settings: `DATABASES["default"] = {"ENGINE": "django.db.backends.postgresql", "NAME": env POSTGRES_DB (default "dashboard"), "USER": POSTGRES_USER (default "dashboard"), "PASSWORD": POSTGRES_PASSWORD (required — `ImproperlyConfigured` if empty), "HOST": POSTGRES_HOST (default "127.0.0.1"), "PORT": POSTGRES_PORT (default "5432"), "CONN_MAX_AGE": 60, "CONN_HEALTH_CHECKS": True}`. `DASHBOARD_DB_DIR` stays only as the directory for files (recordings in plan 4).
- Compose: `postgres` image `postgres:16.4-alpine` (pinned, never latest), `network_mode: host`, `command: ["postgres", "-c", "listen_addresses=127.0.0.1"]`, env `POSTGRES_DB/USER/PASSWORD` from `.env`, volume `postgres-data:/var/lib/postgresql/data`, healthcheck `pg_isready -U $POSTGRES_USER -h 127.0.0.1`; dashboard waits on `condition: service_healthy`.
- `manage.py copy_from_sqlite --path /data/dashboard.sqlite3` — copies `Call`, `CallReport`, `TurnLabel` (and auth users/groups) from the old Django SQLite file into the current (Postgres) database in one transaction, preserving primary keys, then resets sequences (`sqlsequencereset`); refuses if the target already has calls unless `--force`; prints counts. Read-only on the source.
- `scripts/migrate-dashboard-to-postgres.sh` — on the VM: `docker compose up -d postgres`, run `migrate`, run `copy_from_sqlite`, print counts from both sides, and leave the SQLite file in place as a backup. Never deletes it.
- Tests run against Postgres: `conftest.py` sets `POSTGRES_*` from `TEST_POSTGRES_*` env (defaults host 127.0.0.1, port 5432, user/password `postgres`), pytest-django creates/destroys `test_dashboard`.

- [ ] **Step 1: Write failing tests**: `test_engine_is_postgres`; `test_missing_password_is_improperly_configured` (reload settings in a subprocess); `test_copy_from_sqlite_preserves_ids_and_counts` (build a temp SQLite file with the old schema via Django's migrations on a second `sqlite` alias defined only in the test, insert 2 calls + 1 report + 1 turn label, copy, assert same ids/fields, then a new Call gets id 3); `test_copy_refuses_non_empty_target` (and `--force` allows it).
- [ ] **Step 2: Run** `cd dashboard && .venv/bin/pytest tests/test_database.py tests/test_copy_from_sqlite.py -v` with a local Postgres running — Expected: FAIL.
- [ ] **Step 3: Implement** settings, compose service, env/init/Makefile/README changes, command and script.
- [ ] **Step 4: Run** the full suite on Postgres `.venv/bin/pytest -q` — Expected: every existing and Task 1 test PASS. Run `docker compose config -q` — Expected: no errors.
- [ ] **Step 5: Commit** `feat(dashboard): run on PostgreSQL, with a one-off copy from SQLite`

### Task 2: Auth and profile API

**Files:**
- Create: `dashboard/workspaces/api.py`, `dashboard/workspaces/serializers.py`, `dashboard/workspaces/urls.py`; Modify: `dashboard/config/urls.py` (mount `api/` routes)
- Create: `dashboard/workspaces/management/commands/create_member.py`
- Test: `dashboard/tests/test_auth_api.py`

**Interfaces (all JSON):**
- `GET /api/auth/csrf` → 204, sets `csrftoken` cookie.
- `POST /api/auth/login {email, password}` → 200 `Me` | 400 `{"detail": "Wrong email or password."}`; login by email (case-insensitive) against `User.email`.
- `POST /api/auth/logout` → 204.
- `GET /api/me` → `Me = {id, name, email, phone, role, workspace: {id, name, slug}, preferences: {appearance, notify_needs_person, notify_daily_summary, time_zone}}`.
- `PATCH /api/me {name?, phone?, preferences?}` → `Me`. `POST /api/me/password {current_password, new_password}` → 204 | 400 with Django validator messages.
- `GET /api/team` (member) → `[{id, name, email, role, last_login}]`; `POST /api/team {email, name, role}` (admin+) creates the user with an unusable password and returns a one-time set-password link `{"set_password_url": "/set-password/<uid>/<token>"}`; `PATCH /api/team/<id> {role}` (admin+; cannot demote the last owner).
- `manage.py create_member <email> --name --role --workspace carrum` prompts for a password.
- `phone` in `Me` reads/writes `UserPreference.phone`.

- [ ] **Step 1: Write failing tests**: `test_login_by_email_sets_session`, `test_login_wrong_password_400_message`, `test_me_shape` (exact keys above), `test_patch_appearance_dark`, `test_change_password_validates`, `test_invite_requires_admin` (editor → 403), `test_cannot_demote_last_owner`, `test_csrf_required_for_session_post` (POST without token → 403 using `APIClient(enforce_csrf_checks=True)`).
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_auth_api.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** views (DRF `APIView`s), serializers, urls, management command.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(console-api): login, profile, preferences and team`

### Task 3: Script and expression tokens

**Files:**
- Create: `dashboard/voiceagents/__init__.py`, `dashboard/voiceagents/apps.py`, `dashboard/voiceagents/tokens.py`
- Test: `dashboard/tests/test_tokens.py`

**Interfaces:**
- `BUILTIN_EXPRESSIONS: dict[str, str]` — name → tone hint, exactly these keys: `happy, laugh, sad, fear, angry, whisper, pause, excited`. Hints (exact copy): happy "say this warmly and cheerfully"; laugh "say this with a light, warm laugh"; sad "say this gently, with sympathy"; fear "say this with a careful, concerned tone"; angry "say this firmly but calmly, never rude"; whisper "say this softly, as if sharing something personal"; excited "say this with energy and enthusiasm"; pause "pause for about {seconds} seconds before this" (default 1).
- `parse(body: str) -> list[Token]` where `Token = TextToken(text) | ExprToken(name, seconds: float | None) | VarToken(path)`; unknown `[[expr:x]]` names are kept as `ExprToken` (validated separately).
- `unknown_expressions(body: str, custom: dict[str, str]) -> list[str]`.
- `render_hints(body: str, custom: dict[str, str]) -> str` — replaces each expression with `(<hint>)` immediately before the text it precedes; keeps `{{lead.*}}` untouched for the agent to fill; custom hints override nothing built-in.
- `variables(body: str) -> list[str]` — the `lead.*` paths used.

- [ ] **Step 1: Write failing tests**: `test_parse_mixed` (`'[[expr:happy]] नमस्ते {{lead.name}} [[expr:pause:1.2]] ji'` → Expr(happy), Text, Var(lead.name), Expr(pause,1.2), Text); `test_render_hints_exact` (`'[[expr:laugh]] अरे वाह'` → `'(say this with a light, warm laugh) अरे वाह'`); `test_pause_seconds_in_hint` ("pause for about 1.2 seconds before this"); `test_custom_expression_used`; `test_unknown_expression_reported`; `test_variables_listed`; `test_devanagari_untouched`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_tokens.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** with one regex `\[\[expr:([a-z_]+)(?::(\d+(?:\.\d+)?))?\]\]|\{\{\s*(lead\.[a-z_]+)\s*\}\}`.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(console-api): script expression and variable tokens`

### Task 4: Knowledge documents

**Files:**
- Create: `dashboard/knowledge/{__init__,apps,models,serializers,api,urls,admin}.py`, migration
- Test: `dashboard/tests/test_knowledge_api.py`

**Interfaces:**
- `KnowledgeDocument(workspace, title, created_at, updated_at, archived bool)`; `KnowledgeRevision(document FK, number int, body_md text, edited_by user, created_at)` unique (document, number). `document.current` = highest number.
- `GET/POST /api/knowledge` (list: `{id, title, updated_at, used_by: int (agents linking it), current_revision}`), `GET/PATCH /api/knowledge/<id>` (`{title?, body_md?}` — a changed body creates revision n+1; same body → no new revision), `POST /api/knowledge/upload` (multipart `file` `.md`, ≤1 MB, UTF-8 → new document), `GET /api/knowledge/<id>/revisions`, `GET /api/knowledge/<id>/revisions/<n>`.
- Editor+ to write; viewer read.

- [ ] **Step 1: Write failing tests**: `test_create_makes_revision_1`, `test_save_same_body_no_new_revision`, `test_save_changed_body_increments`, `test_upload_md_utf8_devanagari`, `test_upload_rejects_non_md_and_too_big`, `test_viewer_cannot_save`, `test_knowledge_isolated` (uses `assert_isolated`).
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(console-api): knowledge documents with revisions`

### Task 5: Workflows and graph validation

**Files:**
- Create: `dashboard/workflows/{__init__,apps,models,graph,serializers,api,urls,admin}.py`, migration
- Test: `dashboard/tests/test_workflow_graph.py`, `dashboard/tests/test_workflows_api.py`

**Interfaces:**
- Graph JSON: `{"steps": [{"id": str, "name": str, "type": "start"|"prompt"|"collect"|"knowledge"|"transfer"|"end", "prompt": str, "field": str|null (collect), "knowledge_id": int|null, "outcome": Disposition|null (end), "position": {"x": float, "y": float}}], "paths": [{"id": str, "from": str, "to": str, "label": str}]}`.
- `workflows.graph.validate(graph: dict, knowledge_ids: set[int]) -> list[str]` — human-readable errors, empty when valid. Rules: exactly one `start`; ids unique; every path's from/to exist; every non-end step has ≥1 outgoing path; `end` has a valid outcome and no outgoing paths; `collect` has a `field` matching `^[a-z][a-z0-9_]{0,31}$`; every step reachable from start; path labels non-empty and unique per source step; referenced knowledge ids exist in the workspace; prompts may contain tokens and unknown expressions are errors (via `voiceagents.tokens.unknown_expressions`). Error copy example: `'Step "Explain the plan" has no way out. Add a path or make it an end step.'`
- `Workflow(workspace, name, updated_at, archived)`; `WorkflowRevision(workflow, number, graph JSON, saved_by, created_at)`. `POST /api/workflows`, `GET/PATCH /api/workflows/<id>` (`{name?, graph?}`; saving a graph stores a revision even if invalid, response includes `errors: [...]`), `GET /api/workflows/<id>/validate` → `{errors}`.

- [ ] **Step 1: Write failing tests** (graph): `test_valid_driver_onboarding_graph` (fixture: the 9-step flow from the spec — Greeting, Ask city, Ask licence and experience, Explain the plan, End: not in your city (NE), End: not eligible (NE), End: interested (INTERESTED), Schedule a call back (end, CBR), Transfer to a telecaller) → `[]`; `test_two_starts`, `test_dangling_path`, `test_dead_end_step`, `test_end_without_outcome`, `test_unreachable_step`, `test_bad_collect_field`, `test_unknown_expression_in_prompt`, `test_missing_knowledge_id` — each asserts the specific message. (API): `test_save_creates_revision_and_returns_errors`, `test_workflows_isolated`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_workflow_graph.py tests/test_workflows_api.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `validate` (BFS for reachability), models, API.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat(console-api): workflows with graph validation`

### Task 6: Agents, publish and versions

**Files:**
- Create: `dashboard/voiceagents/{models,serializers,api,urls,admin,publish}.py`, migration
- Test: `dashboard/tests/test_agents_api.py`, `dashboard/tests/test_publish.py`

**Interfaces:**
- `Agent(workspace, name, description, status "draft"|"published"|"archived", phone_number str, language str default "Hindi + Hinglish", persona_name default "Priya", voice_id str blank, settings JSON {mood_adaptation: bool, dead_air: {enabled: bool, nudge_s: 4, second_nudge_s: 9, hang_up_s: 15}}, script JSON [{"id", "title", "body"}], custom_expressions JSON {name: hint}, knowledge M2M KnowledgeDocument, workflow FK null, updated_at, updated_by)`.
- `AgentVersion(agent FK, number, snapshot JSON, published_by, published_at)`. `snapshot = {"agent_id", "version", "name", "persona_name", "language", "voice_id", "phone_number", "settings", "script": [{"title", "body_rendered"}] (bodies via tokens.render_hints), "variables": [...], "knowledge": [{"id","title","revision","body_md"}], "workflow": null | {"id","revision","graph"} (step prompts rendered via render_hints)}`. Agent `published_version` FK null.
- `voiceagents.publish.publish(agent: Agent, user) -> AgentVersion` — `transaction.atomic` + `select_for_update` on the workspace row; validates (script non-empty, unknown expressions, workflow `validate()`), raises `PublishError(errors: list[str])`; unpublishes the workspace's other published agent (status → draft, keeps its versions); sets this one published.
- `unpublish(agent)`; `is_outdated(agent) -> bool` (current script/settings/knowledge revisions/workflow revision differ from `published_version.snapshot`).
- API: `GET/POST /api/agents` (list item: `{id, name, description, status, phone_number, updated_at, updated_by_name, calls_this_week, is_outdated}`), `GET/PATCH /api/agents/<id>`, `POST /api/agents/<id>/publish` → 200 `{version}` | 400 `{errors}`, `POST .../unpublish`, `.../duplicate` (copy as draft "Copy of …"), `.../archive`, `.../restore`, `GET .../versions`, `GET /api/expressions` → built-ins + workspace custom (union of all agents' custom_expressions is not needed; return built-ins with hints).

- [ ] **Step 1: Write failing tests**: `test_publish_snapshot_contents` (rendered hints present, `{{lead.city}}` kept, knowledge revision numbers recorded); `test_publish_unpublishes_other`; `test_concurrent_publish_one_wins` (two `TransactionTestCase` threads or sequential calls asserting the invariant `published count == 1` after each); `test_publish_rejects_broken_workflow` (errors from Task 5 surface); `test_publish_rejects_empty_script`; `test_is_outdated_after_knowledge_save` and `..._after_workflow_save`; `test_editing_draft_does_not_change_published_snapshot`; `test_duplicate_is_draft`; `test_archive_published_is_refused` (400 "Unpublish it first."); `test_viewer_cannot_publish`; `test_agents_isolated`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(console-api): agents, publish snapshots and versions`

### Task 7: Runtime config and call events for the agent

**Files:**
- Create: `dashboard/runtime/{__init__,apps,auth,api,urls}.py`
- Modify: `dashboard/calls/models.py` (add `Call.workspace` FK null, `Call.agent_version` FK null, `Call.needs_person` bool default False, `Call.needs_person_handled_at` null; new `CallEvent`), migration `calls/0004_...` incl. data step assigning existing calls to Carrum; `CallReport.store` reads optional `report["agent_version_id"]` and `report["step_path"]` and sets `Call.agent_version`; sets `needs_person=True` when disposition is `CBR` or `telecaller_followup_agreed` is true or final/worst mood is `angry`/`frustrated`.
- Test: `dashboard/tests/test_runtime_api.py`

**Interfaces:**
- `runtime.auth.verify_agent(request, identity: str) -> bool` (shared with `report_ingest`; refactor that view to use it).
- `GET /api/runtime/config?number=<e164>&room=<room>` (identity `agent-runtime`) → 200 `{"version_id": int, "workspace": slug, "snapshot": {...}}` for the published agent of the workspace whose agent `phone_number` matches (digits-only comparison; if no agent has a number set and the workspace has one published agent, return it); 404 `{"detail": "No published agent for this number."}`; 401 bad token. Sets `Call.agent_version` for `room` (creates the row via `Call.record_first`).
- `CallEvent(call FK, seq int, type "turn"|"step_entered"|"mood"|"field_captured", payload JSON, at timestamp)` unique (call, seq), ordered by seq.
- `POST /api/runtime/events {"room": str, "events": [{"seq": int, "type": str, "at": epoch_s float, "payload": {...}}]}` → 200 `{"stored": n}`; upsert-ignore duplicates; unknown type → skipped (counted in `"skipped"`); ≤200 events per batch else 413. Payload shapes: turn `{speaker: "caller"|"agent", text, expressions: [str]}`; step_entered `{step_id, step_name}`; mood `{label, confidence}`; field_captured `{field, value}`.

- [ ] **Step 1: Write failing tests**: `test_config_requires_runtime_token` (report token → 401), `test_config_by_number` (digits-only match `+91 80 4718 2290` vs `918047182290`), `test_config_single_published_fallback`, `test_config_404_json_when_none`, `test_config_sets_call_version`, `test_events_before_call_exists`, `test_events_idempotent_by_seq`, `test_events_ordered_by_seq_when_out_of_order`, `test_events_batch_limit_413`, `test_report_sets_needs_person_for_cbr`, `test_existing_calls_assigned_to_carrum` (migration).
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS (existing `test_report.py`/`test_webhook.py` unchanged and green).
- [ ] **Step 5: Commit** `feat(console-api): runtime config and call events for the agent`

### Task 8: Calls, live calls and dashboard APIs

**Files:**
- Create: `dashboard/calls/api.py`, `dashboard/calls/serializers.py`, `dashboard/calls/outcomes.py`; Modify: `dashboard/calls/urls.py`, `dashboard/calls/livekit_state.py` (add `transfer(room, participant_identity, to_uri)` and `end_call(room)` wrappers around `api.LiveKitAPI`)
- Test: `dashboard/tests/test_calls_api.py`, `dashboard/tests/test_live_api.py`

**Interfaces:**
- `calls.outcomes.DISPLAY_OUTCOME: dict[str, str]` — the grouping in Global Constraints; `display_outcome(code: str) -> str` ("" for blank, "Dropped" for unknown codes).
- `GET /api/calls?q=&outcome=&agent=&mood=&city=&from=&to=&page=` → `{"results": [{room, started_at, caller, agent_name, outcome, outcome_code, mood, duration_s, summary}], "count", "page", "pages"}` (25 per page; `outcome` filters by display group; `q` matches caller digits).
- `GET /api/calls/<room>` → `{..list fields, reason, answers: {field: value}, step_path: [step names], transcript: [{speaker, text, expressions, at}], recording_url: null}` (`recording_url` stays null until plan 4).
- `GET /api/calls/export.csv` (same filters) → `text/csv`, columns `When,Caller,Agent,Outcome,Mood,Duration,Summary`.
- `POST /api/calls/<room>/needs-person {"handled": true}` → marks handled.
- `GET /api/live` → `[{room, caller, city, started_at, current_step, mood, transcript_tail: [last 50 turns]}]` from `fetch_livekit_state()` rooms + CallEvents; `POST /api/live/<room>/transfer` (uses `settings.HANDOFF_SIP_URI`; 409 `{"detail": "Live transfer isn't set up."}` when empty), `POST /api/live/<room>/end`. Editor+ for actions.
- `GET /api/dashboard?date=YYYY-MM-DD` → `{calls_today, connected_pct, interested, avg_duration_s, needs_person: [{room, caller, reason, at}] (unhandled, newest 10), outcomes_week: [{outcome, count}], live_agent: {id, name, phone_number} | null}` — "connected" = calls whose outcome is not Not reached.
- `settings.HANDOFF_SIP_URI = os.getenv("HANDOFF_SIP_URI", "")`.
- `GET /api/phone-numbers` → `[{number, trunk_name, agent_name | null}]` read-only, from the inbound trunks already returned by `fetch_livekit_state()` (Settings › Phone numbers); test `test_phone_numbers_from_trunks`.

- [ ] **Step 1: Write failing tests**: `test_display_outcome_mapping` (every one of the 14 codes), `test_calls_filter_by_outcome_group`, `test_calls_search_digits`, `test_call_detail_transcript_from_events`, `test_csv_export_headers_and_devanagari`, `test_needs_person_handled`, `test_dashboard_numbers` (fixture: 4 calls → exact values), `test_live_lists_rooms_with_tail` (monkeypatch `fetch_livekit_state`), `test_transfer_409_without_uri`, `test_end_calls_livekit` (monkeypatch wrapper, asserts room), `test_calls_isolated`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(console-api): calls, live calls and dashboard endpoints`

### Task 9: Retention, integration requests and seed data

**Files:**
- Create: `dashboard/calls/management/commands/purge_old_call_data.py`; `dashboard/workspaces/models.py` add `IntegrationRequest(workspace, user, tool, note, created_at)` + `POST /api/integrations/requests {tool, note}`; `dashboard/voiceagents/management/commands/seed_carrum.py`
- Modify: `README.md` (dashboard section: new commands, `create_member`, API overview)
- Test: `dashboard/tests/test_retention.py`, `dashboard/tests/test_seed.py`

**Interfaces:**
- `manage.py purge_old_call_data [--days 90] [--dry-run]` — deletes `CallEvent` rows of type `turn` with `at` older than N days, clears `TurnLabel.caller_text` (delete the rows) for reports older than N days, pops `turns` from those reports' `data`; prints counts. Never touches dispositions, summaries, answers, metrics. (Scheduling it daily is plan 4.)
- `manage.py seed_carrum [--knowledge PATH]` — idempotent: ensures the Carrum workspace, a draft agent "Driver lead qualifier" with script sections Greeting / City and licence / If the driver hesitates using the Hindi lines from the spec's Stitch prompts (no figures), and, if `PATH` (default `../agent/knowledge.md`) exists, a knowledge document "Approved pricing and rules" from it, linked to the agent. Does not publish.

- [ ] **Step 1: Write failing tests**: `test_purge_deletes_old_turns_only` (91-day-old turn removed, 89-day-old kept, report disposition intact), `test_purge_dry_run_changes_nothing`, `test_seed_idempotent` (run twice → one agent, one doc), `test_seed_without_knowledge_file`, `test_integration_request_saved`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement**; update README.
- [ ] **Step 4: Run** `cd dashboard && .venv/bin/pytest -q` — Expected: all PASS. Then `DJANGO_SECRET_KEY=x DASHBOARD_DB_DIR=$(mktemp -d) .venv/bin/python manage.py migrate && ... seed_carrum` — Expected: "Seeded Carrum Mobility: 1 agent, 1 knowledge document" (or "0 knowledge documents" without the file).
- [ ] **Step 5: Commit** `feat(console-api): retention, integration requests and seed data`
