import { describe, expect, it } from "vitest";
import type { Graph } from "@/lib/types";
import { layoutMissing } from "./layout";

describe("layoutMissing", () => {
  it("lays out steps that have no position", () => {
    const g: Graph = {
      steps: [
        { id: "a", type: "start", name: "A" },
        { id: "b", type: "prompt", name: "B" },
        { id: "c", type: "end", name: "C", outcome: "NI" },
        { id: "d", type: "prompt", name: "D", position: { x: 999, y: -5 } },
      ],
      paths: [
        { from: "a", to: "b", label: "Next" },
        { from: "b", to: "c", label: "No" },
        { from: "b", to: "d", label: "Yes" },
        { from: "b", to: "missing", label: "Lost" },
      ],
    };
    const out = layoutMissing(g);
    const pos = out.steps.map((s) => s.position);
    expect(pos.every((p) => p && Number.isFinite(p.x) && Number.isFinite(p.y))).toBe(true);
    expect(new Set(pos.slice(0, 3).map((p) => `${p!.x},${p!.y}`)).size).toBe(3);
    expect(out.steps[3].position).toEqual({ x: 999, y: -5 });
    // Top to bottom: a above b.
    expect(pos[0]!.y).toBeLessThan(pos[1]!.y);
    expect(g.steps[0].position).toBeUndefined();
  });

  it("returns the same graph when every step has a position", () => {
    const g: Graph = { steps: [{ id: "a", type: "start", name: "A", position: { x: 0, y: 0 } }], paths: [] };
    expect(layoutMissing(g)).toBe(g);
  });
});
