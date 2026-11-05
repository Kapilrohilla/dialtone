# Agent runtime — implementation plan (2 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every call uses the agent the ops team **published** in the console (script with expression hints, knowledge, workflow steps), falls back safely when the console can't answer, streams call events to the console, and the same engine powers a text "Try it" / "Test call" simulation.

**Architecture:** The voice worker (`agent/`) gains four small pure modules (prompt assembly, config client, workflow engine, event sink) that `agent.py` wires together: fetch the published snapshot at call start → build the instructions (fixed system layer + script + current step) → run the workflow by swapping instructions and path tools as the model calls them → post events and include version/step path in the final report. A text simulation server in the same image (new compose service `agent-sim`) runs the same engine with a text LLM; Django exposes it to the console.

**Tech Stack:** Python 3.12, livekit-agents 1.8.5 (`function_tool(raw_schema=…)`, `Agent.update_instructions`, `Agent.update_tools`), aiohttp, pytest + pytest-asyncio; Django 5.2 + DRF for the simulate endpoint.

**Spec:** `docs/superpowers/specs/2026-11-05-carrum-voice-console-design.md` (roadmap: `docs/superpowers/plans/2026-11-05-carrum-voice-console-roadmap.md`, incl. "Carry forward" items for plan 2). Plan 1 interfaces are on `main` and deployed.

## Global Constraints

- Anti-goals (spec): never quote a price/offer/payout not written in a published knowledge document; a call must never fail or go silent because the console is down; editing a draft never changes a live call — a call keeps the version it started with.
- Prompt layers (spec "My calls"): (1) fixed **system layer** in code ops cannot edit — AI disclosure, never ask for Aadhaar/PAN/bank details or document numbers, knowledge-only pricing rule, `record_outcome` rules and disposition definitions, pronunciation of "Carrum", tone guide, dead-air and handoff behaviour; (2) agent **script** — in every step; (3) current **workflow step prompt** and its paths. No workflow → layers 1 + 2.
- Fallback order at call start: fresh config → last good cached config for that number → today's built-in `BASE_INSTRUCTIONS` + `knowledge.md`. A 404 ("No published agent for this number.") means **built-in**, not cache (ops unpublished on purpose). Config fetch budget **1.5 s**.
- Runtime auth: LiveKit-signed JWT, identity `agent-runtime` for `/api/runtime/config` and `/api/runtime/events`; `agent-report` for `/api/report` (unchanged). Simulation server accepts identity `console-sim` only.
- Event types and payloads (plan 1, exact): `turn {speaker: "caller"|"agent", text, expressions: [str]}`, `step_entered {step_id, step_name}`, `mood {label, confidence}`, `field_captured {field, value}`; batches ≤ 200; `seq` int ≥ 0 per call, increasing.
- Workflow guard rails: a step may be entered at most **3** times per call, at most **25** step transitions per call; on either cap the agent records `UNRESOLVED` (reason "workflow loop limit reached") and closes politely.
- Disposition codes are the fixed 14 (`INTERESTED NI NE CBR CDRP ISUDO ISUID HND WRGN OWNVA ABULR LANGUAGE_BARRIER NOT_CONNECTED UNRESOLVED`). An `end` step's `outcome` is the disposition the agent must record there.
- Expressions arrive as tone hints already rendered by the dashboard (`(say this with a light, warm laugh)`); the agent never sees `[[expr:…]]` tokens except in old snapshots' knowledge (strip them).
- Recording consent line is only spoken when `RECORDING_ENABLED=true` (plan 4 turns recording on); copy: `यह call quality के लिए record हो रही है।` appended to the opening line.
- Existing behaviour unchanged when the console has no published agent: same prompt, same tools, same reports as today. All existing agent tests stay green.

## Review Focus

1. **Console slow or down at call start** — the call still starts within the 1.5 s budget on cache or built-in, never errors. Task 2 (`test_timeout_uses_cache`, `test_down_no_cache_uses_builtin`).
2. **Caller asks about price on a step whose knowledge doc lacks figures** — instructions still carry the "quote only approved figures" rule and the snapshot knowledge, never empty-handed improvisation. Task 1 (`test_system_layer_always_present_with_snapshot`).
3. **Model calls a path tool that isn't valid from the current step, or loops between two steps** — engine refuses with a readable tool result / trips the cap and closes. Task 3 (`test_unknown_path_refused`, `test_visit_cap_forces_close`).
4. **Variables with no lead record** (`{{lead.name}}` on an inbound call) — no literal braces spoken; the model rephrases. Task 1 (`test_missing_variable_placeholder`).
5. **Events endpoint failing mid-call** — speech never blocks, events are dropped after retries, the final report still goes out. Task 4 (`test_post_failure_never_raises`, `test_flush_on_close`).

---

### Task 1: Prompt assembly and the fixed system layer

**Files:**
- Create: `agent/prompt.py`
- Modify: `agent/agent.py` (move the non-script parts of `BASE_INSTRUCTIONS` into `prompt.SYSTEM_LAYER`; keep `BASE_INSTRUCTIONS` behaviour for the fallback via `prompt.builtin_instructions`)
- Test: `agent/tests/test_prompt.py`

**Interfaces:**
- `SYSTEM_LAYER: str` — verbatim text from today's `BASE_INSTRUCTIONS` sections: the AI-disclosure line, "How you talk", "Saying the company name", the "Never ask for Aadhaar, PAN, bank details or any document numbers" rule, the "Never:" list, "Recording the outcome with `record_outcome`", the close procedure ("call `record_outcome`, then say the matching line, then call `end_call`"), plus the knowledge rule: "Quote only figures, offers and rules written under Approved information. If it isn't there, say the telecalling team will share the exact details." and the placeholder rule: "If a line contains [unknown …], say it naturally without that detail."
- `SCRIPT_FALLBACK: str` — the remaining script parts of today's `BASE_INSTRUCTIONS` (persona/job paragraph and "The call:" steps 1–7). `builtin_instructions(lead, language_rules) -> str` must equal today's `PhoneAgent` base instructions text (same order: system layer + script fallback + language rules + approved info + lead + opening), so behaviour is unchanged when no config exists — pin with a golden test against the current string.
- `fill_variables(text: str, lead: dict) -> str` — `{{lead.x}}` → `str(lead[x])` when present and non-empty, else `[unknown x]` with `_` → space.
- `strip_tokens(text: str) -> str` — removes leftover `[[expr:…]]` tokens (old snapshots).
- `knowledge_block(snapshot: dict) -> str` — `"Approved information (the only figures, offers and rules you may quote or apply):\n"` + each doc as `## <title>\n<body>` using `body_rendered` if present else `strip_tokens(body_md)`; with no docs, today's "Approved information: none available…" text from `approved_info()`.
- `build_instructions(snapshot: dict, lead: dict, language_rules: str, step: dict | None = None, paths: list[dict] = ()) -> str` — order: `SYSTEM_LAYER`, persona line `You are {persona_name}, …` (persona from snapshot), script sections (`## <title>\n<body_rendered>` with variables filled), `language_rules`, `knowledge_block`, lead instructions (existing `lead_instructions`), then, when `step` is given, a `Current step: <name>\n<prompt filled>\nWhen one of these happens, call the matching tool: …` block listing each path label; `end` steps add "Record the outcome as <CODE> with record_outcome, say this closing line, then call end_call."; `transfer` steps add "Record the outcome, tell the driver you are connecting them, then call transfer_to_telecaller."

- [ ] **Step 1: Write failing tests**: `test_builtin_matches_today` (golden: for a lead and GEMINI rules, `builtin_instructions` equals the string `PhoneAgent.__init__` builds on `main` today — capture it in the test from the current code before refactoring); `test_system_layer_always_present_with_snapshot`; `test_script_sections_rendered_in_order`; `test_missing_variable_placeholder` (`{{lead.name}}` with `{}` → `[unknown name]`, no `{{`); `test_variable_filled`; `test_knowledge_uses_body_rendered_else_strips_tokens`; `test_no_knowledge_uses_none_available_text`; `test_end_step_block_names_outcome`; `test_transfer_step_block`; `test_devanagari_preserved`.
- [ ] **Step 2: Run** `cd agent && .venv/bin/pytest tests/test_prompt.py -v` — Expected: FAIL (no module `prompt`).
- [ ] **Step 3: Implement** `prompt.py`; refactor `agent.py` to import `SYSTEM_LAYER`/`SCRIPT_FALLBACK`/`builtin_instructions` (no behaviour change).
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: all PASS (existing 50 + new).
- [ ] **Step 5: Commit** `feat(agent): prompt layers with a fixed system layer`

### Task 2: Console config client with cache and fallback

**Files:**
- Create: `agent/console_config.py`
- Test: `agent/tests/test_console_config.py`

**Interfaces:**
- Env: `DASHBOARD_URL` (default: `DASHBOARD_REPORT_URL` with the `/api/report` suffix removed; empty = console off → built-in), `CONFIG_CACHE_DIR` (default `/cache`; created if missing; unwritable → memory only, warning once).
- `@dataclass(frozen=True) class Config: source: Literal["console","cache","builtin"]; snapshot: dict | None; version_id: int | None`.
- `async def load_config(number: str, room: str, *, base_url: str, api_key: str, api_secret: str, timeout_s: float = 1.5, now: Callable[[], float] = time.monotonic) -> Config` — GET `{base_url}/api/runtime/config?number=…&room=…` with a 60-s `agent-runtime` JWT (same construction as `report.send_report`); 200 → `Config("console", snapshot, version_id)` and write `<CONFIG_CACHE_DIR>/<digits>.json` atomically (temp file + rename); 404 → `Config("builtin", None, None)` and delete that number's cache file; timeout / connection error / 5xx / bad JSON → cached file if present (`source="cache"`) else builtin. In-memory memo per number for **15 s** of successful console responses (skips the HTTP call; documented as the publish propagation delay). Never raises.
- Logs one INFO line `config loaded` with `source`, `version_id`, elapsed ms.

- [ ] **Step 1: Write failing tests** (aiohttp `TestServer` fake console): `test_console_ok_and_cached_to_disk`, `test_404_returns_builtin_and_clears_cache`, `test_timeout_uses_cache` (server sleeps 3 s, budget 0.2 s, returns within ~0.3 s), `test_down_no_cache_uses_builtin`, `test_bad_json_uses_cache`, `test_token_identity_agent_runtime` (server asserts the JWT identity), `test_memo_skips_http_within_15s`, `test_unwritable_cache_dir_memory_only`, `test_console_off_when_no_url`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_console_config.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(agent): load the published agent from the console with cache and fallback`

### Task 3: Workflow engine (pure)

**Files:**
- Create: `agent/workflow.py`
- Test: `agent/tests/test_workflow.py`

**Interfaces:**
- `class WorkflowRun` constructed from `graph: dict` (plan 1 shape: steps `{id, name, type, prompt, field, knowledge_id, outcome}`, paths `{id, from, to, label}`), `max_visits: int = 3`, `max_transitions: int = 25`.
  - `start() -> Step` — enters the `start` step.
  - `current: Step`; `path: list[str]` (step names entered, in order); `captured: dict[str, str]`.
  - `paths_from_current() -> list[PathTool]` with `PathTool(name: str, description: str, to: str, takes_value: bool)`; tool `name` = `go_to_` + slug of the target step name (ASCII `[a-z0-9_]`, ≤ 48 chars, de-duplicated with `_2`, `_3`); `description` = the path label; `takes_value` = current step is `collect`.
  - `take(tool_name: str, value: str | None = None) -> Transition` where `Transition(ok: bool, message: str, entered: Step | None, capped: bool, captured: tuple[str, str] | None)`; unknown/invalid tool → `ok=False`, message "That path isn't available from <step name>." ; collect step without a value → `ok=False`, "Say what the driver answered in `value`."; visit or transition cap → `capped=True` (engine stops; `message` tells the model to record UNRESOLVED with reason "workflow loop limit reached" and close).
  - `Step` = frozen dataclass mirroring the graph step plus `knowledge_id`.
- Engine never raises on malformed graphs it receives (published graphs are validated, but be defensive): a graph without a start step → `start()` returns `None` and the caller uses the script-only path.

- [ ] **Step 1: Write failing tests**: `test_driver_onboarding_happy_path` (the spec's 9-step flow from plan 1's fixture: Greeting → Ask city → Ask licence and experience → Explain the plan → End: interested; `path` names in order); `test_tool_names_slugged_and_unique` (Devanagari/duplicate names); `test_unknown_path_refused`; `test_collect_requires_value_and_captures`; `test_visit_cap_forces_close` (A↔B loop hits 3 visits); `test_transition_cap`; `test_end_step_has_no_paths`; `test_transfer_leaf_and_fallback_path`; `test_graph_without_start_returns_none`.
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_workflow.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(agent): workflow engine with path tools and loop caps`

### Task 4: Event sink and report fields

**Files:**
- Create: `agent/events.py`; Modify: `agent/report.py`
- Test: `agent/tests/test_events.py`, `agent/tests/test_report.py`

**Interfaces:**
- `class EventSink(url: str, room: str, api_key: str, api_secret: str, flush_every_s: float = 1.0, max_batch: int = 50)`: `add(type: str, payload: dict) -> None` (assigns `seq` 0,1,2…, `at` = `time.time()`; non-blocking, safe from sync event handlers); background task posts batches to `{DASHBOARD_URL}/api/runtime/events` with an `agent-runtime` JWT; on failure retries the same batch up to 3 times with 0.5/1/2 s backoff then drops it (warning, count); `async close(timeout_s: float = 3.0)` flushes what's left within the timeout. Disabled (no-op) when `url` is empty. Never raises.
- `build_report(..., agent_version_id: int | None = None, step_path: list[str] | None = None)` adds both keys only when given (existing callers unchanged).

- [ ] **Step 1: Write failing tests**: `test_seq_increasing_and_batches_posted` (fake server records bodies), `test_post_failure_never_raises` (500s → dropped after 3 retries, `add` keeps working), `test_flush_on_close`, `test_noop_without_url`, `test_batch_size_capped`; report: `test_report_includes_version_and_step_path`, existing report tests unchanged.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(agent): stream call events to the console`

### Task 5: Wire the runtime into the call

**Files:**
- Modify: `agent/agent.py`
- Test: `agent/tests/test_runtime_wiring.py` (pure helpers only)

**Interfaces / behaviour:**
- `entrypoint`: connect → `caller = await ctx.wait_for_participant(...)` → `called = caller.attributes.get("sip.trunkPhoneNumber", "")` → `cfg = await load_config(called, ctx.room.name, …)` → build session/agent → `session.start`. (Moves participant wait before session start; the greeting gate still listens because the session starts within the fetch budget.)
- `PhoneAgent.__init__(lead, language_rules, cfg: Config)`: `cfg.snapshot is None` → `builtin_instructions` (today's behaviour). Otherwise, if the snapshot has a workflow with a start step, create `WorkflowRun`, enter start, instructions = `build_instructions(snapshot, lead, rules, step, paths)`, tools = base tools + path tools; else `build_instructions(snapshot, lead, rules)`.
- Path tools: `function_tool(handler, raw_schema={"name": tool.name, "description": tool.description, "parameters": {"type": "object", "properties": {"value": {"type": "string", "description": "What the driver answered"}} if tool.takes_value else {}, "required": ["value"] if tool.takes_value else []}})`. Handler: `run.take(...)`; on `ok` → `await self.update_instructions(build_instructions(..., new step, new paths))` and `await self.update_tools(base + new path tools)`, emit `step_entered` (and `field_captured` when captured); return a short tool result ("Now at step <name>.") — on refusal return the engine message; on cap return the cap message.
- `record_outcome` on an `end` step: if `disposition` ≠ the step's `outcome`, return "This step ends with <CODE>. Call record_outcome with disposition <CODE>." without recording.
- Settings from the snapshot: `settings.dead_air` (`enabled`, `nudge_s`, `second_nudge_s`, `hang_up_s`) override the env defaults for that call; `settings.mood_adaptation` overrides `MOOD_ENABLED` per call; `persona_name` replaces `AGENT_PERSONA_NAME` in the opening line. Pipeline and voice stay worker settings (spec).
- Events: `turn` from `conversation_item_added` (speaker caller/agent, `expressions: []`), `mood` on tracker change, `step_entered`, `field_captured`. `EventSink.close()` in the shutdown callback **before** `send_call_report`.
- Report: `agent_version_id=cfg.version_id`, `step_path=run.path` (or None).
- Consent: when `RECORDING_ENABLED=true`, `opening_line()` ends with `यह call quality के लिए record हो रही है।`.
- Helper functions extracted for unit tests: `path_tool_schema(tool: PathTool) -> dict`, `dead_air_config(settings: dict | None) -> DeadAirConfig`, `mood_enabled(settings: dict | None) -> bool`, `opening_line(lead, persona_name: str, recording: bool) -> str`.

- [ ] **Step 1: Write failing tests**: `test_path_tool_schema_with_and_without_value`, `test_dead_air_config_from_settings_and_defaults`, `test_mood_enabled_override`, `test_opening_line_consent_only_when_recording`, `test_opening_line_uses_persona`, `test_end_step_wrong_disposition_refused` (call the bound `record_outcome` method on an agent built with a fake snapshot; no LiveKit session needed — construct `PhoneAgent` directly), `test_builtin_when_no_snapshot` (instructions equal `builtin_instructions`).
- [ ] **Step 2: Run** `.venv/bin/pytest tests/test_runtime_wiring.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement.** First, a 10-minute spike in a scratch script: construct an `Agent` with a `function_tool(raw_schema=…)` tool and call `update_tools` / `update_instructions` outside a session to confirm the 1.8.5 API; record the finding in the report.
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS. Then a local smoke run against a dev LiveKit (`make up` + `make agent-dev`, call via `scripts/test-call.sh` if a SIP trunk is configured; otherwise report it as not run).
- [ ] **Step 5: Commit** `feat(agent): run the published agent and its workflow on every call`

### Task 6: Dashboard snapshot and seed updates

**Files:**
- Modify: `dashboard/voiceagents/publish.py` (`build_snapshot` knowledge entries gain `body_rendered = render_hints(body_md, custom)`), `dashboard/voiceagents/management/commands/seed_carrum.py` (script = today's `SCRIPT_FALLBACK` split into sections "Your job", "Opening", "Qualify", "Pick the plan", "Explain it", "Questions and objections", "Confirm interest", "Close" — text copied from `agent/prompt.py` `SCRIPT_FALLBACK`, Hinglish as today, no new figures; existing seeded agents are not rewritten)
- Test: `dashboard/tests/test_publish.py`, `dashboard/tests/test_seed.py`

- Also (roadmap carry-forward): `voiceagents.tokens.unknown_expressions` stays as is, but publish and workflow validation add an error for any `[[expr:pause:N]]` with N > 10: `"Pause is too long (N s). Use at most 10 seconds."`; test `test_publish_rejects_long_pause`.

- [ ] **Step 1: Write failing tests**: `test_snapshot_knowledge_body_rendered` (`[[expr:excited]]` in a doc → hint text in `body_rendered`, raw kept in `body_md`); `test_seed_script_matches_agent_fallback` (seeded section titles exactly as listed; bodies contain no `₹` and no digits other than step numbers).
- [ ] **Step 2: Run** `cd dashboard && .venv/bin/pytest tests/test_publish.py tests/test_seed.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `.venv/bin/pytest -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(console-api): render knowledge hints in snapshots; seed today's script`

### Task 7: Text simulation ("Try it" and "Test call")

**Files:**
- Create: `agent/simulate.py` (aiohttp app), `dashboard/voiceagents/simulate.py` (Django proxy view)
- Modify: `docker-compose.yml` (service `agent-sim`: same image as `agent`, `command: ["python", "simulate.py"]`, `network_mode: host`, `env_file: .env`, profile `agent`), `dashboard/voiceagents/urls.py`, `dashboard/config/settings.py` (`AGENT_SIM_URL = os.getenv("AGENT_SIM_URL", "http://127.0.0.1:8790")`)
- Test: `agent/tests/test_simulate.py`, `dashboard/tests/test_simulate_api.py`

**Interfaces:**
- Sim server `POST /simulate` on `127.0.0.1:${SIM_PORT:-8790}`, JWT identity `console-sim` (401 otherwise). Body `{snapshot, lead: {}, messages: [{role: "caller"|"agent", text}], state: {current_step_id, visits, transitions, captured, outcome} | null}` → `{reply: str, state: {...}, step: {id, name} | null, outcome: {...} | null, ended: bool}`. Stateless: rebuilds `WorkflowRun` from `state`, builds instructions with `build_instructions`, calls a text LLM with tools (path tools + `record_outcome` + `end_call` + `transfer_to_telecaller` stub that returns "Transfer simulated."), applies tool calls through the same engine, loops until the model produces text (max 4 tool rounds). LLM = `livekit.plugins.google.LLM(model=os.getenv("SIM_LLM_MODEL", "gemini-2.5-flash"))` behind a small `ChatModel` protocol so tests inject a scripted fake.
- Django `POST /api/agents/<id>/simulate {messages, state}` (editor+) → builds the **draft** snapshot with `build_snapshot(agent, 0)` (unsaved), signs a `console-sim` JWT, proxies to `AGENT_SIM_URL/simulate` with a 20 s timeout → returns the sim response; sim unreachable → 503 `{"detail": "The test simulator isn't running."}`. `POST /api/workflows/<id>/simulate` does the same with a minimal snapshot (persona "Priya", the workflow's current graph rendered, no script) for the builder's "Try it".

- [ ] **Step 1: Write failing tests** (agent): `test_sim_requires_console_sim_token`, `test_sim_greeting_turn_returns_reply_and_start_step` (fake model), `test_sim_path_tool_moves_step`, `test_sim_end_step_records_outcome_and_ends`, `test_sim_tool_round_limit`. (dashboard): `test_simulate_uses_draft_snapshot` (monkeypatch the HTTP call; assert the posted snapshot reflects an unpublished script edit), `test_simulate_503_when_down`, `test_simulate_viewer_forbidden`, `test_workflow_simulate_minimal_snapshot`, `test_simulate_isolated`.
- [ ] **Step 2: Run** both suites' new files — Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `cd agent && .venv/bin/pytest -q` and `cd dashboard && .venv/bin/pytest -q` — Expected: PASS; `docker compose --env-file <scratch env> config -q` — Expected: no errors.
- [ ] **Step 5: Commit** `feat: text simulation for Try it and Test call`

### Task 8: Configuration, cache volume and docs

**Files:**
- Modify: `docker-compose.yml` (agent: volume `agent-cache:/cache`; declare volume), `.env.example` (`DASHBOARD_URL`, `CONFIG_CACHE_DIR`, `RECORDING_ENABLED=false`, `SIM_PORT=8790`, `SIM_LLM_MODEL`, `AGENT_SIM_URL`), `scripts/deploy.sh` (also build/up `agent-sim`), `agent/Dockerfile` (create `/cache` owned by the runtime user), `README.md` (how a call picks its agent, fallback order, the 15-s publish delay, simulation service), `docs/superpowers/plans/2026-11-05-carrum-voice-console-roadmap.md` (mark plan 2 items done)
- Test: `scripts/tests/test-init.sh` if `init.sh` changes; `docker compose config -q`

- [ ] **Step 1: Write failing check**: extend `scripts/tests/test-init.sh` (or add one) asserting `init.sh` adds `DASHBOARD_URL=http://127.0.0.1:8787` and `RECORDING_ENABLED=false` to an existing `.env` without overwriting values.
- [ ] **Step 2: Run** `bash scripts/tests/test-init.sh` — Expected: FAIL.
- [ ] **Step 3: Implement** compose, env, init, deploy, Dockerfile, README, roadmap.
- [ ] **Step 4: Run** `make test` and `docker compose --env-file <scratch env> config -q` — Expected: all pass, no errors.
- [ ] **Step 5: Commit** `chore: agent config cache, simulator service and docs`
