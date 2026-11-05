import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TranscriptTurn } from "@/lib/types";
import { Transcript } from "./Transcript";

const lines: TranscriptTurn[] = [
  { speaker: "agent", text: "Namaste, main Priya bol rahi hoon.", expressions: ["happy", "pause"], at: "2026-11-05T09:02:03Z" },
  { speaker: "caller", text: "Haan, boliye.", expressions: [], at: "2026-11-05T09:02:09Z" },
];

describe("Transcript", () => {
  it("labels caller and agent and renders chips", () => {
    render(<Transcript lines={lines} />);
    const log = screen.getByRole("log", { name: "Transcript" });
    expect(within(log).getByText("Agent").className).toMatch(/agent/);
    expect(within(log).getByText("Caller").className).toMatch(/caller/);
    const chips = log.querySelectorAll("[data-expr]");
    expect([...chips].map((c) => c.getAttribute("data-expr"))).toEqual(["happy", "pause"]);
    // chips come before the agent's words
    expect(chips[0].closest("p")?.textContent).toMatch(/^\[happy\]\[pause[^\]]*\]Namaste, main Priya bol rahi hoon\.$/);
    expect(within(log).getAllByText("Haan, boliye.")).toHaveLength(1);
  });

  it("says so when nothing has been said", () => {
    render(<Transcript lines={[]} empty="Nobody has spoken." />);
    expect(screen.getByText("Nobody has spoken.")).toBeInTheDocument();
  });

  function metrics(el: HTMLElement, m: { scrollHeight: number; clientHeight: number; top: number }) {
    let top = m.top;
    Object.defineProperty(el, "scrollHeight", { configurable: true, get: () => m.scrollHeight });
    Object.defineProperty(el, "clientHeight", { configurable: true, get: () => m.clientHeight });
    Object.defineProperty(el, "scrollTop", { configurable: true, get: () => top, set: (v: number) => { top = v; } });
  }

  it("follows new lines only while the reader is at the bottom", () => {
    const { rerender } = render(<Transcript lines={lines.slice(0, 1)} />);
    const log = screen.getByRole("log");
    metrics(log, { scrollHeight: 1000, clientHeight: 300, top: 700 });
    log.dispatchEvent(new Event("scroll"));
    rerender(<Transcript lines={lines} />);
    expect(log.scrollTop).toBe(1000);

    // the reader scrolls up to re-read: new lines leave the view where it is
    log.scrollTop = 200;
    log.dispatchEvent(new Event("scroll"));
    rerender(<Transcript lines={[...lines, { speaker: "caller", text: "Ek minute.", expressions: [], at: "2026-11-05T09:02:20Z" }]} />);
    expect(log.scrollTop).toBe(200);
  });

  it("keeps following when the window slides at a constant length", () => {
    const at = (n: number) => `2026-11-05T09:02:${String(10 + n).padStart(2, "0")}Z`;
    const window = (from: number) =>
      Array.from({ length: 3 }, (_, i): TranscriptTurn => ({ speaker: "caller", text: `Line ${from + i}`, expressions: [], at: at(from + i) }));
    const { rerender } = render(<Transcript lines={window(0)} />);
    const log = screen.getByRole("log");
    metrics(log, { scrollHeight: 1000, clientHeight: 300, top: 700 });
    log.dispatchEvent(new Event("scroll"));
    rerender(<Transcript lines={window(1)} />);
    expect(log.scrollTop).toBe(1000);

    log.scrollTop = 200;
    log.dispatchEvent(new Event("scroll"));
    rerender(<Transcript lines={window(2)} />);
    expect(log.scrollTop).toBe(200);
  });

  it("renders lines that share a timestamp without key clashes", () => {
    const same = { speaker: "caller", text: "Haan.", expressions: [], at: "2026-11-05T09:02:09Z" };
    render(<Transcript lines={[same, { ...same, text: "Theek hai." }]} />);
    expect(screen.getByText("Haan.")).toBeInTheDocument();
    expect(screen.getByText("Theek hai.")).toBeInTheDocument();
  });
});
