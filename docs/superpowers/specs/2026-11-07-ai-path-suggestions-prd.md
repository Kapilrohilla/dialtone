# Suggest with AI — workflow path and expression suggestions (PRD)

Date: 2026-11-07. Status: ready for approval. Ticket: KAP-14 (plan only; build in follow-up tickets).

## Intent

A workflow branch is a `Path { from, to, label }`. At call time every target step becomes one tool, `go_to_<step slug>`, and the tool's description is the path label (`agent/workflow.py`, `all_path_tools` and `path_tool_schema`). The label wording is therefore the whole classifier for what the caller said.

There is no fallback path. If no label matches, the agent keeps talking on the same step until the loop cap (3 visits per step, 25 transitions per call, `WorkflowRun`) stops the workflow and the call is closed as **UNRESOLVED**.

Authors write the happy paths ("Has licence", "No licence") and rarely cover the long tail of Hindi and Hinglish answers ("पता नहीं", "apply किया है", "पहले job बताओ"). They also seldom add **expressions** (`[pause 0.6s]`, `[sad]`, `[happy]`) to the agent's lines.

**Suggest with AI** lets Gemini read one step, or the whole workflow, and propose:

1. **Other answers** callers give, each as a new path out of the step. Every answer comes with a short path name, 2–5 example caller phrases, a target (an existing step or a new step) and a one-line reason.
2. **Expressions** for the agent's lines, shown as before and after.

Everything it produces is a **draft**. The workflow does not change until the author accepts a suggestion, and nothing reaches live calls until the agent is republished.

## Goals

1. Entry points: **Suggest with AI** in the workflow top bar (whole workflow) and **Suggest more answers** under a step's "Then go to" (this step).
2. A review panel with **Answers** and **Expressions** tabs. Each item can be accepted, edited or dismissed. There are **Accept all**, **Discard all** and **Undo**.
3. Drafts are stored on the server, survive reloads, are visible to teammates, and are marked **out of date** when the step they came from changes.
4. Optional `examples` on every path, editable by hand, fed into the runtime tool description.
5. Accept + Save produces a revision that passes `graph.validate`.

## Non-goals (this phase)

- Changing live calls. Calls change only when the agent is republished.
- Generating whole workflows from scratch.
- A runtime catch-all path type ("Anything else"). See open question 1.
- Light-mode designs. The console follows the dark designs; light mode uses existing tokens.
- Suggesting new custom expressions. Only expressions that already exist for the workspace are allowed.

## Anti-goals (a failure even if it works)

- The workflow changes without an explicit Accept.
- A suggestion silently rewrites the agent's words. Expression suggestions may only **add** expression tokens.
- An accepted suggestion makes the graph invalid, or makes Save fail.
- One author's run wipes out a teammate's pending draft without warning.
- A Gemini failure or timeout leaves the editor stuck or the workflow touched.

## Facts from the code that shape the design

- **One tool per target step, first label wins.** `all_path_tools` registers one tool per *target* step for the whole graph, and its description is the label of the first path pointing at that step. A second path into the same step (for example "Licence applied, not received" → existing "Schedule a call back") is matched only by the first path's label today. This feature must fix that: the description is built from **every** incoming path's label and examples (see Runtime).
- **Two paths from one step to the same target collapse** into one tool in `paths_from_current`. A suggestion must not target a step that its source step already goes to; the validator rejects it with "This step already goes there. Add the phrases to that path instead."
- **Expressions are stored as tokens**, `[[expr:name]]` or `[[expr:pause:0.6]]` (`dashboard/voiceagents/tokens.py`). `[pause 0.6s]` is only how the editor chip looks. Built-ins: happy, laugh, sad, fear, angry, whisper, pause, excited. Pauses are 0.2–10 s (`MAX_PAUSE_SECONDS`, console `MIN_PAUSE_S`).
- **Step types** are `start, prompt, collect, knowledge, transfer, end`. End steps may not have outgoing paths, and every step except transfer and end needs a way out (`dashboard/workflows/graph.py`).
- **Saving** is `PATCH /api/workflows/<id>` with the whole graph; a new `WorkflowRevision` is created only when the graph changed. Invalid graphs can be saved; errors are reported.
- **The dashboard has no Gemini code and no background workers.** Gemini is used only by the agent (`GOOGLE_API_KEY`, `SIM_LLM_MODEL=gemini-2.5-flash`). This feature adds `google-genai` to the dashboard.
- **Permissions:** reads need `IsMember`, writes need `CanEdit` (editor, admin, owner). Viewers are read-only (`workspaces/permissions.py`, console `canEdit`).

## User flow

1. The author clicks **Suggest with AI** (top bar) or **Suggest more answers** (under "Then go to"). A popover asks:
   - Look at: **This step** (pre-selected from the step entry point) or **Whole workflow**.
   - Suggest: **Other answers** and/or **Expressions** (both on by default).
   - **Suggest** button. If the editor has unsaved changes, the popover says "Suggestions use the last saved version. Save first?" with **Save and suggest** and **Suggest anyway**.
2. **Generating** (screen 2): the panel opens with a progress state; the canvas is still editable. The author can close the panel; the run continues and the banner shows when it is done.
3. **Review** (screens 3 and 4): items appear in the panel. Answer suggestions also appear on the canvas as dashed, cool-blue paths and "Suggested" step cards. A notice reads "These are a draft. Your workflow hasn't changed. Accept what you want, then Save."
4. **Accept** applies the item to the unsaved graph. **Edit** opens the edit form (screen 5). **Dismiss** (×) hides it for everyone.
5. **Partly accepted** (screen 6): accepted items turn into normal solid paths and steps; the editor shows unsaved changes; **Undo** reverts the last accept.
6. **Save** (screen 7): if items are still pending, the Save dialog shows "Accepted N / Still a draft M" and "Calls change only when you republish the agent." Saving keeps pending items as a draft.
7. Later, any teammate opening the workflow sees the banner "N suggestions are waiting for review — From <name>, <time>" with **Review** and **Discard draft**.

## Screens (Stitch project "Carrum Voice — Final", "Suggest with AI 1–10")

| # | State | Notes |
|---|-------|-------|
| 1 | Start: scope popover | Scope and kinds; editors only. |
| 2 | Generating | Progress in panel; cancel closes the panel, not the run. |
| 3 | Review answers | Per item: quoted path name, "Goes to" (with **New step** chip), "Caller might say" chips, "Why". Footer: **Discard all**, **Accept all N**. |
| 4 | Review expressions | Per step: "Now" line, "Suggested" line with dashed expression chips, "Why". Footnote: "Expressions guide the agent's tone. They are hints, not exact audio." |
| 5 | Edit suggestion | Path name (≤ 60, "The agent uses this to decide when to take this path."), "When the caller says something like" chips (+ Add phrase), "Then go to", and for a new step: name, "What the agent says" with the expression editor, "After this step, go to". Buttons: **Cancel**, **Save to draft**, **Accept**. |
| 6 | Partly accepted | Solid accepted paths, **Undo**, unsaved-changes state on Save. |
| 7 | Draft banner + Save dialog | Banner for anyone opening the workflow; dialog counts accepted vs still-draft items. |
| 8 | Nothing to suggest | "This step already covers the answers callers usually give." with **Suggest again** and **Close**. |
| 9 | Error | "Couldn't get suggestions. Your workflow hasn't changed." with **Try again**. Rate limit uses the same state with "Daily limit reached. Try again tomorrow." and no retry. |
| 10 | Out of date | "These suggestions are out of date. Someone changed this step after the suggestions were made." **Suggest again** / **Review anyway**. Lists "Still valid suggestions" and "No longer valid suggestions" (struck through). A valid-but-blocked item shows its reason in red, for example "A path with this name already exists. Rename it to accept.", and only **Edit** and × are offered. |

## Data model (dashboard/workflows)

`WorkflowSuggestionSet` — one run.

| Field | Type | Notes |
|---|---|---|
| `workflow` | FK Workflow | `related_name="suggestion_sets"` |
| `base_revision` | FK WorkflowRevision | Revision the run read. |
| `scope` | `step` / `workflow` | |
| `step_ids` | JSON list[str] | Steps that were sent to Gemini. |
| `kinds` | JSON list | Subset of `answers`, `expressions`. |
| `status` | `running` / `ready` / `empty` / `error` / `closed` | |
| `error` | text | User-safe message; details go to logs. |
| `step_fingerprints` | JSON {step_id: sha1} | Hash of each source step's type, name, prompt and outgoing paths at `base_revision`. Drives out-of-date. |
| `created_by` | FK User | Shown in the banner. |
| `created_at`, `finished_at`, `closed_at` | datetime | |
| `model` | str | Gemini model id, for analysis. |

`WorkflowSuggestion` — one item.

| Field | Type | Notes |
|---|---|---|
| `suggestion_set` | FK | `related_name="items"` |
| `kind` | `answer` / `expression` | |
| `step_id` | str | Source step. |
| `payload` | JSON | As produced by Gemini, after validation. |
| `edited_payload` | JSON, null | Author's edit ("Save to draft"). The effective payload is `edited_payload or payload`. |
| `status` | `pending` / `accepted` / `dismissed` | |
| `invalid_reason` | text, blank | Set by validation; computed again on read against the current revision. |
| `decided_by`, `decided_at` | | |

Payloads:

```jsonc
// answer
{
  "label": "Not sure which licence",                  // ≤ 60 chars
  "examples": ["पता नहीं", "शायद yellow है", "not sure ji"], // 1–5, ≤ 40 chars each
  "reason": "callers often don't know their licence type.", // ≤ 140 chars
  "target": {"step_id": "s_explain_plan"}             // existing step, or:
  // "target": {"new_step": {"name": "Explain licence types", "type": "prompt",
  //            "prompt": "[[expr:pause:0.6]] कोई बात नहीं जी। ...",
  //            "then": {"step_id": "s_ask_licence", "label": "Explained licence types"}}}
  //   new step type is "prompt" or "end"; an end step has "outcome" instead of "then".
}
// expression
{ "before": "<step prompt at base revision>", "after": "<same text with tokens added>",
  "reason": "a softer tone when turning a driver away." }
```

One open set per workflow: starting a new run closes the previous open set (its pending items stay in the database as `closed`, not shown). The popover warns "This replaces N pending suggestions from <name>." when the open set belongs to someone else.

## API

All under `/api/workflows/<id>/suggestions`, scoped to the request's workspace like the other workflow views. Reads: `IsMember`. Writes: `CanEdit`.

- `POST /api/workflows/<id>/suggestions` `{scope, step_id?, kinds}` → `202 {set}` with `status: "running"`. Checks the daily limit (429 with `{"detail": "Daily limit reached"}`), creates the set, starts generation in a background thread, returns at once.
- `GET /api/workflows/<id>/suggestions/current` → the open set with items, or `204`. Each item carries its effective payload, `status`, and `invalid_reason` / `stale` computed against the **current** revision. The console polls every 1.5 s while `running`. A set still `running` after 45 s is reported (and stored) as `error` with "Took too long".
- `PATCH /api/workflows/<id>/suggestions/<item_id>` `{edited_payload?}` or `{status: "dismissed" | "pending"}`. Validates `edited_payload` with the same rules and returns 400 with field errors.
- `POST /api/workflows/<id>/suggestions/<set_id>/close` — **Discard all** / **Discard draft**. Marks pending items dismissed and the set closed.
- Save: `PATCH /api/workflows/<id>` accepts an optional `accepted_suggestions: [item_id, ...]`. In the same transaction as the new revision, those items become `accepted`. Accept therefore stays client-side until Save, and **Undo** needs no server call. When no pending items are left, the set is closed.

Background work: the dashboard has no queue, so generation runs in a `threading.Thread` started from the view (`close_old_connections()` at start and end). This fits one run of at most 30 s; the 45 s read-time timeout cleans up runs lost to a restart. If a worker queue is added later, only the starter changes.

Daily limit: `SUGGEST_DAILY_LIMIT` (default 20) runs per workspace per calendar day in `TIME_ZONE`. Runs that end in `error` do not count.

## Generation (dashboard/workflows/suggest.py)

- Client: `google-genai`, model `SUGGEST_LLM_MODEL` (default `gemini-3.6-flash`; `gemini-2.5-flash` is no longer available to new API keys), key `GOOGLE_API_KEY`. Add both to `.env.example` and the dashboard service in `docker-compose.yml`.
- Structured output: `response_mime_type="application/json"` with a `response_schema` matching the payloads above, `temperature` 0.4.
- Input per step: name, type, prompt (tokens kept), `field`, outgoing paths (label, examples, target name), the list of all step names and ids with types, the workflow name, the allowed expression names (built-ins + the published agent's custom expressions), and the agent's language from the workflow content.
- Prompt rules: Hindi/Hinglish phrases as callers actually speak them (Devanagari and Latin both fine); do not repeat an answer an existing path already covers; prefer existing steps; propose a new step only when no step fits; never paths out of end steps; expressions only add tokens, never change words; at most 5 answers per step; return nothing rather than filler.
- Steps looked at: for **answers**, steps of type start, prompt, collect and knowledge; for **expressions**, any step with a prompt. **Whole workflow** sends up to 20 steps in graph order and the panel says "Looked at 20 of N steps" when it cuts.
- Batching: at most 5 steps per call; batches run concurrently (up to 4). Each call has a 20 s timeout and one retry if at least 8 s of the 30 s budget remain. A batch that fails is dropped; the set is `error` only if every batch fails, otherwise the panel says "Some steps couldn't be checked."
- Logging: duration, token counts and item counts per run; never log caller data (there is none in the input).

## Validation (dashboard/workflows/suggestions.py, pure functions)

Run on Gemini output (invalid items are dropped and logged), on `edited_payload`, and on every read against the current revision (items become `invalid_reason`). Every rule returns a short, user-facing reason.

Answer:

- `label` non-empty, ≤ 60 chars, not equal (case-insensitive, trimmed) to another label out of the same step — including other pending suggestions from the same step.
- `examples`: 1–5 strings, each non-empty and ≤ 40 chars, de-duplicated.
- Source step exists and is not `end` or `transfer`.
- Target: an existing step id that is not `start` and that the source does not already go to; or a new step with a non-empty name (≤ 60) that does not clash with an existing step name, type `prompt` with a `then` (existing, non-`start` target, label ≤ 60) or type `end` with a valid outcome from `DISPOSITIONS`.
- New step prompt passes the expression checks below.
- At most 5 answer items per step per set (extra items dropped).

Expression:

- Source step exists and its prompt still equals `before`.
- `after` with every `[[expr:…]]` token removed equals `before` with its tokens removed (whitespace-normalised). Otherwise dropped: "would change the words".
- Every token is a known expression (`unknown_expressions`), no pause is over 10 s (`long_pause_errors`) and none is under 0.2 s (the console's `MIN_PAUSE_S`; add the same lower bound on the server).
- `after` differs from `before`.

Out of date: an item is **stale** when its source step's fingerprint at the current revision differs from `step_fingerprints`. Stale items are re-validated against the current graph: still valid → listed under "Still valid suggestions"; failing → "No longer valid" with the reason (e.g. "The path this pointed to was removed"). The client also runs the same checks (ported to `console/src/components/workflow/suggestions.ts`) against the **unsaved** graph before Accept, so a local rename that clashes blocks Accept with the screen 10 red reason.

## Runtime (agent/)

- `Path` gains optional `examples: list[str]` (≤ 5, ≤ 40 chars; loader trims and drops bad entries, same as other fields). `graph.validate` checks the same limits; console `Path` type gains `examples?: string[]`.
- Tool description is built from **all** non-end paths into the target, in graph order, de-duplicated:
  `"<label 1>. Caller might say: \"a\", \"b\". | <label 2>. Caller might say: …"`, capped at 1000 chars. A single path with no examples keeps today's description (its label) exactly, so existing calls and tests are unchanged.
- `paths_from_current` uses the same description so the tool the model sees and the tool that is registered agree.
- No change to loop caps, tool names or the once-per-call tool registration.

## Console (console/src/components/workflow/)

- `TopBar` secondary action **Suggest with AI** (sparkle icon) next to **Try it**; hidden for viewers. `PathRows` gets a **Suggest more answers** link under "Then go to" for non-end steps.
- `SuggestPopover`, `SuggestionsPanel` (tabs, rows, footer), `SuggestionEditForm`, `SuggestionBanner`, and a Save dialog variant. Queries in `src/lib/queries.ts`: `useCurrentSuggestions(workflowId)` (polls while running), `useStartSuggestions`, `usePatchSuggestion`, `useCloseSuggestions`.
- Canvas: `toFlow` takes the pending items and draws dashed cool-blue edges and "Suggested" / "Suggested path" cards for them. Suggested items are not draggable and not part of the graph.
- Accept uses the existing helpers on the unsaved graph through `edit(g => …)`:
  - answer to an existing step → `addPath(g, from, to, label)` then `updatePath` with `examples`;
  - answer to a new step → `addStep(g, type, near)` + `updateStep` (name, prompt, outcome) + `addPath` for the answer + `addPath` for `then`;
  - expression → `updateStep(g, id, {prompt: after})`.
  A new `applySuggestion(graph, item)` helper in `graph.ts` wraps this and returns `{graph, error?}`. The page keeps an `accepted` stack of `{itemId, previousGraph}` for **Undo** and sends `accepted_suggestions` with Save. Accept all applies items in order and stops at the first failure.
- `PathRows` gets an examples chip input under each path (max 5, 40 chars), so authors can add phrases without the AI.
- Viewers: no entry points; they see the banner and the read-only panel without Accept, Edit or ×.

## Follow-up tickets (build order)

1. **Path examples, end to end**: `examples` in `agent/workflow.py` (merged descriptions), `graph.validate`, console type and `PathRows` chips. Small, ships value alone.
2. **Backend suggestions**: models + migration, validation module, Gemini generation, API, daily limit, settings and env. Unit tests for validation and out-of-date; API tests with Gemini mocked; permission tests (viewer 403).
3. **Console review flow**: entry points, popover, panel, canvas drafts, `applySuggestion` + Undo, Save dialog, banner, empty / error / out-of-date states. Graph helper tests and panel tests with MSW handlers in `src/test/handlers.ts`.
4. **Simulator check**: an `agent/tests` case and a "Try it" run showing a path with examples is taken for a long-tail answer.

## Acceptance criteria

- Suggest on a collect step returns 1–5 valid answer suggestions and 0–N expression suggestions, or the empty state.
- No graph change until Accept; Accept + Save produces a revision that passes `graph.validate`.
- Reloading restores the pending draft; a teammate sees the banner.
- Editing the source step marks affected suggestions out of date and shows screen 10.
- A Gemini timeout shows the error state and leaves the workflow untouched.
- Viewers cannot run, accept, edit or dismiss (UI hidden and API 403).
- A path added through a suggestion into a step that already had an incoming path is described to the agent by its own label and examples.

## Success metrics

- ≥ 50% of saved workflows have an accepted suggestion within 60 days.
- ≥ 40% suggestion acceptance rate (accepted / (accepted + dismissed), from `WorkflowSuggestion.status`).
- −30% calls capped as UNRESOLVED ("workflow loop limit reached") on steps with accepted paths, compared with the 30 days before.

## Open questions (with a proposed answer)

1. **Runtime catch-all path ("Anything else") per question step?** Proposed: not in this phase. Measure UNRESOLVED caps after suggestions ship; revisit if they don't drop.
2. **Keep an "Added by AI" marker after Save?** Proposed: no marker on the graph. The accepted items in `WorkflowSuggestion` are enough for metrics and audit.
3. **Is 20 runs per workspace per day right?** Proposed: yes for launch; it is a setting (`SUGGEST_DAILY_LIMIT`), and failed runs don't count.
