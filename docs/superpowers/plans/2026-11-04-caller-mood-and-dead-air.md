# Caller Mood, Dead Air and Adaptive Tone: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The phone agent notices silence and the caller's mood (from their words and their behaviour on the call), and adjusts what it says, how fast it speaks and where it steers the call.

**Architecture:** Small pure-Python modules hold all the logic: dead-air timing, mood smoothing, tone policy, behaviour features, reports. They are unit-tested without LiveKit. `agent/agent.py` only wires LiveKit session events into them and applies their decisions: `generate_reply` for nudges, a system note in the chat context for tone, `tts.update_options` for speed. Classification runs in background tasks and only affects the **next** reply, so it never adds latency. A per-call report goes to the dashboard for review and evaluation. The dashboard is rebuilt as a Django project. It keeps the same URLs and port, so LiveKit's webhook config and the agent need no changes. The agent stays a plain LiveKit worker, because a real-time audio worker can't run inside Django.

**Tech Stack:** Python 3.12, livekit-agents 1.8.5 (pinned), its google/openai/sarvam/elevenlabs plugins, pytest + pytest-asyncio. Dashboard: Django 5.2 LTS (async views, admin), uvicorn (ASGI), whitenoise (static files), SQLite, livekit-api, pytest-django.

**Spec:** The design reply in this session, summarised under "Design" below. There is no separate spec file.

## Design (summary of the agreed approach)

- Calls are audio-only over SIP (8 kHz G.711). There is no face, so "expressions/micro-expressions" means voice and behaviour signals: words, interruptions, reply latency, reply length, silence.
- **Phase 1:** dead-air handling (caller silence escalates nudge → second nudge → polite hang-up) plus per-turn latency metrics. Gemini's `GEMINI_AFFECTIVE_DIALOG` gets A/B tested (config only).
- **Phase 2:** an LLM classifies each caller turn into a mood. A tracker smooths it (hysteresis), and a fixed tone policy turns the mood into a prompt note and a TTS speed.
- **Phase 3:** behaviour features (interruptions, short/slow replies) feed the same tracker. Optional live handoff to a telecaller.
- **Phase 4:** port the dashboard from aiohttp to Django at feature parity. Then the agent sends a per-call report → Django (mood column, timeline, admin). Telecallers label caller turns in the Django admin, and a management command scores accuracy.
- **Out of scope until Phase 4 data says otherwise:** a speech-emotion-recognition model on raw audio. We record no call audio today, and 8 kHz SER accuracy is unproven.

## Global Constraints

- Agent: keep `livekit-agents==1.8.5` and add no new runtime dependencies. Dev-only: `pytest`, `pytest-asyncio` in `agent/requirements-dev.txt`.
- Dashboard: `Django` 5.2.x (LTS), `uvicorn`, `whitenoise` and the existing `livekit-api==1.2.1`, plus dev-only `pytest-django`. Pin each exactly to the newest patch release that is at least two weeks old (check with `pip index versions <pkg>`). Never use unpinned versions.
- Dashboard URLs stay `/`, `/api/state` and `/webhook` on `127.0.0.1:8787`, and the `/api/state` JSON shape stays the same, so `docker-compose.yml`'s webhook URL and the existing page logic carry over unchanged.
- The dashboard stays localhost-only (reached with `make tunnel`), and every page now also requires a Django login. `/webhook` and `/api/report` use LiveKit-signed tokens instead of a login and are CSRF-exempt.
- New logic modules (`dead_air.py`, `mood.py`, `tone.py`, `behavior.py`, `sentiment.py`, `metrics.py`, `report.py`) must not import `agent.py`. They take time as a `now: float` argument (seconds, monotonic) so tests need no real clock.
- Every new feature can be switched off with an env var, documented in `.env.example`: `DEAD_AIR_ENABLED` (default `true`), `MOOD_ENABLED` (default `false` until Phase 4 eval passes), `HANDOFF_SIP_URI` (empty = off), `DASHBOARD_REPORT_URL` (empty = off).
- Nothing new may raise into the call. Background tasks catch, log once (`logger.warning`) and carry on. All tasks are cancelled in the session `close` handler.
- The agent must never tell the caller it detected their mood. Every tone note says so.
- Mood detection works on both pipelines (`gemini-live` and cascaded). TTS speed changes apply only to cascaded pipelines. Gemini gets the prompt note only.
- Store mood labels, not audio. Turn text goes into reports only when `MOOD_EVAL_CAPTURE=true`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Caller says "ek minute" and puts the phone down for 40 s.** Expect no hang-up at 15 s: hold phrases triple the thresholds for that silence only. Test in Task 1.
2. **Classifier times out, errors or returns junk.** The call continues unchanged, with no mood change and one warning per call. Test in Task 5.
3. **The agent's own nudges count as "activity" and reset the silence clock forever.** Expect silence to accumulate across nudges and reset only on caller activity. Test in Task 1.
4. **A single curt "nahi" (a plain refusal) flips the agent into apology mode.** Expect no switch from one reading. Two agreeing readings are needed, except high-confidence anger. Test in Task 4.
5. **The dashboard receives a report before the LiveKit `room_finished` webhook, or for a room it never saw.** Expect the report stored and shown, with no 500. Test in Task 11.
6. **Deploying the Django dashboard on a VM that already has `/data/calls.db` history.** Expect the old calls to still show after the switch, and re-running the import to create no duplicates. Test in Task 10.

---

## Phase 1: Dead air and latency

### Task 1: Dead-air watcher

**Files:**
- Create: `agent/dead_air.py`, `agent/requirements-dev.txt`, `agent/tests/__init__.py`, `agent/tests/test_dead_air.py`, `agent/pytest.ini`
- Modify: `Makefile` (add `test` target)

**Interfaces:**
- Produces:
  - `DeadAirAction = Literal["nudge", "second_nudge", "hang_up"]`
  - `@dataclass(frozen=True) class DeadAirConfig: nudge_s: float = 4.0; second_nudge_s: float = 9.0; hang_up_s: float = 15.0; hold_multiplier: float = 3.0`
  - `HOLD_PHRASES: tuple[str, ...] = ("ek minute", "ek min", "ek second", "do minute", "ruko", "rukiye", "hold", "wait", "one minute", "one second")`
  - `class DeadAirWatcher(config: DeadAirConfig)` with:
    - `agent_listening(now: float) -> None`: the agent is idle and waiting. Silence accumulates only in this state.
    - `agent_busy(now: float) -> None`: the agent is thinking or speaking. Accumulation pauses, but nothing resets.
    - `user_activity(now: float, text: str = "") -> None`: resets accumulated silence and fired actions to zero. If `text` contains a hold phrase (case-insensitive), the next silence uses thresholds × `hold_multiplier`.
    - `poll(now: float) -> DeadAirAction | None`: returns each action at most once per silence, in order.
    - `events: list[dict]`: one `{"action": str, "silence_s": float}` per fired action.

- [ ] **Step 1: Scaffolding.** `requirements-dev.txt`: `-r requirements.txt`, `pytest==8.3.3`, `pytest-asyncio==0.24.0`. `pytest.ini`: `testpaths = tests`, `asyncio_mode = auto`, `pythonpath = .`. Makefile: `test: ; cd agent && .venv/bin/pytest -q`. Task 10 adds the dashboard line, because pytest exits non-zero when it collects no tests.
- [ ] **Step 2: Write failing tests** in `test_dead_air.py`:
  - `test_nudges_then_hangs_up`: `agent_listening(0)`; `poll(3.9) is None`; `poll(4.0) == "nudge"`; `poll(5) is None`; `poll(9) == "second_nudge"`; `poll(15) == "hang_up"`; `poll(20) is None`.
  - `test_agent_speech_pauses_but_does_not_reset`: listening at 0, `poll(4)=="nudge"`, `agent_busy(4)`, `agent_listening(7)` → `poll(11.9) is None`, `poll(12) == "second_nudge"` (4 s + 5 s accumulated = 9).
  - `test_user_activity_resets`: listening 0, poll(4) nudge, `user_activity(5)`, `agent_listening(6)` → `poll(9.9) is None`, `poll(10) == "nudge"`.
  - `test_hold_phrase_triples_thresholds_once`: `user_activity(0, "Haan ek minute ruko")`, `agent_listening(0)` → `poll(11.9) is None`, `poll(12)=="nudge"`, `poll(45)=="hang_up"`. Then `user_activity(50)`, `agent_listening(50)` → `poll(54)=="nudge"`.
  - `test_no_silence_counted_before_first_listening`: `poll(100) is None` on a fresh watcher.
  - `test_events_recorded`: after nudge at 4, `events == [{"action": "nudge", "silence_s": 4.0}]`.
- [ ] **Step 3: Run** `make test`. Expected: FAIL, `ModuleNotFoundError: dead_air`.
- [ ] **Step 4: Implement** `agent/dead_air.py` to the interface above.
- [ ] **Step 5: Run** `make test`. Expected: 6 passed.
- [ ] **Step 6: Commit** `feat(agent): dead-air watcher with hold detection`.

### Task 2: Wire dead air into the call

**Files:**
- Modify: `agent/agent.py` (`PhoneAgent.__init__`, `entrypoint`), `.env.example`, `README.md` ("What the agent does")

**Interfaces:**
- Consumes: `DeadAirWatcher`, `DeadAirConfig` (Task 1).
- Produces: `PhoneAgent.dead_air_events` is carried into the `call ended` log as `"dead_air": watcher.events`. Env vars: `DEAD_AIR_ENABLED=true`, `DEAD_AIR_NUDGE_S=4`, `DEAD_AIR_SECOND_NUDGE_S=9`, `DEAD_AIR_HANG_UP_S=15`.

- [ ] **Step 1: Feed events.** In `entrypoint`, if `DEAD_AIR_ENABLED`:
  - `session.on("agent_state_changed")`: `"listening"` → `watcher.agent_listening(t)`; `"thinking"`/`"speaking"` → `watcher.agent_busy(t)`.
  - `session.on("user_state_changed")`: `"speaking"` → `watcher.user_activity(t)`.
  - The existing `conversation_item_added` handler, user role → `watcher.user_activity(t, text)`. This second source covers Gemini Live, in case it doesn't emit user speaking state.
  - Use `t = time.monotonic()`.
- [ ] **Step 2: Poll loop.** After the greeting, add an `asyncio.create_task` loop that calls `watcher.poll(time.monotonic())` every 0.5 s:
  - `"nudge"` → `session.generate_reply(instructions="The driver has gone quiet. In one short sentence, gently check if they can hear you, e.g. 'Hello sir, aap sun pa rahe hain?'")`
  - `"second_nudge"` → `session.generate_reply(instructions="Still no reply. In one short sentence, say the line may be unclear and ask once more if they can hear you; say you'll try again later if not.")`
  - `"hang_up"` → if `agent.outcome is None`, set it to `{"disposition": "NOT_CONNECTED" if driver never spoke else "UNRESOLVED", "reason": "caller silent for 15 s"}`. Then `await session.generate_reply(instructions="Say a brief polite goodbye: you'll try again another time.")`, wait for playout, and `delete_room()`. Reuse the "driver spoke" check from `_on_close` by extracting it into `def driver_spoke(session) -> bool`.
  - Cancel the loop in `_on_close`.
- [ ] **Step 3: Config.** Read thresholds from env into `DeadAirConfig`. Add the four vars to `.env.example` with one comment line. Add one README bullet: "Dead air: …".
- [ ] **Step 4: Verify** on a real call with `make deploy` and `scripts/test-call.sh`, once with `AGENT_PIPELINE=gemini-live` and once with `sarvam`. Answer, then stay silent. Expected in `make logs s=agent`: a nudge at about 4 s, a second at about 9 s, a goodbye and hang-up at about 15 s, and `call ended` with `"dead_air": [3 events]` and disposition `UNRESOLVED`. Repeat, saying "ek minute" before going silent. Expected: no nudge before about 12 s.
- [ ] **Step 5: Commit** `feat(agent): nudge and hang up on caller silence`.

### Task 3: Latency metrics

**Files:**
- Create: `agent/metrics.py`, `agent/tests/test_metrics.py`
- Modify: `agent/agent.py` (`entrypoint`)

**Interfaces:**
- Produces: `class LatencyStats` with `add(kind: Literal["eou", "llm_ttft", "tts_ttfb"], seconds: float) -> None` and `summary() -> dict[str, dict[str, int]]`. The summary looks like `{"eou": {"p50_ms": 640, "p95_ms": 900, "n": 7}, ...}`, omits kinds with no samples, and uses nearest-rank percentiles.

- [ ] **Step 1: Failing tests.** `test_summary_percentiles`: add eou 0.1…1.0 (10 values) → `summary()["eou"] == {"p50_ms": 500, "p95_ms": 1000, "n": 10}`. `test_empty_kinds_omitted`: `LatencyStats().summary() == {}`. `test_negative_ignored`: `add("llm_ttft", -1)` leaves the summary empty.
- [ ] **Step 2: Run** `make test`. Expected: FAIL.
- [ ] **Step 3: Implement** `metrics.py`.
- [ ] **Step 4: Run** `make test`. Expected: PASS.
- [ ] **Step 5: Wire.** `session.on("metrics_collected")`: `EOUMetrics.end_of_utterance_delay` → `"eou"`, `LLMMetrics.ttft` → `"llm_ttft"`, `TTSMetrics.ttfb` → `"tts_ttfb"`. Gemini realtime emits `RealtimeModelMetrics`; map its `ttft` to `"llm_ttft"`. Add `"latency": stats.summary()` to the `call ended` log.
- [ ] **Step 6: Verify and A/B.** Make one call per pipeline. Expected: `call ended` includes the latency summary. Then set `GEMINI_AFFECTIVE_DIALOG=true` and make 3 calls where you act frustrated or confused. Note in the PR description whether the tone audibly follows the caller and whether latency changed. This decides whether Gemini needs the Phase 2 prompt notes, or only benefits from them.
- [ ] **Step 7: Commit** `feat(agent): per-call latency summary`.

---

## Phase 2: Mood from what the caller says

### Task 4: Mood tracker and tone policy

**Files:**
- Create: `agent/mood.py`, `agent/tone.py`, `agent/tests/test_mood.py`, `agent/tests/test_tone.py`

**Interfaces:**
- Produces (`mood.py`):
  - `Emotion = Literal["neutral", "interested", "confused", "frustrated", "rushed", "suspicious", "angry", "disengaged"]`
  - `@dataclass(frozen=True) class MoodReading: emotion: Emotion; sentiment: float; confidence: float; source: Literal["text", "behavior"]; at_s: float`
  - `class MoodTracker` with:
    - `observe(r: MoodReading) -> Emotion | None`: returns the new mood only when it changes.
    - `current: Emotion` (starts `"neutral"`).
    - `sentiment: float`: an EMA with α=0.5 over text readings only, starting at 0.
    - `timeline: list[dict]`: one `{"at_s", "emotion", "confidence", "source"}` per reading.
    - `summary() -> dict`, with keys `final`, `worst` (the most negative mood seen, ranked angry > frustrated > suspicious > confused > rushed > disengaged > neutral > interested), `avg_sentiment` (rounded to 2 places) and `changes` (int).
  - Switching rule: readings with `confidence < 0.6` are recorded but never cause a switch. The mood switches to X when the last two accepted readings are both X. `angry` with `confidence >= 0.8` switches immediately.
- Produces (`tone.py`):
  - `@dataclass(frozen=True) class ToneDirective: note: str; tts_speed: float; offer_handoff: bool`
  - `TONE_POLICY: dict[Emotion, ToneDirective]` with the values below. `neutral` is `ToneDirective("", 1.0, False)`.
  - `mood_message(emotion: Emotion) -> str`: returns `f"[Caller mood: {emotion}] {note} Never tell the caller you can tell how they feel. This replaces any earlier caller-mood note."`. For neutral it returns `"[Caller mood: neutral] Talk normally. This replaces any earlier caller-mood note."`.

  | Emotion | note | speed | handoff |
  |---|---|---|---|
  | interested | Caller sounds interested. Move toward confirming interest and the telecaller follow-up; don't over-explain. | 1.0 | no |
  | confused | Caller sounds confused. Slow down, use simpler words, one point at a time, and check they understood before moving on. | 0.9 | no |
  | frustrated | Caller sounds frustrated. Acknowledge briefly ("samajh sakti hoon sir"), keep replies to one short sentence, stop pitching, offer a callback or the telecalling team. | 0.92 | yes |
  | rushed | Caller seems short on time. Ask only what is essential, or offer a callback at a time that suits them. | 1.08 | no |
  | suspicious | Caller sounds wary. Be transparent: you are Carrum's AI assistant and never ask for documents or money. Answer their doubt before anything else. | 0.95 | no |
  | angry | Caller sounds angry. Apologise once, don't argue or pitch, offer to end the call or connect them to the team; if they ask not to be called, set do_not_call. | 0.9 | yes |
  | disengaged | Caller seems disengaged. Ask one short direct question to check if this is a good time; if not, offer a callback. | 1.0 | no |

- [ ] **Step 1: Failing tests** (`test_mood.py`; `r(e, c=0.9, t=0)` builds a text reading):
  - `test_single_reading_does_not_switch`: `observe(r("frustrated")) is None`, and `current == "neutral"`.
  - `test_two_agreeing_readings_switch`: the second `observe(r("frustrated"))` returns `"frustrated"`.
  - `test_low_confidence_never_switches`: two `r("confused", c=0.5)` leave `current == "neutral"`, and `len(timeline) == 2`.
  - `test_confident_anger_switches_immediately`: `observe(r("angry", c=0.85)) == "angry"`.
  - `test_curt_refusal_then_neutral_stays_neutral`: frustrated then neutral leaves `current == "neutral"`, with `changes == 0`.
  - `test_summary_worst_and_avg`: readings frustrated (sentiment −0.8), frustrated (−0.6), interested, interested → `final == "interested"`, `worst == "frustrated"`, `changes == 2`.
  - `test_tone.py::test_every_emotion_has_policy`: `set(TONE_POLICY) == set(get_args(Emotion))`. `test_message_has_guardrail`: every non-neutral `mood_message(e)` contains `"Never tell the caller"`.
- [ ] **Step 2: Run** `make test`. Expected: FAIL.
- [ ] **Step 3: Implement** `mood.py` and `tone.py`.
- [ ] **Step 4: Run** `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(agent): mood tracker with hysteresis and tone policy`.

### Task 5: Turn classifier

**Files:**
- Create: `agent/sentiment.py`, `agent/tests/test_sentiment.py`

**Interfaces:**
- Consumes: `MoodReading`, `Emotion` (Task 4).
- Produces:
  - `parse_reading(raw: str, at_s: float) -> MoodReading | None`: accepts JSON, optionally inside ```` ``` ```` fences. Clamps sentiment to [−1, 1] and confidence to [0, 1]. Returns None for an unknown emotion or invalid JSON. Sets source `"text"`.
  - `class TurnClassifier(complete: Callable[[str, str], Awaitable[str]], timeout_s: float = 3.0)`, with `async classify(agent_line: str, caller_text: str, at_s: float) -> MoodReading | None`. It never raises, and it logs one warning per instance on its first failure or timeout.
  - `make_classifier(pipeline: str) -> TurnClassifier | None`. It builds `complete` from a livekit LLM:
    - `gemini-live` → `google.LLM(model=os.getenv("SENTIMENT_MODEL", "gemini-flash-lite-latest"))`
    - otherwise → `openai.LLM(model=os.getenv("SENTIMENT_MODEL", "gpt-4.1-mini"))`
    - It returns None (with a warning) when the needed API key is missing. `complete` streams `llm.chat(chat_ctx=…)` and joins the text deltas.
  - `CLASSIFIER_PROMPT`: a system prompt that says the input is one Hindi/Hinglish/regional phone reply from a driver to Carrum's AI caller, plus the agent's previous line for context. It asks for only `{"emotion": <one of the 8 labels>, "sentiment": -1..1, "confidence": 0..1}`, defines each label in one line (from the tone table), and says that a plain "no"/"nahi" is `neutral` unless the wording shows irritation.

- [ ] **Step 1: Failing tests:**
  - `test_parse_plain_json`: `parse_reading('{"emotion":"confused","sentiment":-0.2,"confidence":0.7}', 3.0)` → `MoodReading("confused", -0.2, 0.7, "text", 3.0)`.
  - `test_parse_fenced_and_clamped`: fenced JSON with sentiment 4 and confidence −1 gives 1.0 and 0.0.
  - `test_parse_rejects_unknown_label_and_junk`: `"happy"` → None; `"sorry I can't"` → None.
  - `test_classify_timeout_returns_none`: a fake `complete` that sleeps 5 s, with `timeout_s=0.05`, gives None.
  - `test_classify_error_logged_once`: a fake that raises; two calls → both None, and `caplog` holds exactly one warning.
  - `test_classify_passes_context`: a fake records its args; the user message contains both the agent line and the caller text.
- [ ] **Step 2: Run** `make test`. Expected: FAIL.
- [ ] **Step 3: Implement** `sentiment.py`.
- [ ] **Step 4: Run** `make test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(agent): LLM turn mood classifier`.

### Task 6: Adapt tone during the call

**Files:**
- Modify: `agent/agent.py`, `.env.example`, `README.md`

**Interfaces:**
- Consumes: `make_classifier`, `TurnClassifier.classify` (Task 5); `MoodTracker`, `TONE_POLICY`, `mood_message` (Task 4).
- Produces: `async def apply_mood(session: AgentSession, agent: PhoneAgent, emotion: Emotion) -> None` in `agent.py`. The `call ended` log gains `"mood": tracker.summary()`. Env vars: `MOOD_ENABLED=false`, `SENTIMENT_MODEL=` (empty = pipeline default), `MOOD_EVAL_CAPTURE=false`.

- [ ] **Step 1: Classify each caller turn.** In the existing `conversation_item_added` handler, for user items (when `MOOD_ENABLED` and a classifier exists), `asyncio.create_task(classify(last_agent_line, text, t))`. On a result, `tracker.observe(reading)`. If the mood changed, call `apply_mood` and `logger.info("mood changed", extra={"mood": emotion})`. Track `last_agent_line` from assistant items. Keep tasks in a set and cancel them in `_on_close`.
- [ ] **Step 2: `apply_mood`.**
  - Copy `agent.chat_ctx`, `add_message(role="system", content=mood_message(emotion))`, then `await agent.update_chat_ctx(ctx)`.
  - On cascaded pipelines, also set the TTS speed from `TONE_POLICY[emotion].tts_speed`:
    - Sarvam: `tts.update_options(pace=speed)`.
    - ElevenLabs: `tts.update_options(voice_settings=VoiceSettings(..., speed=speed))`, keeping the other settings.
  - First confirm the parameter names: `agent/.venv/bin/python -c "import inspect, livekit.plugins.sarvam as s, livekit.plugins.elevenlabs as e; print(inspect.signature(s.TTS.update_options)); print(e.VoiceSettings.__dataclass_fields__.keys())"`. If a parameter doesn't exist, skip speed for that TTS and log once.
- [ ] **Step 3: Verify on Gemini.** Make a test call with `MOOD_ENABLED=true` on `gemini-live` and sound clearly irritated for 2 turns. Expected: `mood changed: frustrated` in the logs, and the next replies are shorter and stop pitching. If Gemini ignores the system note in the chat context, switch `apply_mood` for `gemini-live` to `await agent.update_instructions(base_instructions + "\n\n" + mood_message(emotion))`, keeping the base text on the agent. Repeat the call and record which method worked in a code comment.
- [ ] **Step 4: Verify on cascaded.** Same call on `sarvam`. Expected: the mood changes and the agent audibly speaks slower after frustration.
- [ ] **Step 5: Docs.** Add the env vars to `.env.example` and a README bullet "Caller mood: …" saying it's off by default until the Phase 4 eval.
- [ ] **Step 6: Commit** `feat(agent): adapt tone and pace to caller mood`.

---

## Phase 3: Behaviour signals and handoff

### Task 7: Behaviour features

**Files:**
- Create: `agent/behavior.py`, `agent/tests/test_behavior.py`
- Modify: `agent/agent.py`

**Interfaces:**
- Consumes: `MoodReading` (Task 4), and `MoodTracker.observe` for wiring.
- Produces: `class BehaviorTracker` with:
  - `agent_turn_ended(now: float, interrupted: bool) -> None`
  - `user_turn(now: float, text: str, reply_latency_s: float) -> None`
  - `poll(now: float) -> MoodReading | None`. Each call emits at most one reading, and never the same emotion twice in a row. Readings have source `"behavior"`, sentiment 0 and confidence 0.7. The rules:
    - `rushed` when 2 or more of the last 3 agent turns were interrupted.
    - `disengaged` when each of the last 3 user turns has 2 words or fewer AND the median reply latency is 2.5 s or more.
  - `features() -> dict` with keys `interruptions`, `agent_turns`, `median_reply_latency_s` and `median_reply_words`.

- [ ] **Step 1: Failing tests.**
  - `test_rushed_after_two_interruptions_in_three`: turns interrupted T, F, T → `poll().emotion == "rushed"`. A second `poll()` returns None.
  - `test_disengaged_needs_short_and_slow`: three replies "haan", "ok", "ji" at latencies 3, 3, 3 → `"disengaged"`. The same words at latency 0.5 → None.
  - `test_features`: values after a known sequence.
- [ ] **Step 2: Run** `make test`. Expected: FAIL.
- [ ] **Step 3: Implement** `behavior.py`.
- [ ] **Step 4: Run** `make test`. Expected: PASS.
- [ ] **Step 5: Wire** (only when `MOOD_ENABLED`):
  - `session.on("speech_created")`: add a done callback on `ev.speech_handle` → `agent_turn_ended(t, handle.interrupted)`.
  - Reply latency = the time from the agent's last `"listening"` state to the caller's next `"speaking"` user state, or to the user transcript if no state arrives.
  - After each user turn, `poll()` and pass any reading to `tracker.observe` (same `apply_mood` path).
  - Add `"behavior": features()` to the `call ended` log.
- [ ] **Step 6: Verify** with a test call where you interrupt the agent twice. Expected: a `behavior` reading in the logs, and the mood becomes `rushed` once a text reading agrees, or after two behaviour polls.
- [ ] **Step 7: Commit** `feat(agent): interruption and engagement signals feed caller mood`.

### Task 8: Live handoff to a telecaller

**Files:**
- Modify: `agent/agent.py` (`PhoneAgent`, `entrypoint`), `agent/tone.py` (notes for `offer_handoff`), `agent/tests/test_tone.py`, `.env.example`, `README.md`

**Interfaces:**
- Consumes: `ToneDirective.offer_handoff` (Task 4).
- Produces:
  - `@function_tool async def transfer_to_telecaller(self, ctx: RunContext) -> str` on `PhoneAgent`.
  - `PhoneAgent.caller_identity: str | None`, set in `entrypoint` from `caller.identity`.
  - Env var `HANDOFF_SIP_URI` (e.g. `tel:+91…` or `sip:…`). Empty means off.

- [ ] **Step 1: Failing test.** `test_handoff_note_only_when_enabled`: `mood_message("angry", handoff_available=True)` contains `"transfer_to_telecaller"`, and with `False` it doesn't. Change `mood_message`'s signature to `mood_message(emotion: Emotion, handoff_available: bool = False) -> str`. When the directive has `offer_handoff` and handoff is available, append: "If they agree to speak to a person now, call record_outcome, then transfer_to_telecaller."
- [ ] **Step 2: Run** `make test`. Expected: FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5: Tool.**
  - If `HANDOFF_SIP_URI` is empty → return "Live transfer isn't available. Offer a callback from the telecalling team instead."
  - If `self.outcome is None` → return "Call record_outcome first."
  - Otherwise say a one-line handover (via the returned instruction), `await ctx.wait_for_playout()`, then `await get_job_context().api.sip.transfer_sip_participant(api.TransferSIPParticipantRequest(room_name=…, participant_identity=self.caller_identity, transfer_to=HANDOFF_SIP_URI, play_dialtone=True))`. On error, log it and return "Transfer failed; apologise and offer a callback."
  - Pass `handoff_available=bool(HANDOFF_SIP_URI)` in `apply_mood`.
- [ ] **Step 6: Verify** on the SIP trunk, with `HANDOFF_SIP_URI` set to your own mobile. Act angry and agree to talk to a person. Expected: the caller's phone gets transferred and your mobile rings. If the trunk rejects REFER, note it in the README and leave the env var empty.
- [ ] **Step 7: Commit** `feat(agent): optional live transfer to telecaller for upset callers`.

---

## Phase 4: Reporting and evaluation

### Task 9: Per-call report from the agent

**Files:**
- Create: `agent/report.py`, `agent/tests/test_report.py`
- Modify: `agent/agent.py` (`_on_close`), `.env.example`

**Interfaces:**
- Consumes: `MoodTracker.summary()` and `.timeline`, `DeadAirWatcher.events`, `LatencyStats.summary()`, `BehaviorTracker.features()`.
- Produces:
  - `build_report(room: str, outcome: dict, mood: dict, timeline: list[dict], dead_air: list[dict], latency: dict, behavior: dict, turns: list[dict] | None) -> dict`. It returns `{"room", "disposition", "outcome", "mood", "timeline", "dead_air", "latency", "behavior", "turns"}`, and `"turns"` is only present when the argument is not None. Each turn is `{"role": "user" | "assistant", "text": str, "at_s": float}`. `timeline` and `at_s` are seconds since the call started.
  - `async send_report(url: str, report: dict, api_key: str, api_secret: str) -> bool`. It POSTs JSON with `Authorization: Bearer <jwt>`, where the JWT comes from `api.AccessToken(api_key, api_secret).with_identity("agent-report").with_ttl(timedelta(seconds=60)).to_jwt()`. It has a 5 s timeout and returns False on any failure, without raising.
  - Env var `DASHBOARD_REPORT_URL` (default empty; on the media VM, `http://127.0.0.1:8787/api/report`).

- [ ] **Step 1: Failing tests.** `test_build_report_omits_turns_by_default`. `test_build_report_disposition_from_outcome`. `test_send_report_false_on_connection_error`: url `http://127.0.0.1:9/x` → False.
- [ ] **Step 2: Run** `make test`. Expected: FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5: Wire.** In `_on_close`, build the report. Pass `turns=[{"role", "text", "at_s"}]` only when `MOOD_EVAL_CAPTURE=true`. Then `asyncio.create_task(send_report(...))` when the URL is set.
- [ ] **Step 6: Commit** `feat(agent): send per-call mood report to dashboard`.

### Task 10: Port the dashboard to Django (feature parity)

The dashboard does the same things as today, rebuilt as Django. It adds no mood features yet.

**Files:**
- Delete: `dashboard/app.py`. `dashboard/static/index.html` moves to `dashboard/calls/templates/calls/index.html`.
- Create:
  - `dashboard/manage.py`
  - `dashboard/config/{__init__,settings,urls,asgi}.py`
  - `dashboard/calls/{__init__,apps,models,views,urls,admin,livekit_state}.py`
  - `dashboard/calls/migrations/0001_initial.py` (from `makemigrations`)
  - `dashboard/calls/management/commands/import_legacy_calls.py`
  - `dashboard/requirements-dev.txt`, `dashboard/pytest.ini`
  - `dashboard/tests/{__init__,conftest,test_webhook,test_state,test_import_legacy}.py`
- Modify: `dashboard/requirements.txt`, `dashboard/Dockerfile`, `Makefile`, `scripts/init.sh`, `.env.example`, `README.md` ("Calls dashboard")

**Interfaces:**
- Produces:
  - `calls.models.Call`. Fields:
    - `room` (CharField, unique)
    - `started_at`, `answered_at`, `ended_at`, `agent_joined_at` (DateTimeField, null)
    - `caller`, `called`, `sip_call_id`, `end_reason` (CharField, blank)

    Meta ordering is `-started_at`.
  - `Call.record_first(room: str, **fields) -> Call` (classmethod). It creates the row if missing and sets each given non-None field only if it's still empty. This keeps today's "first value wins" behaviour.
  - `Call.mark_ended(room: str, ended_at: datetime, reason: str) -> Call` (classmethod). It always overwrites.
  - `Call.as_dict() -> dict`, with the same keys as today's `calls` row. Datetimes become epoch-second ints, or None.
  - `async calls.livekit_state.fetch_livekit_state() -> dict`, returning `{"server": {"ok", "error"}, "live", "trunks", "rules"}`. The logic is lifted from today's `state()`, including the empty lists and `ok=False` on any exception.
  - Views:
    - `index` (login required) renders the moved page.
    - `async state` (login required) returns the same JSON keys as today: `now, server, live, trunks, rules, recent, today`.
    - `webhook` (CSRF-exempt) verifies with `api.WebhookReceiver(api.TokenVerifier(key, secret)).receive(request.body.decode(), request.headers.get("Authorization", ""))` and returns 401 on failure. The event handling is the same as today's `webhook()`.
  - Settings, read from env:
    - `DJANGO_SECRET_KEY` (required)
    - `ALLOWED_HOSTS = ["127.0.0.1", "localhost"]`
    - `DEBUG` false unless `DJANGO_DEBUG=true`
    - SQLite at `DASHBOARD_DB_DIR/dashboard.sqlite3` (default `/data`)
    - `LOGIN_URL = "/admin/login/"`
    - whitenoise middleware, `STATIC_ROOT=/app/staticfiles`
    - `TIME_ZONE = "Asia/Kolkata"`, `USE_TZ = True`
  - Management command `import_legacy_calls --path /data/calls.db`. It copies every row of the old `calls` table into `Call`, converting epoch ints to aware datetimes, and uses `update_or_create` on `room`, so running it again is a no-op.
  - Make targets:
    - `dashboard-admin`: `docker compose exec dashboard python manage.py createsuperuser`
    - `test` gains `cd dashboard && .venv/bin/pytest -q`

- [ ] **Step 1: Scaffold.**
  - `django-admin startproject config dashboard` and `manage.py startapp calls`. Pin `requirements.txt` per Global Constraints.
  - `requirements-dev.txt`: `-r requirements.txt` + `pytest==8.3.3` + `pytest-asyncio==0.24.0` + `pytest-django` (pinned).
  - `pytest.ini`: `DJANGO_SETTINGS_MODULE = config.settings`, `testpaths = tests`, `asyncio_mode = auto`.
  - `conftest.py` sets `DJANGO_SECRET_KEY`, `LIVEKIT_API_KEY`/`SECRET` and a temporary `DASHBOARD_DB_DIR` before Django loads.
  - Create `dashboard/.venv` the same way as the agent's.
- [ ] **Step 2: Failing tests.**
  - `test_webhook.py`: monkeypatch `calls.views.receiver.receive` to return built `livekit.api.WebhookEvent` protos.
    - `test_bad_signature_401`: the real receiver with a junk header → 401.
    - `test_sip_join_records_caller_first_wins`: two `participant_joined` SIP events with different `sip.phoneNumber` values → `Call.caller` keeps the first.
    - `test_agent_join_sets_agent_joined_at`.
    - `test_room_finished_sets_end_reason`: `ROOM_END_...` → `end_reason == "..."` (lowercased, prefix removed).
  - `test_state.py`:
    - `test_state_requires_login`: anonymous → 302 to `/admin/login/`.
    - `test_state_shape_when_livekit_down`: logged in, `fetch_livekit_state` patched to raise inside → 200, `server.ok is False`, `live == []`, `recent` lists seeded calls newest first, `today.total` counts calls started since local midnight.
    - `test_index_renders`: logged in → 200, containing `api/state`.
  - `test_import_legacy.py`: build a temp `calls.db` with today's schema and two rows. `test_import_copies_rows` checks 2 `Call`s with matching caller and epoch→datetime. `test_import_idempotent` runs the import twice and still finds 2.
- [ ] **Step 3: Run** `make test`. Expected: dashboard tests FAIL (no views/models).
- [ ] **Step 4: Implement** the models, migration, views, `livekit_state.py`, URLs and the command.
  - In the template, use relative `fetch("api/state")` as today and add a logout link (`/admin/logout/`, POST form with CSRF token).
  - `admin.py` registers `Call` with `list_display = (room, caller, started_at, ended_at, end_reason)`, `search_fields = (caller, room)` and `date_hierarchy = started_at`.
  - `today` uses local midnight in `Asia/Kolkata`. Today's code uses UTC midnight, which is a bug for an India-only service; mention the change in the commit message.
- [ ] **Step 5: Run** `make test`. Expected: all agent and dashboard tests PASS.
- [ ] **Step 6: Container and config.**
  - Dockerfile: copy the whole `dashboard/` folder, run `python manage.py collectstatic --noinput` at build time, and use `CMD sh -c "python manage.py migrate --noinput && uvicorn config.asgi:application --host ${DASHBOARD_HOST:-127.0.0.1} --port ${DASHBOARD_PORT:-8787}"`.
  - `scripts/init.sh` generates `DJANGO_SECRET_KEY` the same way it generates the LiveKit secret.
  - `.env.example` gains `DJANGO_SECRET_KEY=` and `DJANGO_DEBUG=false`.
  - README: after the first deploy, run `make dashboard-admin` once, then `docker compose exec dashboard python manage.py import_legacy_calls --path /data/calls.db`.
- [ ] **Step 7: Verify on the VM.**
  - `make deploy`, then on the VM run the two README commands.
  - `make tunnel` → `http://localhost:8787` redirects to login; after login, the old call history, live calls, trunks and dispatch rules show as before.
  - Place a test call and confirm it appears live, then in history with its end reason.
  - `/admin/` lists the calls.
- [ ] **Step 8: Commit** `refactor(dashboard): port to Django with login and admin`.

### Task 11: Mood reports in the Django dashboard

**Files:**
- Modify: `dashboard/calls/{models,views,urls,admin}.py`, `dashboard/calls/templates/calls/index.html`
- Create: `dashboard/calls/migrations/0002_callreport.py`, `dashboard/tests/test_report.py`

**Interfaces:**
- Consumes: the JSON report and Bearer JWT from Task 9; `Call.record_first`, `Call.as_dict` (Task 10).
- Produces:
  - `calls.models.CallReport`. Fields:
    - `call` (OneToOneField → `Call`, `related_name="report"`, on_delete CASCADE)
    - `disposition`, `final_mood`, `worst_mood` (CharField, blank)
    - `avg_sentiment` (FloatField, null)
    - `dead_air_nudges` (PositiveIntegerField, default 0)
    - `llm_ttft_p50_ms` (PositiveIntegerField, null)
    - `data` (JSONField: the full report)
    - `received_at` (auto_now)
  - `CallReport.store(report: dict) -> CallReport` (classmethod). It calls `Call.record_first(report["room"])` (so the report may arrive before the webhook) and uses `update_or_create` on `call`, so a later report replaces an earlier one. It derives:
    - `final_mood`/`worst_mood`/`avg_sentiment` from `report["mood"]`
    - `dead_air_nudges` = the count of `dead_air` events whose action is not `hang_up`
    - `llm_ttft_p50_ms` = `report["latency"].get("llm_ttft", {}).get("p50_ms")`
  - Views:
    - `report_ingest`: `POST /api/report`, CSRF-exempt. It verifies `api.TokenVerifier(key, secret).verify(bearer)` and requires identity `agent-report`, else 401. Invalid JSON or a missing `room` → 400. Otherwise 200.
    - `report_detail`: `GET /api/report/<room>`, login required. Returns `report.data`, or 404.
  - `Call.as_dict()` gains `disposition`, `final_mood`, `worst_mood`, `avg_sentiment`, `dead_air_nudges` and `llm_ttft_p50_ms` (None without a report). `state` uses `select_related("report")`.
  - Admin: `CallAdmin` adds `disposition`/`final_mood` to `list_display` and `list_filter = ("report__final_mood", "report__disposition")`, plus a read-only `CallReport` inline showing `data` as indented JSON.

- [ ] **Step 1: Failing tests** in `test_report.py`. Make tokens with `api.AccessToken(key, secret).with_identity("agent-report").to_jwt()`.
  - `test_report_rejects_bad_token`: a junk bearer → 401. A token with identity `someone-else` → 401.
  - `test_report_rejects_missing_room`: 400.
  - `test_report_before_webhook_creates_call`: POST for `call-x` → 200; `Call.objects.get(room="call-x").report.final_mood` matches; a logged-in `GET /api/report/call-x` returns the same JSON.
  - `test_report_replaces_previous`: a second POST with `final_mood: angry` → one `CallReport`, angry.
  - `test_dead_air_nudges_excludes_hang_up`: events nudge, second_nudge, hang_up → 2.
  - `test_state_rows_include_mood`: a seeded report shows up in `state` → `recent[0]["final_mood"]`.
- [ ] **Step 2: Run** `make test`. Expected: FAIL.
- [ ] **Step 3: Implement** the model, migration, views, URLs and admin changes.
- [ ] **Step 4: Run** `make test`. Expected: PASS.
- [ ] **Step 5: Page.**
  - In `index.html`, add "Outcome", "Mood" (a final-mood badge with the worst mood in a tooltip) and "Dead air" columns. Colours: angry/frustrated red, confused/suspicious amber, rushed/disengaged grey, interested green, neutral none. Rows without a report show "–".
  - Clicking a row fetches `api/report/<room>` and shows a strip of mood readings over the call (one coloured dot per timeline entry at `at_s`), plus latency p50s and dead-air events.
- [ ] **Step 6: Verify.** Set `DASHBOARD_REPORT_URL=http://127.0.0.1:8787/api/report` and `MOOD_ENABLED=true` on the VM, then make 2 test calls (one calm, one irritated). Expected: both rows show outcome and mood, the irritated one is red, clicking shows the strip, and the admin's mood filter finds it.
- [ ] **Step 7: Commit** `feat(dashboard): per-call mood reports, mood column and timeline`.

### Task 12: Label caller turns in the admin and score accuracy

**Files:**
- Create:
  - `dashboard/calls/evaluation.py`
  - `dashboard/calls/management/commands/{mood_eval,purge_turns}.py`
  - `dashboard/calls/migrations/0003_turnlabel.py`
  - `dashboard/tests/test_evaluation.py`
- Modify: `dashboard/calls/{models,admin}.py`, `CallReport.store` (in `models.py`), `README.md` (new section "Evaluating caller mood")

**Interfaces:**
- Consumes: `report["turns"]` and `report["timeline"]` (Task 9, captured with `MOOD_EVAL_CAPTURE=true`); `CallReport.store` (Task 11).
- Produces:
  - `calls.models.TurnLabel`. Fields:
    - `report` (FK → `CallReport`, `related_name="turns"`, CASCADE)
    - `at_s` (FloatField)
    - `caller_text` (TextField)
    - `predicted` (CharField)
    - `label` (CharField, blank, `choices` = the 8 emotions from Task 4 plus `"unclear"`)

    `unique_together = (report, at_s)`.
  - `calls.evaluation.align_predictions(turns: list[dict], timeline: list[dict]) -> list[dict]`. For each user turn, it returns `{"at_s", "caller_text", "predicted"}`, where `predicted` is the first text-source timeline entry with `at_s` greater than or equal to the turn's, before the next user turn. It falls back to `"neutral"`.
  - `calls.evaluation.score(pairs: list[tuple[str, str]]) -> dict`, taking pairs of (label, predicted) and skipping `unclear`. It returns `{"accuracy": float, "per_emotion": {e: {"precision", "recall", "support"}}, "confusion": {label: {predicted: n}}}`.
  - `CallReport.store` creates or refreshes the `TurnLabel` rows from `align_predictions` when `turns` is present, and keeps existing labels on re-store.
  - Admin: `TurnLabelAdmin` with `list_display = (caller_text, predicted, label)`, `list_editable = ("label",)`, `list_filter = (predicted, label)` and `list_per_page = 50`. Telecallers label straight in the list.
  - `manage.py mood_eval [--since YYYY-MM-DD]` prints the accuracy, a per-emotion table, the confusion matrix and a PASS/FAIL line for the go-live gate. `manage.py purge_turns` deletes all `TurnLabel` rows and strips `turns` from `CallReport.data`.

- [ ] **Step 1: Failing tests** in `test_evaluation.py`:
  - `test_align_picks_first_reading_after_turn`
  - `test_align_falls_back_to_neutral`
  - `test_score_precision_recall`: a 6-pair fixture with known counts, e.g. labels (angry, angry, neutral, confused, confused, neutral) vs predicted (angry, neutral, neutral, confused, angry, neutral) → angry precision 0.5, recall 0.5; confused precision 1.0, recall 0.5; accuracy 4/6.
  - `test_score_skips_unclear`
  - `test_store_creates_turn_labels_and_keeps_labels`: store with 2 user turns → 2 rows; set one label; store again → that label is kept.
  - `test_purge_turns`: afterwards there are no `TurnLabel` rows, and the report `data` has no `turns`.
- [ ] **Step 2: Run** `make test`. Expected: FAIL.
- [ ] **Step 3: Implement** the model, migration, `evaluation.py`, the `store` change, the admin and both commands.
- [ ] **Step 4: Run** `make test`. Expected: PASS.
- [ ] **Step 5: README procedure.**
  1. Set `MOOD_ENABLED=true MOOD_EVAL_CAPTURE=true` for one week of real calls.
  2. Create telecaller accounts with **staff** access limited to `TurnLabel` permissions.
  3. Label 300 or more turns in `/admin/calls/turnlabel/`.
  4. `docker compose exec dashboard python manage.py mood_eval`.
  - **Go-live gate:** precision ≥ 0.7 for `angry`, `frustrated` and `confused`. Below that, tighten `CLASSIFIER_PROMPT` and re-score, or keep `MOOD_ENABLED=false`.
  - Afterwards, set `MOOD_EVAL_CAPTURE=false` and run `purge_turns`, because the turns hold caller speech.
  - Also compare the CDRP and NI rates for calls with mood on vs off, using the admin filters.
- [ ] **Step 6: Commit** `feat(dashboard): label caller turns in admin and score mood accuracy`.

---

## Open decisions for the team (not blocking Phase 1)

- **Disclosure:** should the opening line mention that the call is analysed to improve service? (DPDP Act.)
- **Dashboard logins:** who gets accounts (ops, telecallers for labelling), and whether everyone uses one shared login or personal ones.
- **Live handoff (Task 8):** do telecallers accept live transfers, and does the SIP trunk support REFER?
- **Speech-emotion model on raw audio:** revisit after the Task 12 results, if text and behaviour signals miss too much.
