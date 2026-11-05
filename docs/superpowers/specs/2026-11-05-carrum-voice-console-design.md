# Carrum Voice console — design

Date: 2026-11-05. Status: ready for approval.

## Intent

Today the calling agent's behaviour lives in code: the script in `agent/agent.py`, approved pricing in `agent/knowledge.md`, the conversation order hard-coded in `BASE_INSTRUCTIONS`, and settings in `.env`. Changing a pitch means a developer edits Python and redeploys. The dashboard (`dashboard/`, Django) only shows calls.

The console turns this into a logged-in product where Carrum's ops team, without a developer, can:

- write an agent's script, with inline voice **expressions** such as `[laugh]`, `[whisper]` or `[pause 1.2s]`, and `{{lead.city}}`-style variables;
- attach **knowledge** documents (Markdown or rich text) the agent may quote;
- build the call as a **workflow** of steps, each with its own prompt, and have the agent actually follow it;
- **publish** one agent to answer calls;
- watch **live calls** (transcript, current step, mood), listen in, transfer or end them;
- review **call history** with outcome, summary, answers and transcript;
- manage their **profile** and appearance (light/dark).

It is for Carrum's internal team first, but built so outside companies can be added later.

## Goals

1. A Next.js front end implementing the final Stitch designs (project "Carrum Voice — Final", ten screens, light and dark).
2. A Django JSON API behind it, extending the existing `dashboard` app and database.
3. The voice agent loads the **published** agent's script, knowledge and workflow from the API at the start of every call, and follows the workflow step by step.
4. Workspace-scoped data from day one (one workspace, "Carrum Mobility").
5. Everything existing keeps working: LiveKit webhooks, per-call reports, call history, mood evaluation tooling, deploy scripts.

## Non-goals (this release)

- Public signup, billing, plans. (Users are created by an admin; Billing is a "Soon" item.)
- Real integrations. The Integrations screen is a static "Coming soon" list plus a "Request an integration" form that emails/stores the request.
- Purposes (sales/support/marketing) with a number or trunk each. Planned next; the model leaves room for it (see "Later").
- Buying or provisioning phone numbers in the app. Trunks stay set up by `scripts/setup-sip.sh`.
- Exact audio expressions. Expressions are tone hints to the model (see below), not SSML/audio tags.
- Mobile layouts beyond "usable": the console is a desktop tool; screens must not break below 60rem but need no bespoke mobile design.

## Anti-goals (would be a failure even if it works)

- Calling a driver without saying the call is recorded.
- The agent quoting a price, offer or payout that is not written in a published knowledge document.
- A call failing or going silent because the console/API is down. The agent must fall back to the last good config it fetched, or to today's built-in script.
- Editing a draft changing a live call. Only **publishing** changes what callers hear; a call keeps the version it started with.
- Losing the call history and reports already recorded.
- A design that looks like a generic AI SaaS template (the design work so far exists to avoid that; follow the Stitch screens and the rules below).

## Constraints

- Existing stack: Django 5.2, PostgreSQL 16 (replacing SQLite at the user's request, 2026-11-05; existing call history is copied over once), uvicorn, whitenoise; LiveKit Agents 1.8.5 (Python) with three pipelines (gemini-live default, sarvam, elevenlabs). One GCP VM, `network_mode: host`, docker compose, `scripts/deploy.sh`.
- The dashboard listens on 127.0.0.1 only and is reached via `make tunnel` (SSH). The console keeps that model for this release: no public exposure, so HTTPS settings stay off.
- Agent → dashboard calls are already authenticated with a short-lived LiveKit-signed JWT (`agent/report.py`, `report_ingest`). Reuse that for the new runtime endpoints.
- Hindi/Hinglish (Devanagari) text everywhere: fonts and inputs must handle it.
- Tests: pytest exists for agent and dashboard; new code ships with tests.

## Decisions made with the user

- **Scope:** everything, including a working workflow builder the agent follows.
- **Expressions:** tone hints. A chip becomes a short delivery instruction to the model for the line that follows (e.g. `[laugh]` → "say this with a light, warm laugh"; `[pause 1.2s]` → "pause briefly before this"). Works on Gemini Live; on the cascaded pipelines the same hints go into the LLM prompt.
- **Front end:** Next.js talking to a Django API.
- **Workspaces:** yes, every record belongs to a workspace; only Carrum exists for now.
- **Visual design:** the final Stitch screens, theme "Console", light (warm paper) and dark (graphite), simplified. Design rules and tokens: `docs/superpowers/specs/assets/final-screens.md` (copy of the Stitch spec; move it there from the scratchpad).

## Architecture

```
Browser ──(SSH tunnel)──► Next.js (127.0.0.1:3000)
                              │  /api/* rewritten to
                              ▼
                         Django API (127.0.0.1:8787)  ◄── LiveKit webhooks (/webhook)
                              │  PostgreSQL           ◄── agent: config fetch, turn events, reports
                              ▼
                         LiveKit server API (rooms, SIP transfer, tokens)
```

- **Next.js** (App Router, TypeScript) in a new `console/` folder and its own container `console` (`network_mode: host`, port 3000). Next.js rewrites `/api/*` and `/webhook` to Django so the browser sees one origin: Django session cookies and CSRF work without CORS.
- **Django** keeps the `calls` app and adds a `console` app (or `accounts`, `agents`, `knowledge`, `workflows` apps; builder's call) exposing JSON via Django REST Framework (new dependency). The old `index.html` dashboard can be retired once the Next.js screens cover it.
- **Auth:** Django session auth. Email + password login; "Continue with Google" is shown in the design but can be hidden until Google OAuth is configured (builder may ship it disabled). Users are created by an admin (Django admin or a management command). No signup page.
- **Agent:** fetches config from Django at call start; posts turn events during the call; posts the final report as today.

## Data model (new, all with `workspace` FK)

- **Workspace**: name, slug. One row: Carrum Mobility.
- **Membership**: user ↔ workspace, role (`owner`, `admin`, `editor`, `viewer`). Viewers can't edit or publish.
- **UserPreference**: appearance (`light`/`dark`/`system`), notification switches, time zone.
- **Agent**: name, description, language (e.g. Hindi + Hinglish), voice (persona name + pipeline voice id), pipeline (`gemini-live`/`sarvam`/`elevenlabs`), behaviour settings (mood adaptation on/off, dead-air check-ins on/off + timings under "Advanced"), status (`draft`/`published`/`archived`), the phone number it answers (string), linked knowledge documents, linked workflow.
- **AgentVersion**: an immutable snapshot taken on publish: script, settings, knowledge text, workflow graph, created_by, created_at. The agent at runtime always gets a version, never a live draft. **Only one agent per workspace is published at a time**; publishing another unpublishes the current one (confirmation dialog, as designed).
- **Script**: belongs to an agent; ordered sections (title + body). Body is stored as structured text: plain text with tokens for expressions `[[expr:laugh]]`, `[[expr:pause:1.2]]` and variables `{{lead.city}}`. The editor renders tokens as chips.
- **KnowledgeDocument**: title, body (Markdown is the stored format; the rich-text editor reads and writes Markdown), may contain expression chips in sample lines; version history (simple: keep each saved revision with editor and time).
- **Workflow**: name, status, graph JSON: steps (id, name, type, prompt, knowledge doc, position on canvas) and paths (from step, label/condition, to step). Step types: `prompt` (agent speaks/asks), `collect` (capture a named field, e.g. licence), `knowledge` (answer from a doc), `transfer` (to telecaller), `end` (with an outcome code). One `start` step.
- **Existing `Call`, `CallReport`, `TurnLabel`** gain `workspace` and `agent_version` FKs (nullable for old rows; a data migration assigns existing rows to Carrum).
- **CallEvent**: room, sequence, type (`turn`, `step_entered`, `mood`, `field_captured`), payload JSON, timestamp. Feeds Live calls and the call-history transcript.
- **IntegrationRequest**: who, what tool, note.

## How the agent uses it

1. **Config fetch.** At call start, `entrypoint` calls `GET /api/runtime/config?number=<called number>` (JWT as for reports). Django returns the published `AgentVersion` for the workspace that owns that number: persona, language, pipeline choice, voice, behaviour settings, knowledge text, the script and the workflow graph. The agent caches the last good response on disk; if the fetch fails or times out (~1.5 s budget), it uses the cache, and with no cache, today's built-in `BASE_INSTRUCTIONS` and `knowledge.md`. The version id is recorded on the call.
2. **Script and expressions.** The script's sections become the base instructions. Expression tokens are rendered into tone hints ("(say this warmly, with a light laugh)") and variable tokens are filled from the lead record (dispatch metadata) or dropped with a neutral phrasing if missing. The existing tone guide, greeting gate, dead-air watcher, mood adaptation and handoff keep working.
3. **Workflow.** Each step becomes a LiveKit `Agent` (or a single agent whose instructions are swapped per step; builder's call after a spike). The step's prompt is its instructions; each outgoing path is a function tool the model calls when that condition is met (e.g. `go_to_explain_the_plan` with the path label as the tool description). `collect` steps also record the captured field; `transfer` uses the existing `transfer_to_telecaller`; `end` calls `record_outcome` with the step's outcome code, says its closing line and `end_call`. Entering a step emits a `step_entered` event. Guard rails: a step-visit cap and an overall turn cap so a looping graph can't trap a caller; on a broken graph (no start, dangling path) the API refuses to publish.
4. **Events.** The agent posts `turn` (speaker, text, expressions used), `step_entered`, `mood` and `field_captured` events to `POST /api/runtime/events` in small batches (fire-and-forget, never blocks speech). The final report (`/api/report`) is unchanged, plus the version id and step path.
5. **Knowledge rule.** The agent's instructions keep today's rule: quote only figures present in the knowledge text; otherwise refer to the telecalling team.

## Screens (from the Stitch "Final" project)

Shell: left sidebar (Dashboard, Agents, Workflows, Knowledge base, Live calls with active count, Call history, Integrations "Soon", Settings), user at the bottom with a light/dark toggle; top bar with title and one primary action.

1. **Sign in** — email/password (Google button optional), "Ask your workspace admin for an invite".
2. **Dashboard** — today's calls, connected %, interested, average call (from `Call`/`CallReport`); "Needs a person" (calls whose outcome or mood asks for a human callback, with "Call back" marking them handled); outcomes this week; the live agent.
3. **Agents** — "Answering calls now" panel; table with Publish/Unpublish (confirmation), Duplicate, Archive, Restore; New agent.
4. **Agent script editor** — sections, chips, variables, Expression menu (the 8 expressions + custom expression = a named hint the user writes), Voice (with Preview: a short TTS sample of the first line), Knowledge links, Behaviour switches, Advanced (dead-air timings, pipeline). Test call: opens the text simulation with the draft config (see decisions).
5. **Workflow builder** — canvas of steps and labelled paths, add/connect/delete steps, side panel to edit the selected step, validation on publish, "Try it" = a text simulation in the browser where the user plays the caller and sees which step the agent is in (uses the same LLM and step logic via an API endpoint).
6. **Knowledge base** — document list, editor (Rich text ⇄ Markdown), upload `.md`, version history, "The agent only quotes what is written here."
7. **Live calls** — active calls (from LiveKit room state + `CallEvent`s), transcript updating live (polling every 1–2 s or server-sent events), current step, captured details, mood; Transfer to a telecaller (LiveKit SIP transfer to `HANDOFF_SIP_URI`), End call (remove the SIP participant / delete room).
8. **Call history** — filters (search number, outcome, agent, more: mood, city, date range), table, slide-over with the recording player, summary, answers, transcript; Export CSV.
9. **Settings** — profile, password, appearance, notifications; Team (list/invite/role) and Phone numbers (read-only list from LiveKit trunks) as simple pages.
10. **Integrations** — static list, "Request an integration".

Visual rules (from the Hallmark/Console design work, binding): tokens for every colour and font (light and dark from one token set, hue never moves), Hanken Grotesk + JetBrains Mono (numbers, phones, times only), amber = person / one primary action, cool blue = agent/system, sentence-case labels (no tracked capitals), no middle-dot strings, no decorative dots, no cards inside cards, no invented figures, visible focus states, reduced-motion fallbacks. Every data region has loading, empty, error and full states.

## Later (shape the model, don't build)

- **Purposes**: a workspace defines purposes (Sales, Marketing, Support…) in Settings; each purpose owns a number/trunk; "one published agent per purpose" replaces "one per workspace". Plan: add `Purpose` with a number, put `purpose` on `Agent`, change the uniqueness rule.
- More workspaces, signup, billing, real integrations, exact audio expressions on ElevenLabs v3.

## Left to the builder

- App split inside Django, DRF serializer shapes, URL naming.
- Next.js libraries: canvas (e.g. React Flow), rich-text editor (e.g. TipTap with custom chip nodes), data fetching, styling (CSS variables + CSS modules or Tailwind mapped to the tokens).
- Polling vs SSE for live data.
- One-agent-per-step vs instruction swapping in the LiveKit workflow runtime.
- Exact wording of tone hints per expression.

## Decisions after the builder check

Answered by the user:

- **Inbound only.** No outbound trunk this release. `{{lead.*}}` variables fill only when a lead record arrives as dispatch metadata; otherwise the agent uses a neutral phrasing. "Call again" / "Call back" mark the call as needing a telecaller (status on the call, shown in "Needs a person"); they do not dial. The "Send WhatsApp details" button is removed.
- **Record calls.** Add a LiveKit Egress service (audio-only room recording) to docker compose. Files go to the VM disk under the dashboard data volume (`/data/recordings/<room>.ogg`) and are served by Django to logged-in members only. The agent's opening line gains a short consent notice ("yeh call quality ke liye record ho rahi hai"). Recordings follow the same 90-day retention as transcripts (my call; easy to change).
- **Listen in deferred.** Live calls ships live transcript, current step, captured details, mood, Transfer and End call. No Listen in button this release (needs LiveKit reachable from ops laptops behind TLS/TURN).
- **Retention 90 days.** A daily job deletes `CallEvent` turn rows, `TurnLabel` text and recordings older than 90 days; outcomes, summaries, captured answers and metrics stay.

My calls (change any of them before planning if you disagree):

- **Prompt layers.** At runtime the agent's instructions are assembled as: (1) a fixed **system layer** in code that ops cannot edit — AI disclosure, never ask for Aadhaar/PAN/bank details, the knowledge-only pricing rule, `record_outcome` rules and disposition definitions, pronunciation of "Carrum", tone guide, dead-air and handoff behaviour (today's non-script parts of `BASE_INSTRUCTIONS`); (2) the **agent script** (persona, how to talk, what to cover) — present in every step; (3) the **current workflow step's prompt** and its paths. An agent without a workflow runs on layers 1 and 2 alone, like today. The seed data moves today's script content into a "Driver lead qualifier" agent.
- **Publishing.** Only publishing an **agent** changes calls. Saving a knowledge doc or saving/publishing a workflow creates a new revision; the Agents screen and the agent's page then show "Uses an older version — Republish". Republish snapshots the current script, linked knowledge revisions and workflow revision into a new `AgentVersion`. The workflow screen's button is "Save" (not "Publish") to avoid implying it changes calls.
- **Outcomes and fields.** The 14 existing disposition codes stay fixed (end steps pick one). The screens group them into five display outcomes: Interested ← INTERESTED; Call back ← CBR; Not interested ← NI, NE, ISUDO, ISUID, OWNVA, ABULR, WRGN, LANGUAGE_BARRIER, HND; Dropped ← CDRP, UNRESOLVED; Not reached ← NOT_CONNECTED. (Builder confirms each code's meaning against the definitions in `agent/agent.py` and adjusts the grouping if one is clearly misplaced.) The existing qualification fields stay; `collect` steps may also define extra named fields, stored as generic answers.
- **Pipeline.** Stays a worker setting (`AGENT_PIPELINE`) this release; the console shows it read-only on the agent. Voice choice applies within that pipeline.
- **Test call.** Because browsers can't reach LiveKit over the tunnel, "Test call" opens the same text simulation as the workflow builder's "Try it" (draft config, user types as the caller). A voice test comes with Listen in.
