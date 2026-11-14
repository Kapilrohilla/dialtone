import type { OutcomeGroup } from "@/lib/types";

export type Tone = "ok" | "amber" | "neutral" | "bad" | "muted";

export const OUTCOME_GROUPS: OutcomeGroup[] = ["Interested", "Call back", "Not interested", "Dropped", "Not reached"];

const TONES: Record<OutcomeGroup, Tone> = {
  Interested: "ok",
  "Call back": "amber",
  "Not interested": "neutral",
  Dropped: "bad",
  "Not reached": "muted",
};

export function outcomeTone(group: string): Tone {
  return TONES[group as OutcomeGroup] ?? "muted";
}

// Groups match server/calls/outcomes.py.
export const DISPOSITIONS: { code: string; group: OutcomeGroup; label: string }[] = [
  { code: "INTERESTED", group: "Interested", label: "Interested" },
  { code: "CBR", group: "Call back", label: "Asked to talk later" },
  { code: "NI", group: "Not interested", label: "Not interested" },
  { code: "NE", group: "Not interested", label: "Not eligible" },
  { code: "ISUDO", group: "Not interested", label: "Missing documents" },
  { code: "ISUID", group: "Not interested", label: "Uber ID blocked" },
  { code: "HND", group: "Not interested", label: "Not a driver" },
  { code: "WRGN", group: "Not interested", label: "Wrong number" },
  { code: "OWNVA", group: "Not interested", label: "Has own vehicle" },
  { code: "ABULR", group: "Not interested", label: "Abusive" },
  { code: "LANGUAGE_BARRIER", group: "Not interested", label: "No shared language" },
  { code: "CDRP", group: "Dropped", label: "Call cut off" },
  { code: "UNRESOLVED", group: "Dropped", label: "No clear outcome" },
  { code: "NOT_CONNECTED", group: "Not reached", label: "No conversation" },
];
