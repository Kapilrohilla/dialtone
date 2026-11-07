# PRD: Suggest with AI — more answer paths and expressions for workflows

Date: 2026-11-07 · Owner: Kapil Rohilla · Status: Draft for review
Designs: Stitch project "Carrum Voice — Final", screens titled `Carrum Voice - Suggest paths 1–9 [Final · Dark]`

## 1. Summary

Workflow authors design question steps around the answers they expect ("Has licence" / "No licence"). Real callers answer in many more ways: "पता नहीं", "apply किया है, अभी आया नहीं", "पहले job बताओ". Today those answers match no path, so the agent improvises on the same step until it hits the loop cap and the call ends UNRESOLVED.

**Suggest with AI** lets an author ask Gemini to look at a step (or the whole workflow) and propose:

1. **Other answers** callers give, each as a new path (to an existing step or a new one), with example caller phrases.
2. **Expressions** for the agent's lines (`[pause 0.6s]`, `[sad]`, `[happy]`…), shown as a before/after.

Everything Gemini produces is a **draft**. Nothing in the workflow changes until the author accepts a suggestion. Authors can edit any suggestion before accepting, dismiss it, or undo.

## 2. Problem and evidence from the code

- A branch is just a `Path { from, to, label }` in the workflow graph (`console/src/lib/types.ts`). At runtime each path becomes a tool `go_to_<step>` whose **description is the label** (`agent/workflow.py`). The label wording is the whole classifier.
- There is **no fallback path**. If nothing matches, the LLM calls no tool and keeps talking on the current step. After 3 visits to a step or 25 transitions, the call is capped and recorded UNRESOLVED (`agent/workflow.py`, `CAPPED_MESSAGE`).
- Authors rarely think of the long tail (unsure, partial yes, counter-question, busy, wrong person), especially in Hinglish.
- Expressions exist (`[[expr:name]]`, `[[expr:pause:s]]`) but authors seldom add them. They become tone hints for the LLM at publish (`dashboard/voiceagents/publish.py`, `render_hints`).

## 3. Goals and non-goals

Goals
- Fewer calls stuck on a step: authors cover the common unmatched answers in minutes.
- Better-sounding agent lines through suggested expressions.
- The author stays in control: every AI change is reviewable, editable and reversible.

Non-goals (this release)
- Automatically changing live calls. Saving a workflow still only creates a revision; calls change when the agent is republished.
- Generating whole workflows from scratch.
- A runtime "catch-all / other" path type (see Open questions).
- Light-mode designs (dark set is final; light follows the same layout with light tokens).

## 4. Users and permissions

- **Editors, admins, owners** can run Suggest with AI, edit, accept and dismiss.
- **Viewers** see a pending draft banner ("4 suggestions are waiting for review") but cannot act on it.

## 5. User flow and states (one screen per state)

| # | State | Stitch screen | What the user sees |
|---|---|---|---|
| 1 | Start | `Suggest paths 1 Start` | "Suggest with AI" in the top bar (whole workflow) and "Suggest more answers" under a step's "Then go to" (this step). Popover: Look at (This step / Whole workflow), Suggest (Other answers / Expressions), draft note, "Suggest". |
| 2 | Generating | `Suggest paths 2 Generating` | Side panel checklist (reading the step, looking at past calls, writing answers, suggesting expressions), skeleton rows, Cancel. Canvas stays editable. |
| 3 | Review answers | `Suggest paths 3 Review answers` | Draft banner. Tabs Answers / Expressions. Each suggestion: path label, goes to (existing step or "New step"), "Caller might say" chips, one-line why, Accept / Edit / Dismiss. Dashed blue paths and cards on the canvas. Accept all / Discard all. |
| 4 | Review expressions | `Suggest paths 4 Review expressions` | Per step: "Now" line vs "Suggested" line with the added chip outlined. Footnote: hints, not exact audio. |
| 5 | Edit suggestion | `Suggest paths 5 Edit suggestion` | Path name, example phrases (add/remove), Then go to, new step name and line (token editor with Expression menu), After this step go to. Save to draft / Accept. |
| 6 | Partly accepted | `Suggest paths 6 Partly accepted` | Progress "2 accepted, 1 dismissed, 1 left". Accepted paths become solid with an "Added" marker; "Unsaved changes" next to the breadcrumb; Undo on each row and an Undo toast. |
| 7 | Saved draft + Save dialog | `Suggest paths 7 Saved draft and Save dialog` | Returning later: banner with author and time, Review / Discard draft. Pressing Save with pending items explains that only accepted items are saved and that calls change only on agent republish. |
| 8 | Nothing to suggest | `Suggest paths 8 Nothing to suggest v2` | Empty state with what was checked and "Look at the whole workflow". |
| 9 | Error / out of date / conflict | `Suggest paths 9 Error and out of date` | Gemini timeout ("Nothing in your workflow changed", Try again); draft out of date after someone edited the step (Suggest again / Review anyway); single suggestion that can't be accepted (duplicate label → Edit). |

Visual language: AI = cool blue (system colour); suggested items use dashed cool-blue lines and a "Suggested" chip; the only amber button remains "Save".

## 6. Functional requirements

### 6.1 Running a suggestion
- FR1. Scope is **This step** (selected step) or **Whole workflow** (all `prompt`/`collect`/`knowledge` steps, max 15 steps per run).
- FR2. Kinds are **Other answers** and/or **Expressions**; at least one must be selected.
- FR3. Gemini receives: the steps in scope (name, type, prompt, field, existing path labels and targets), the full list of step names (so it can target existing steps), the agent's language and persona summary, the expression catalogue (8 built-ins + the agent's `custom_expressions`), and the dispositions available to end steps.
- FR4. **Phase 2:** also send up to 30 recent anonymised caller turns captured on the step when no path was taken (from `CallEvent` turns between `step_entered` events). Phone numbers and names are redacted before sending.
- FR5. Only one run per workflow at a time; a new run replaces the previous **pending** draft after confirmation.
- FR6. The user can keep editing while a run is in progress; Cancel stops the run and stores nothing.

### 6.2 Suggestion types
- **New path to an existing step**: `{ from, to, label, examples[], why }`.
- **New path + new step**: as above plus `{ new_step: { name, type: "prompt", prompt, then_to } }`. The new step gets one path back to a chosen step (default: the source step) so the graph stays valid.
- **Expression**: `{ step_id, before, after, why }` where `after` is the prompt with added `[[expr:…]]` tokens only — Gemini must not rewrite the words.

### 6.3 Rules every suggestion must pass (checked server-side before it is shown and again on accept)
- Path label: non-empty, ≤ 60 characters, unique among the step's paths (same rule as `graph.validate`).
- Labels must describe the caller's answer, not the agent's action, and must not overlap an existing label's meaning (Gemini is instructed; the server rejects exact or near-exact duplicates).
- Target step exists, or the suggestion carries a valid new step.
- Expressions: only known names; pauses ≤ 10 s; at most 2 added tokens per line.
- End steps get no new outgoing paths. Transfer steps are skipped.
- Max 5 answer suggestions per step and 1 expression suggestion per line.

### 6.4 Review, edit, accept
- FR7. **Accept** applies the change to the builder's working graph using the existing pure helpers (`addPath`, `addStep`, `updateStep` in `console/src/components/workflow/graph.ts`). The page shows "Unsaved changes"; the normal **Save** creates a new `WorkflowRevision`.
- FR8. **Edit** lets the user change label, examples, target, new step name/line and follow-on step. Edits are stored in the draft ("Save to draft") or applied directly ("Accept").
- FR9. **Dismiss** hides the item; **Undo** is available on accepted and dismissed rows until the draft is closed, plus a toast for the last action.
- FR10. **Accept all / Discard all** per tab.
- FR11. Suggestions that conflict at accept time (label now exists, target deleted) stay pending with an inline message and an Edit action.

### 6.5 Draft persistence
- FR12. Drafts are stored on the server so they survive reloads and are visible to teammates (banner with author and time).
- FR13. A draft records the workflow revision it was made from. If the current revision differs, show "out of date"; items whose source step, target step or label changed are marked invalid; others can still be reviewed.
- FR14. Saving the workflow with pending items keeps them in the draft (dialog in screen 7). Discarding the draft deletes all pending items.
- FR15. Drafts older than 30 days are deleted.

### 6.6 Example phrases at runtime
- FR16. Add optional `examples?: string[]` to `Path` (max 5, each ≤ 40 characters). The runtime appends them to the tool description: `"{label}. The caller might say: {examples}"` (`agent/workflow.py` `path_tool_schema`). This improves classification for all paths, not only AI ones. Authors can also edit examples on any path in "Then go to".

## 7. Data model and API

```
WorkflowSuggestionSet
  workflow            FK Workflow
  base_revision       FK WorkflowRevision
  scope               "step" | "workflow"
  step_ids            JSON list
  kinds               JSON list ("answers", "expressions")
  status              "running" | "ready" | "failed" | "closed"
  error               text, nullable
  created_by, created_at, updated_at

WorkflowSuggestion
  set                 FK WorkflowSuggestionSet
  kind                "path" | "path_new_step" | "expression"
  payload             JSON (shapes in 6.2)
  edited_payload      JSON, nullable (user edits)
  status              "pending" | "accepted" | "dismissed" | "invalid"
  invalid_reason      text, nullable
  position            int
```

API (Django, `dashboard/workflows/`):
- `POST /api/workflows/<id>/suggestions` `{ scope, step_ids, kinds }` → `202 { set_id }`; work runs async with a 30 s budget.
- `GET /api/workflows/<id>/suggestions/current` → the open set with items and an `out_of_date` flag.
- `PATCH /api/workflows/<id>/suggestions/<item_id>` `{ status?, edited_payload? }`.
- `POST /api/workflows/<id>/suggestions/<set_id>/close` (discard draft).
- Accepting does **not** write the graph server-side; the console applies the change and uses the existing `PATCH /api/workflows/<id>` Save. Item status is updated to `accepted` alongside.

## 8. Gemini integration

- Model: `gemini-2.5-flash` (env `SUGGEST_LLM_MODEL`, default same as `SIM_LLM_MODEL`), called with the `google-genai` SDK from Django, `GOOGLE_API_KEY` as today. Structured output with a JSON response schema matching 6.2; temperature 0.4.
- Prompt instructs: Hindi/Hinglish caller phrasing; labels describe the caller's answer in plain English sentence case; prefer existing steps over new ones; never invent prices, offers or figures (knowledge rule); never change the agent's words when adding expressions.
- Timeout 20 s per call, one retry on transient errors; whole-workflow runs batch steps (≤ 5 steps per call).
- Responses are validated against 6.3; failing items are dropped and counted (telemetry), never shown.
- Cost guardrail: max 20 runs per workspace per day (configurable).

## 9. Success metrics

- Adoption: % of saved workflows with at least one accepted suggestion (target 50% in 60 days).
- Quality: acceptance rate of suggestions (target ≥ 40%), edit-before-accept rate.
- Outcome: on steps with accepted paths, drop in calls capped as UNRESOLVED and in repeat visits to the same step (target −30% vs the previous agent version).
- Reliability: generation success rate ≥ 97%, p95 latency ≤ 15 s for a single step.

## 10. Risks and mitigations

- **Overlapping labels confuse the LLM.** Server de-duplicates; Try it encourages testing; examples sharpen labels.
- **Hallucinated policy or prices in new step lines.** Knowledge rule in the prompt; new steps default to short clarifying lines; the user reviews every line.
- **Expressions are hints only** (they don't reach TTS). UI says so; don't promise exact audio.
- **Privacy** when sending past caller turns (phase 2): redaction, feature flag, workspace setting to opt out.
- **Draft vs. Save confusion.** Clear banner and Save dialog; accepted items become normal unsaved changes.

## 11. Rollout

1. Phase 1 (flag `ai_suggestions`): step scope, answers + expressions, server drafts, `Path.examples` in runtime and builder.
2. Phase 2: whole-workflow scope, past-call turns as input, "Suggest again" for out-of-date drafts.
3. Phase 3: light-mode polish, per-workspace daily limits in Settings.

## 12. Open questions

1. Should we add a runtime **catch-all path** ("Anything else") per question step, so unmatched answers have a defined route instead of the loop cap?
2. Should accepted AI paths keep an "Added by AI" marker after Save (audit), or disappear?
3. Do whole-workflow runs need a step picker, or is "all question steps" enough?
4. Daily run limit per workspace: 20 a good default?

## 13. Acceptance criteria (phase 1)

- Running Suggest on a collect step with two paths returns 1–5 valid answer suggestions in Hindi/Hinglish context and 0–N expression suggestions, or the empty state.
- No graph change happens until Accept; Accept + Save produces a revision that passes `graph.validate`.
- Reloading the page restores the pending draft; a teammate sees the banner.
- Editing the source step after generation marks affected items invalid and shows the out-of-date state.
- Gemini timeout shows the error state and leaves the workflow untouched.
- Viewers cannot run, accept or dismiss.
