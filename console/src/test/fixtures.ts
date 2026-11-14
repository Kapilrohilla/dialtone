import type {
  Agent,
  AgentListItem,
  CallDetail,
  CallPage,
  CallRow,
  Dashboard,
  Graph,
  Instance,
  KnowledgeDoc,
  LiveCall,
  Me,
  PhoneNumber,
  Step,
  SuggestionSet,
  Voice,
  Workflow,
} from "@/lib/types";

export const NUMBER = "+918047182290";

/** GET /api/instance/. Not "Dialtone", so a test can tell the saved name from the fallback. */
export const instance: Instance = { project_name: "Northwind Voice", theme: "saffron", logo_url: null };

export const me: Me = {
  id: 1,
  name: "Kapil Rohilla",
  email: "kapil@northwind.example",
  phone: "+919810000001",
  role: "owner",
  is_superuser: false,
  workspace: {
    id: 1,
    name: "Northwind Car Rentals",
    slug: "northwind",
    dead_air_enabled: true,
    recording_enabled: false,
    audit_enabled: false,
    audit_sample_pct: 100,
    audit_weights: { naturalness: 25, listening: 20, empathy: 15, pacing: 15, flow: 15, accuracy: 10 },
    audit_instructions: "",
  },
  preferences: { appearance: "system", notify_needs_person: true, notify_daily_summary: false, time_zone: "Asia/Kolkata" },
};

export const script = [
  {
    id: "greeting",
    title: "Greeting",
    body: "[[expr:happy]] नमस्ते! मैं Northwind Car Rentals से Maya बोल रही हूँ। [[expr:pause:1.2]] क्या मेरी बात {{lead.name}} जी से हो रही है?",
  },
  {
    id: "city-and-licence",
    title: "City and licence",
    body: "[[expr:laugh]] अरे वाह, बहुत बढ़िया! क्या आपके पास commercial yellow plate है?",
  },
  {
    id: "if-the-driver-hesitates",
    title: "If the driver hesitates",
    body: "[[expr:sad]] मैं आपकी बात समझ सकती हूँ। [[expr:whisper]] क्या मैं WhatsApp पर details भेज दूँ?",
  },
];

export const agent: Agent = {
  id: 3,
  name: "Driver lead qualifier",
  description: "Calls new driver leads and finds out if they can start.",
  status: "published",
  phone_number: NUMBER,
  updated_at: "2026-11-05T08:30:00Z",
  updated_by_name: "Kapil",
  is_outdated: false,
  language: "Hinglish",
  persona_name: "Maya",
  voice_id: "Kore",
  settings: { mood_adaptation: true, dead_air: { enabled: true, nudge_s: 4, second_nudge_s: 9, hang_up_s: 15 } },
  script,
  custom_expressions: {},
  knowledge: [7],
  workflow: 2,
  published_version: 4,
  created_at: "2026-10-01T10:00:00Z",
};

export const agentListItem: AgentListItem = {
  id: agent.id,
  name: agent.name,
  description: agent.description,
  status: agent.status,
  phone_number: agent.phone_number,
  updated_at: agent.updated_at,
  updated_by_name: agent.updated_by_name,
  is_outdated: agent.is_outdated,
  workflow: agent.workflow,
  calls_this_week: 42,
};

export const knowledgeDoc: KnowledgeDoc = {
  id: 7,
  title: "Pricing and plans, Pune",
  updated_at: "2026-11-03T12:00:00Z",
  current_revision: 2,
  used_by: 1,
  body_md: "# Plans\n\nThe weekly plan is for drivers who own no vehicle.",
};

export const workflow: Workflow = {
  id: 2,
  name: "Driver onboarding",
  updated_at: "2026-11-04T09:00:00Z",
  current_revision: 3,
  dead_air_enabled: true,
  errors: [],
  graph: {
    steps: [
      { id: "start", name: "Greeting", type: "start", prompt: "Greet the driver.", position: { x: 0, y: 0 } },
      { id: "city", name: "Ask city", type: "collect", field: "city", prompt: "Ask which city.", position: { x: 0, y: 160 } },
      { id: "done", name: "End: interested", type: "end", outcome: "INTERESTED", position: { x: 0, y: 320 } },
    ],
    paths: [
      { id: "p1", from: "start", to: "city", label: "Always" },
      { id: "p2", from: "city", to: "done", label: "Pune or Delhi" },
    ],
  },
};

export const callRow: CallRow = {
  room: "call-7f3a",
  started_at: "2026-11-05T09:02:00Z",
  caller: NUMBER,
  agent_name: "Driver lead qualifier",
  outcome: "Interested",
  outcome_code: "INTERESTED",
  mood: "happy",
  duration_s: 125,
  summary: "Has a commercial yellow plate in Pune and wants to start next week.",
  has_recording: false,
  recording_status: "none",
};

export const callDetail: CallDetail = {
  ...callRow,
  reason: "",
  answers: { city: "Pune", licence: "Yes" },
  step_path: ["Greeting", "Ask city"],
  transcript: [
    { speaker: "agent", text: "नमस्ते! मैं Northwind Car Rentals से Maya बोल रही हूँ।", expressions: ["happy"], at: "2026-11-05T09:02:03Z" },
    { speaker: "caller", text: "हाँ, बोलिए।", expressions: [], at: "2026-11-05T09:02:09Z" },
  ],
  recording_url: null,
  recording_status: "none",
  recording_duration_s: null,
  recording_started_at: null,
};

export const callPage: CallPage = { results: [callRow], count: 1, page: 1, pages: 1 };

export const liveCall: LiveCall = {
  room: "call-9b21",
  caller: NUMBER,
  city: "Pune",
  started_at: "2026-11-05T09:58:00Z",
  step_path: ["Greeting", "Ask city"],
  captured: { city: "Pune" },
  current_step: "Ask city",
  mood: "neutral",
  transcript_tail: callDetail.transcript,
};

export const dashboard: Dashboard = {
  calls_today: 18,
  connected_pct: 72,
  interested: 5,
  avg_duration_s: 134,
  needs_person: [{ room: "call-1c0d", caller: NUMBER, reason: "Asked to talk to a person.", at: "2026-11-05T07:40:00Z" }],
  outcomes_week: [
    { outcome: "Interested", count: 21 },
    { outcome: "Call back", count: 9 },
    { outcome: "Not interested", count: 30 },
    { outcome: "Dropped", count: 4 },
    { outcome: "Not reached", count: 12 },
  ],
  live_agent: { id: agent.id, name: agent.name, phone_number: NUMBER },
};

export const phoneNumbers: PhoneNumber[] = [{ number: NUMBER, trunk_name: "Northwind inbound", agent_name: agent.name }];

export const voices: Voice[] = [
  { id: "Kore", name: "Kore", description: "Female, firm", sample: "/voices/kore.wav" },
  { id: "priya", name: "Priya", description: "Female, Hindi", sample: null },
];

const step = (id: string, type: Step["type"], name: string, x: number, y: number, extra: Partial<Step> = {}): Step => ({
  id,
  type,
  name,
  position: { x, y },
  ...extra,
});

/** The seeded "Driver onboarding" graph (the server's demo seed command). Paths carry no ids. */
export const onboardingGraph = (): Graph => ({
  steps: [
    step("greeting", "start", "Greeting", 290, 0, { prompt: "नमस्ते, मैं Northwind से बोल रही हूँ। क्या अभी दो मिनट बात कर सकते हैं?" }),
    step("ask_city", "prompt", "Ask city", 290, 180, { prompt: "आप अभी किस शहर में रहते हैं?" }),
    step("ask_licence", "collect", "Ask licence and experience", 145, 360, {
      field: "licence",
      prompt: "क्या आपके पास अपने नाम का चार-पहिया ड्राइविंग लाइसेंस है, और आपने पहले गाड़ी चलाई है?",
    }),
    step("explain_plan", "prompt", "Explain the plan", 0, 540, {
      prompt: "[[expr:excited]]{{lead.city}} में हमारे plan के बारे में बताऊँ?[[expr:pause:1]]",
    }),
    step("end_interested", "end", "End: interested", -290, 720, { outcome: "INTERESTED", prompt: "बहुत अच्छा, मैं आपकी details हमारी team को भेज रही हूँ।" }),
    step("schedule_callback", "end", "Schedule a call back", 0, 720, { outcome: "CBR", prompt: "ठीक है, आप बताइए कब फ़ोन करूँ?" }),
    step("transfer", "transfer", "Transfer to a telecaller", 290, 720, { prompt: "मैं आपकी बात हमारी team के एक साथी से करवाती हूँ।" }),
    step("end_city", "end", "End: not in your city", 435, 360, { outcome: "NE", prompt: "अभी हम सिर्फ़ कुछ शहरों में हैं, समय देने के लिए धन्यवाद।" }),
    step("end_no_licence", "end", "End: not eligible", 290, 540, { outcome: "NE", prompt: "बिना लाइसेंस के हम आगे नहीं बढ़ पाएँगे, धन्यवाद।" }),
  ],
  paths: [
    { from: "greeting", to: "ask_city", label: "Next" },
    { from: "ask_city", to: "ask_licence", label: "Pune or Delhi" },
    { from: "ask_city", to: "end_city", label: "Other city" },
    { from: "ask_licence", to: "explain_plan", label: "Has licence" },
    { from: "ask_licence", to: "end_no_licence", label: "No licence" },
    { from: "explain_plan", to: "end_interested", label: "Interested" },
    { from: "explain_plan", to: "schedule_callback", label: "Busy" },
    { from: "explain_plan", to: "transfer", label: "Upset" },
  ],
});

// "Suggest with AI" draft for onboardingGraph (server/workflows/suggestions_api.py serialize_set).
export const suggestionSet = (over: Partial<SuggestionSet> = {}): SuggestionSet => ({
  id: 7,
  status: "ready",
  scope: "workflow",
  kinds: ["answers", "expressions"],
  step_ids: ["greeting", "ask_city", "ask_licence", "explain_plan"],
  total_steps: 4,
  failed_step_ids: [],
  error: "",
  base_revision: 3,
  created_by: { id: 1, name: "Kapil Rohilla" },
  created_at: new Date().toISOString(),
  finished_at: new Date().toISOString(),
  items: [
    {
      id: 101,
      kind: "answer",
      step_id: "ask_licence",
      payload: {
        label: "Not sure which licence",
        examples: ["पता नहीं", "शायद yellow है", "not sure ji"],
        reason: "callers often don't know their licence type.",
        target: {
          new_step: {
            name: "Explain licence types",
            type: "prompt",
            prompt: "[[expr:pause:0.6]] कोई बात नहीं जी।",
            then: { step_id: "ask_licence", label: "Explained licence types" },
          },
        },
      },
      edited: false,
      status: "pending",
      invalid_reason: "",
      stale: false,
    },
    {
      id: 102,
      kind: "answer",
      step_id: "ask_licence",
      payload: {
        label: "Licence applied, not received",
        examples: ["apply किया है"],
        reason: "many drivers are waiting for their licence.",
        target: { step_id: "schedule_callback" },
      },
      edited: false,
      status: "pending",
      invalid_reason: "",
      stale: false,
    },
    {
      id: 103,
      kind: "expression",
      step_id: "end_no_licence",
      payload: {
        before: "बिना लाइसेंस के हम आगे नहीं बढ़ पाएँगे, धन्यवाद।",
        after: "[[expr:sad]] बिना लाइसेंस के हम आगे नहीं बढ़ पाएँगे, धन्यवाद।",
        reason: "a softer tone when turning a driver away.",
      },
      edited: false,
      status: "pending",
      invalid_reason: "",
      stale: false,
    },
  ],
  ...over,
});
