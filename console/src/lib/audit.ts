import type { ChipTone } from "@/components/ui";
import type { AuditAreaKey, AuditEvidence, TranscriptTurn } from "@/lib/types";

/** Score colour bands: under 60 red, 60–79 amber, 80 and up green. */
export function scoreTone(score: number | null | undefined): ChipTone {
  if (score == null) return "neutral";
  if (score < 60) return "bad";
  if (score < 80) return "amber";
  return "ok";
}

/** The call list's Score filter: presets that match the colour bands. */
export const SCORE_RANGES = [
  { value: "low", label: "Below 60", min: "", max: "59" },
  { value: "mid", label: "60 to 79", min: "60", max: "79" },
  { value: "high", label: "80 and up", min: "80", max: "" },
] as const;

export function scoreRangeOf(min: string | undefined, max: string | undefined): string {
  if (!min && !max) return "";
  const match = SCORE_RANGES.find((r) => r.min === (min ?? "") && r.max === (max ?? ""));
  return match?.value ?? "custom";
}

export const SAMPLE_PCTS = [100, 50, 25, 10] as const;

export const EVENT_LABELS: Record<string, string> = {
  interruption: "Interruptions",
  dead_air: "Silence",
  latency: "Reply speed",
  mood: "Caller mood",
  call_end: "How the call ended",
};

/** The transcript line an audit item points at: the one with the same time (and speaker), else -1. */
export function transcriptIndex(lines: TranscriptTurn[], item: Pick<AuditEvidence, "at" | "speaker">): number {
  if (!item.at) return -1;
  const at = Date.parse(item.at);
  if (Number.isNaN(at)) return -1;
  let best = -1;
  let bestGap = Number.POSITIVE_INFINITY;
  lines.forEach((line, i) => {
    const gap = Math.abs(Date.parse(line.at) - at);
    if (gap < bestGap && (!item.speaker || line.speaker === item.speaker)) {
      best = i;
      bestGap = gap;
    }
  });
  return bestGap <= 1000 ? best : -1;
}

/** Seconds into the recording for an audit item, or null when it can't be placed. */
export function auditOffset(item: Pick<AuditEvidence, "at">, recordingStartedAt: string | null | undefined): number | null {
  if (!item.at || !recordingStartedAt) return null;
  const at = Date.parse(item.at);
  const start = Date.parse(recordingStartedAt);
  if (Number.isNaN(at) || Number.isNaN(start)) return null;
  return Math.max(0, (at - start) / 1000);
}

/** The rubric areas in order, with their names on screen. */
export const AREA_LABELS: [AuditAreaKey, string][] = [
  ["naturalness", "Sounds human"],
  ["listening", "Listening"],
  ["empathy", "Empathy and tone"],
  ["pacing", "Pacing and turn-taking"],
  ["flow", "Flow and goal"],
  ["accuracy", "Accuracy"],
];

/** A score change with its sign: "+3.2", "−1.5" (a real minus), "0". Unknown shows as "—". */
export function signed(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const v = Math.round(n * 10) / 10;
  if (v > 0) return `+${v}`;
  if (v < 0) return `\u2212${Math.abs(v)}`;
  return "0";
}
