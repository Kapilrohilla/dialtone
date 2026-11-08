import type { TranscriptTurn } from "@/lib/types";

export const SPEEDS = [0.75, 1, 1.25, 1.5, 2] as const;
export const SKIP_S = 10;
export const KEY_SEEK_S = 5;
export const BARS = 64;

const pad = (n: number) => String(n).padStart(2, "0");

/** Player time, always two-digit minutes: "01:18". Unknown shows as "--:--". */
export function clock(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "--:--";
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${pad(m)}:${pad(s % 60)}`;
}

/** "1.5x", "1x", "0.75x". */
export const speedLabel = (rate: number) => `${rate}x`;

/** Seconds into the recording for each transcript turn, or null when a turn's time is unknown. */
export function turnOffsets(lines: TranscriptTurn[], startedAt: string | null | undefined): (number | null)[] {
  const start = startedAt ? Date.parse(startedAt) : Number.NaN;
  return lines.map((line) => {
    const at = Date.parse(line.at);
    if (Number.isNaN(start) || Number.isNaN(at)) return null;
    return Math.max(0, (at - start) / 1000);
  });
}

/** The turn being heard at `time`: the last one that started at or before it. -1 before the first. */
export function activeTurn(offsets: (number | null)[], time: number): number {
  let found = -1;
  offsets.forEach((offset, i) => {
    if (offset != null && offset <= time + 0.05) found = i;
  });
  return found;
}

export type Segment = { speaker: "caller" | "agent"; from: number; to: number };

/** Who spoke when, as fractions of the recording (0–1), for the coloured bar under the waveform. */
export function speakerSegments(lines: TranscriptTurn[], offsets: (number | null)[], duration: number): Segment[] {
  if (!(duration > 0)) return [];
  const timed = lines
    .map((line, i) => ({ speaker: line.speaker === "agent" ? ("agent" as const) : ("caller" as const), at: offsets[i] }))
    .filter((t): t is { speaker: "caller" | "agent"; at: number } => t.at != null && t.at < duration);
  return timed.map((t, i) => ({
    speaker: t.speaker,
    from: t.at / duration,
    to: Math.min(1, (i + 1 < timed.length ? timed[i + 1].at : duration) / duration),
  }));
}

/** A steady-looking stand-in waveform (0.2–1) when the browser can't decode the audio. Same room, same shape. */
export function placeholderPeaks(seed: string, count = BARS): number[] {
  let h = 2166136261;
  for (const ch of seed) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return Array.from({ length: count }, (_, i) => {
    h = Math.imul(h ^ (h >>> 15), 2246822519) ^ i;
    const noise = ((h >>> 0) % 1000) / 1000;
    return 0.25 + 0.75 * (0.55 * noise + 0.45 * Math.abs(Math.sin(i / 2.3)));
  });
}

/** Loudest sample per bar, scaled so the loudest bar is 1. */
export function peaksOf(channel: Float32Array, count = BARS): number[] {
  const size = Math.max(1, Math.floor(channel.length / count));
  const peaks = Array.from({ length: count }, (_, i) => {
    let max = 0;
    for (let j = i * size; j < Math.min(channel.length, (i + 1) * size); j++) max = Math.max(max, Math.abs(channel[j]));
    return max;
  });
  const top = Math.max(...peaks) || 1;
  return peaks.map((p) => Math.max(0.12, p / top));
}

/** Decodes the file in the browser to draw the real waveform; null when it can't (old Safari, jsdom). */
export async function decodePeaks(data: ArrayBuffer): Promise<number[] | null> {
  const Ctx: typeof AudioContext | undefined =
    typeof window === "undefined" ? undefined : (window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext);
  if (!Ctx) return null;
  const ctx = new Ctx();
  try {
    const buffer = await ctx.decodeAudioData(data);
    return peaksOf(buffer.getChannelData(0));
  } catch {
    return null;
  } finally {
    void ctx.close?.();
  }
}
