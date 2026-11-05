import type {
  Agent,
  AgentListItem,
  CallDetail,
  CallPage,
  CallRow,
  Dashboard,
  KnowledgeDoc,
  LiveCall,
  Me,
  PhoneNumber,
  Voice,
  Workflow,
} from "@/lib/types";

export const NUMBER = "+918047182290";

export const me: Me = {
  id: 1,
  name: "Kapil Rohilla",
  email: "kapil@carrum.example",
  phone: "+919810000001",
  role: "owner",
  workspace: { id: 1, name: "Carrum Mobility", slug: "carrum" },
  preferences: { appearance: "system", notify_needs_person: true, notify_daily_summary: false, time_zone: "Asia/Kolkata" },
};

export const script = [
  {
    id: "greeting",
    title: "Greeting",
    body: "[[expr:happy]] नमस्ते! मैं Carrum Mobility से Priya बोल रही हूँ। [[expr:pause:1.2]] क्या मेरी बात {{lead.name}} जी से हो रही है?",
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
  persona_name: "Priya",
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
};

export const callDetail: CallDetail = {
  ...callRow,
  reason: "",
  answers: { city: "Pune", licence: "Yes" },
  step_path: ["Greeting", "Ask city"],
  transcript: [
    { speaker: "agent", text: "नमस्ते! मैं Carrum Mobility से Priya बोल रही हूँ।", expressions: ["happy"], at: "2026-11-05T09:02:03Z" },
    { speaker: "caller", text: "हाँ, बोलिए।", expressions: [], at: "2026-11-05T09:02:09Z" },
  ],
  recording_url: null,
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

export const phoneNumbers: PhoneNumber[] = [{ number: NUMBER, trunk_name: "Carrum inbound", agent_name: agent.name }];

export const voices: Voice[] = [
  { id: "Kore", name: "Kore", description: "Female, firm", sample: "/voices/kore.wav" },
  { id: "priya", name: "Priya", description: "Female, Hindi", sample: null },
];
