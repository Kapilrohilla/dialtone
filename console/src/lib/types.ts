// Shapes of the Django API, copied from the serializers and views they come from.

export type Role = "owner" | "admin" | "editor" | "viewer";
export type Appearance = "light" | "dark" | "system";

// server/workspaces/serializers.py
export type Preferences = {
  appearance: Appearance;
  notify_needs_person: boolean;
  notify_daily_summary: boolean;
  time_zone: string;
};

/** The account. GET/PATCH /api/workspace; also inside GET /api/me. */
export type Workspace = {
  id: number;
  name: string;
  slug: string;
  /** Off: no agent or workflow checks in on silent callers. Reaches the next call, no publishing needed. */
  dead_air_enabled: boolean;
  /** Records real phone calls (never browser tests). The server's RECORDING_ENABLED can still turn it off. */
  recording_enabled: boolean;
  /** Call audits: Gemini scores the AI side of finished calls. Off by default. */
  audit_enabled: boolean;
  /** Share of calls audited automatically: 100, 50, 25 or 10. */
  audit_sample_pct: number;
  /** Weight (0–100) of each rubric area in the overall score. */
  audit_weights: Record<AuditAreaKey, number>;
  /** Extra notes for the rubric. */
  audit_instructions: string;
  /** Audit fixes that pass checks, are confident and show in 3+ calls are applied to the draft on their own. */
  audit_fix_auto_apply: boolean;
};

export type Me = {
  id: number;
  name: string;
  email: string;
  phone: string;
  role: Role;
  /** Django superuser: may rename the install (Settings → General). */
  is_superuser: boolean;
  workspace: Workspace;
  preferences: Preferences;
};

/** The console palette for everyone on the install. Light / dark stays each user's own `Appearance`. */
export type Theme = "saffron" | "ocean" | "forest";

/** This install. GET /api/instance/ (public); PATCH by a superuser. The logo has its own endpoint
 *  (POST / DELETE /api/instance/logo); `logo_url` is null when there is none. */
export type Instance = {
  project_name: string;
  theme: Theme;
  logo_url: string | null;
};

export type InstanceUpdate = Partial<Pick<Instance, "project_name" | "theme">>;

export type TeamMember = {
  id: number;
  name: string;
  email: string;
  role: Role;
  last_login: string | null;
};

// server/knowledge/serializers.py
export type KnowledgeListItem = {
  id: number;
  title: string;
  updated_at: string;
  current_revision: number;
  used_by: number;
};

export type KnowledgeDoc = KnowledgeListItem & { body_md: string };

export type Revision = {
  number: number;
  edited_by: string | null;
  created_at: string;
  /** Present on GET /api/knowledge/:id/revisions/:n only. */
  body_md?: string;
};

// server/workflows (api.py detail + graph.py)
export type StepType = "start" | "prompt" | "collect" | "knowledge" | "transfer" | "end";

export type Step = {
  id: string;
  name: string;
  type: StepType;
  prompt?: string;
  field?: string;
  knowledge_id?: number;
  outcome?: string;
  position?: { x: number; y: number };
};

export type Path = {
  id?: string;
  from: string;
  to: string;
  label: string;
  /** Things a caller might say for this path (up to 5, 40 characters each); they help the agent pick it. */
  examples?: string[];
};
export type Graph = { steps: Step[]; paths: Path[] };

export type WorkflowListItem = {
  id: number;
  name: string;
  updated_at: string;
  current_revision: number;
  /** Off: agents using this workflow don't check in on silent callers (after they are published). */
  dead_air_enabled: boolean;
};

export type Workflow = WorkflowListItem & {
  graph: Graph;
  /** Validation errors for the saved graph, plain words. */
  errors: string[];
};

// server/voiceagents/serializers.py
export type AgentStatus = "draft" | "published" | "archived";

export type AgentSettings = {
  mood_adaptation: boolean;
  dead_air: { enabled: boolean; nudge_s: number; second_nudge_s: number; hang_up_s: number };
  /** The company the agent says it calls from. Blank or missing: unset. */
  company_name?: string;
  /** How the agent's name is spoken, e.g. "Maa-yaa". Blank or missing: unset. */
  name_pronunciation?: string;
  /** Read out at the start of the call, e.g. a recording notice. Blank or missing: unset. */
  consent_line?: string;
};

/** The optional free-text agent settings (blank = unset). */
export type AgentTextSetting = "company_name" | "name_pronunciation" | "consent_line";

export type ScriptSection = { id: string; title: string; body: string };

export type AgentListItem = {
  id: number;
  name: string;
  description: string;
  status: AgentStatus;
  phone_number: string;
  updated_at: string;
  updated_by_name: string | null;
  is_outdated: boolean;
  /** Workflow id, or null. */
  workflow: number | null;
  calls_this_week: number;
};

export type Agent = Omit<AgentListItem, "calls_this_week"> & {
  language: string;
  persona_name: string;
  voice_id: string;
  settings: AgentSettings;
  script: ScriptSection[];
  custom_expressions: Record<string, string>;
  /** Knowledge document ids. */
  knowledge: number[];
  published_version: number | null;
  created_at: string;
};

/** Average audit scores of a version's calls: overall 0–100, areas 1–5; null when nothing was scored. */
export type AuditScores = { calls: number; overall: number | null; areas: Record<AuditAreaKey, number | null> };

/** GET /api/agents/:id/versions, newest first (server/audits/impact.py versions_payload). */
export type AgentVersion = {
  number: number;
  published_by_name: string | null;
  published_at: string;
  /** Accepted audit fixes first published in this version. */
  audit_fixes: { id: number; target: AuditFixTarget; kind: AuditFixKind; title: string; area: string; auto_applied: boolean }[];
  audit_scores: AuditScores;
  /** The version before this one; null for the first. `change` is set only when both have `min_calls` audited calls. */
  compared_to: null | {
    version: number;
    enough: boolean;
    scores: AuditScores;
    change: null | { overall: number | null; areas: Record<AuditAreaKey, number | null> };
  };
  min_calls: number;
};

// GET /api/expressions
export type Expression = { name: string; hint: string; builtin: boolean };

// GET /api/voices
export type Voice = { id: string; name: string; description: string; sample: string | null };
export type VoicesResponse = { pipeline: string; voices: Voice[] };

// server/calls/serializers.py and api.py
export type OutcomeGroup = "Interested" | "Call back" | "Not interested" | "Dropped" | "Not reached";

export type CallRow = {
  room: string;
  started_at: string | null;
  caller: string;
  agent_name: string | null;
  /** Display group, "" when the call has no report yet. */
  outcome: OutcomeGroup | "";
  outcome_code: string;
  mood: string;
  duration_s: number | null;
  summary: string;
  /** A finished recording can be played. */
  has_recording: boolean;
  /** Missing from older servers; then has_recording decides. */
  recording_status?: RecordingStatus;
  /** The current audit's overall score (0–100); null when the call isn't scored. Missing from older servers. */
  audit_score?: number | null;
};

/** "processing" covers starting and still recording. */
export type RecordingStatus = "none" | "processing" | "complete" | "failed" | "purged";

export type TranscriptTurn = { speaker: string; text: string; expressions: string[]; at: string };

export type CallDetail = CallRow & {
  reason: string;
  answers: Record<string, unknown>;
  step_path: string[];
  transcript: TranscriptTurn[];
  /** Set only when the recording is complete and its file exists. */
  recording_url: string | null;
  recording_status: RecordingStatus;
  recording_duration_s: number | null;
  /** When the recording began: transcript times minus this are offsets into the audio. */
  recording_started_at: string | null;
  /** Caller stops speaking -> agent reply heard (agent/response_gap.py); null for calls before it was measured. */
  response_gap: ResponseGap | null;
};

export type GapStats = { avg_ms?: number; p50_ms?: number; p95_ms?: number; max_ms?: number };

/** `system`: until the agent's audio starts. `perceived`: until it is audible (adds silence at the start of
 * the line, such as a pause cue). Replies the caller didn't wait for (the agent cut in) aren't measured. */
export type ResponseGap = {
  n: number;
  system: GapStats;
  perceived: GapStats;
  slow_replies: number;
  slow_threshold_ms: number;
  agent_cut_ins: number;
  replies: { at_s: number; system_ms: number; perceived_ms: number }[];
};

// dashboard/calls/feedback.py: a person's own rating of a call (usually after a voice test).
export type CallFeedback = {
  id: number;
  author: string | null;
  mine: boolean;
  ratings: Partial<Record<AuditAreaKey, number>>;
  overall: number | null;
  remarks: string;
  updated_at: string;
};

export type CallFeedbackInput = {
  ratings: Partial<Record<AuditAreaKey, number>>;
  overall: number | null;
  remarks: string;
};

// dashboard/audits/api.py
export type AuditAreaKey = "naturalness" | "listening" | "empathy" | "pacing" | "flow" | "accuracy";

/** One quoted line (or call signal) behind a score. `at` is the transcript line's time; null for signals. */
export type AuditEvidence = {
  line: number | null;
  at: string | null;
  at_s: number | null;
  step_id: string;
  step_name: string;
  speaker: string;
  /** Blank after 90 days (quotes_purged). */
  quote: string;
  /** Set when the evidence is a call signal rather than words: dead_air, interruption, latency, mood, call_end. */
  event: string;
  kind: "good" | "problem";
  note: string;
};

export type AuditArea = {
  key: AuditAreaKey;
  label: string;
  weight: number;
  /** 1–5; null when the model gave no evidence for it. */
  score: number | null;
  summary: string;
  evidence: AuditEvidence[];
};

export type AuditMoment = Omit<AuditEvidence, "event"> & { area: AuditAreaKey | "" };

export type CallAudit =
  | { status: "none"; enabled: boolean }
  | {
      id: number;
      status: "queued" | "running" | "ready" | "skipped" | "error";
      enabled: boolean;
      error: string;
      skipped_reason: string;
      skipped_label: string;
      overall_score: number | null;
      summary: string;
      areas: AuditArea[];
      moments: AuditMoment[];
      rubric_version: string;
      model: string;
      used_audio: boolean;
      quotes_purged: boolean;
      automatic: boolean;
      created_at: string;
      finished_at: string | null;
    };

export type CallPage = { results: CallRow[]; count: number; page: number; pages: number };

export type LiveCall = {
  room: string;
  caller: string;
  city: string;
  started_at: string | null;
  step_path: string[];
  captured: Record<string, string>;
  current_step: string;
  mood: string;
  transcript_tail: TranscriptTurn[];
};

export type Dashboard = {
  calls_today: number;
  connected_pct: number | null;
  interested: number;
  avg_duration_s: number | null;
  needs_person: { room: string; caller: string; reason: string; at: string | null }[];
  outcomes_week: { outcome: OutcomeGroup; count: number }[];
  live_agent: { id: number; name: string; phone_number: string } | null;
};

export type PhoneNumber = { number: string; trunk_name: string; agent_name: string | null };

// agent/simulate.py Simulation.response
/** A browser voice test of an agent's draft: where to connect and a LiveKit token for a fresh room. */
export type WebCallResponse = { url: string; token: string; room: string };

export type SimResponse = {
  reply: string;
  state: Record<string, unknown>;
  step: { id: string; name: string } | null;
  outcome: Record<string, unknown> | null;
  ended: boolean;
};

// server/workflows (suggestions_api.py): "Suggest with AI" drafts
export type SuggestKind = "answers" | "expressions";
export type SuggestScope = "step" | "workflow";

/** A new step an answer leads to: one that says something and moves on, or one that ends the call. */
export type SuggestedNewStep =
  | { name: string; type: "prompt"; prompt: string; then: { step_id: string; label: string } }
  | { name: string; type: "end"; prompt: string; outcome: string };

export type AnswerPayload = {
  label: string;
  examples: string[];
  reason: string;
  target: { step_id: string } | { new_step: SuggestedNewStep };
};

export type ExpressionPayload = { before: string; after: string; reason: string };

type SuggestionBase = {
  id: number;
  step_id: string;
  /** The author's edit when there is one, else what the AI suggested. */
  edited: boolean;
  status: "pending" | "accepted" | "dismissed";
  /** Why it can't be accepted against the saved workflow; empty when it can. */
  invalid_reason: string;
  /** Its step changed after the suggestions were made. */
  stale: boolean;
};

export type AnswerSuggestion = SuggestionBase & { kind: "answer"; payload: AnswerPayload };
export type ExpressionSuggestion = SuggestionBase & { kind: "expression"; payload: ExpressionPayload };
export type Suggestion = AnswerSuggestion | ExpressionSuggestion;

export type SuggestionSet = {
  id: number;
  status: "running" | "ready" | "empty" | "error" | "closed";
  scope: SuggestScope;
  kinds: SuggestKind[];
  step_ids: string[];
  /** How many steps could have been looked at ("Looked at 20 of N steps"). */
  total_steps: number;
  failed_step_ids: string[];
  error: string;
  base_revision: number;
  created_by: { id: number; name: string | null } | null;
  created_at: string;
  finished_at: string | null;
  items: Suggestion[];
};

// server/audits/fixes_api.py: "Suggest fixes" from call audits
export type AuditFixTarget = "workflow" | "agent";
export type AuditFixKind = "answer" | "expression" | "prompt" | "script" | "knowledge" | "settings";

/** A call moment behind a fix. `at_s` is seconds into the call. */
export type AuditFixEvidence = {
  call: string;
  audit_id: number;
  line: number | null;
  at: string | null;
  at_s: number | null;
  area: string;
  step_id: string;
  step_name: string;
  /** Blank once the call's quotes were removed. */
  quote: string;
  note: string;
  event: string;
};

export type ScriptFixPayload = { section_id: string; title: string; before: string; after: string; reason: string };
export type KnowledgeFixPayload = { title: string; body: string; reason: string };
/** Keys: language, persona_name, name_pronunciation, consent_line, mood_adaptation. */
export type SettingsFixPayload = { changes: Record<string, string | boolean>; before: Record<string, string | boolean>; reason: string };

type AuditFixBase = {
  id: number;
  step_id: string;
  step_name: string;
  /** The payload is the author's edit. */
  edited: boolean;
  status: "pending" | "accepted" | "dismissed";
  /** Why it can't be accepted against the current draft; empty when it can. */
  invalid_reason: string;
  auto_applied: boolean;
  /** The workflow revision an accepted workflow fix made. */
  applied_revision: number | null;
  title: string;
  area: string;
  area_label: string;
  /** Calls (out of `pool`) that had this problem. */
  calls: number;
  pool: number;
  /** About how many overall points the problem cost. */
  score_cost: number;
  rank_score: number;
  confidence: number;
  evidence: AuditFixEvidence[];
};

export type AuditFix = AuditFixBase &
  (
    | { target: "workflow"; kind: "answer"; payload: AnswerPayload }
    | { target: "workflow"; kind: "expression" | "prompt"; payload: ExpressionPayload }
    | { target: "agent"; kind: "script"; payload: ScriptFixPayload }
    | { target: "agent"; kind: "knowledge"; payload: KnowledgeFixPayload }
    | { target: "agent"; kind: "settings"; payload: SettingsFixPayload }
  );

export type AuditFixRun = {
  id: number;
  status: "running" | "ready" | "empty" | "error";
  scope: "call" | "batch";
  error: string;
  /** The call's room for a one-call run. */
  call: string | null;
  agent: { id: number; name: string };
  agent_version: number | null;
  workflow: { id: number; name: string } | null;
  /** Audited calls looked at. */
  calls: number;
  /** Suggestions left out because they failed checks. */
  dropped: number;
  auto_applied: number;
  created_by: { id: number; name: string | null } | null;
  created_at: string;
  finished_at: string | null;
  /** Ranked best first. */
  items: AuditFix[];
};
