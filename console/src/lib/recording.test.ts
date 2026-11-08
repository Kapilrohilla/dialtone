import { describe, expect, it } from "vitest";
import { activeTurn, clock, peaksOf, placeholderPeaks, speakerSegments, turnOffsets } from "./recording";
import type { TranscriptTurn } from "./types";

const turn = (speaker: string, at: string): TranscriptTurn => ({ speaker, text: "…", expressions: [], at });

describe("recording helpers", () => {
  it("formats player time with two-digit minutes", () => {
    expect(clock(0)).toBe("00:00");
    expect(clock(78.9)).toBe("01:18");
    expect(clock(3725)).toBe("1:02:05");
    expect(clock(null)).toBe("--:--");
    expect(clock(Number.POSITIVE_INFINITY)).toBe("--:--");
  });

  it("works out each turn's offset from when recording began", () => {
    const lines = [turn("agent", "2026-11-07T09:02:12Z"), turn("caller", "2026-11-07T09:02:29.500Z"), turn("agent", "nope")];
    expect(turnOffsets(lines, "2026-11-07T09:02:11Z")).toEqual([1, 18.5, null]);
    expect(turnOffsets(lines, null)).toEqual([null, null, null]);
  });

  it("finds the turn being heard", () => {
    const offsets = [1, 18.5, null, 40];
    expect(activeTurn(offsets, 0)).toBe(-1);
    expect(activeTurn(offsets, 1)).toBe(0);
    expect(activeTurn(offsets, 30)).toBe(1);
    expect(activeTurn(offsets, 99)).toBe(3);
  });

  it("splits the recording into who-spoke segments", () => {
    const lines = [turn("agent", ""), turn("caller", ""), turn("agent", "")];
    expect(speakerSegments(lines, [0, 50, 150], 100)).toEqual([
      { speaker: "agent", from: 0, to: 0.5 },
      { speaker: "caller", from: 0.5, to: 1 },
    ]);
    expect(speakerSegments(lines, [0, 50, 75], 0)).toEqual([]);
  });

  it("draws the same stand-in waveform for the same call", () => {
    const a = placeholderPeaks("call-7f3a", 32);
    expect(a).toHaveLength(32);
    expect(placeholderPeaks("call-7f3a", 32)).toEqual(a);
    expect(placeholderPeaks("call-other", 32)).not.toEqual(a);
    expect(Math.min(...a)).toBeGreaterThanOrEqual(0.2);
    expect(Math.max(...a)).toBeLessThanOrEqual(1);
  });

  it("scales real peaks so the loudest bar is full height", () => {
    const peaks = peaksOf(new Float32Array([0.1, -0.5, 0.25, 0.05]), 2);
    expect(peaks).toEqual([1, 0.5]);
  });
});
