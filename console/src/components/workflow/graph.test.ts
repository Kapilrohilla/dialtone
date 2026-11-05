import { describe, expect, it, vi } from "vitest";
import type { Graph } from "@/lib/types";
import { onboardingGraph } from "@/test/fixtures";
import { addPath, addStep, edgeTone, removePath, removeStep, stepKind, stepSays, toFlow, updatePath, withPathIds } from "./graph";

describe("workflow graph", () => {
  it("colours paths by where they lead", () => {
    const g = onboardingGraph();
    const tone = (to: string) => edgeTone(g.paths.find((p) => p.to === to)!, g.steps);
    expect(tone("end_interested")).toBe("ok");
    expect(tone("schedule_callback")).toBe("amber");
    expect(tone("transfer")).toBe("bad");
    expect(tone("ask_city")).toBe("neutral");
    expect(tone("end_city")).toBe("neutral");
    const { edges } = toFlow(g);
    expect(edges.find((e) => e.target === "end_interested")?.style?.stroke).toBe("var(--ok)");
    expect(edges.find((e) => e.target === "ask_city")?.style?.stroke).toBe("var(--rule-strong)");
  });

  it("drops paths to missing steps from the canvas", () => {
    const g = onboardingGraph();
    g.paths.push({ from: "ask_city", to: "gone", label: "Lost" }, { from: "gone", to: "ask_city", label: "Back" });
    const { nodes, edges } = toFlow(g, "ask_city");
    expect(nodes).toHaveLength(9);
    expect(edges).toHaveLength(8);
    expect(edges[0].id).toBe("greeting->ask_city:Next");
    expect(edges.every((e) => e.type === "smoothstep" && typeof e.label === "string")).toBe(true);
    expect(nodes.find((n) => n.id === "ask_city")?.selected).toBe(true);
    expect(nodes.find((n) => n.id === "greeting")?.selected).toBe(false);
    expect(nodes[0].position).toEqual({ x: 0, y: 160 });
    // Left to right in the seed: paths leave the right side; a step below is reached from the bottom.
    expect(edges[0]).toMatchObject({ sourceHandle: "right", targetHandle: "left" });
    const below = toFlow({ steps: [{ id: "a", type: "start", name: "A", position: { x: 0, y: 0 } }, { id: "b", type: "end", name: "B", position: { x: 40, y: 220 } }], paths: [{ from: "a", to: "b", label: "Next" }] });
    expect(below.edges[0]).toMatchObject({ sourceHandle: "bottom", targetHandle: "top" });
  });

  it("removing a step removes its paths and keeps the only start", () => {
    const g = onboardingGraph();
    const next = removeStep(g, "ask_licence");
    expect(next.steps.map((s) => s.id)).not.toContain("ask_licence");
    expect(next.paths.some((p) => p.from === "ask_licence" || p.to === "ask_licence")).toBe(false);
    expect(next.paths).toHaveLength(5);
    expect(g.steps).toHaveLength(9); // not mutated
    expect(removeStep(g, "greeting")).toBe(g);
    const twoStarts: Graph = { steps: [...g.steps, { id: "s2", type: "start", name: "Other" }], paths: g.paths };
    expect(removeStep(twoStarts, "greeting").steps.some((s) => s.id === "greeting")).toBe(false);
  });

  it("adds a step below its neighbour with a unique id", () => {
    const g = onboardingGraph();
    const near = g.steps.find((s) => s.id === "ask_city")!;
    const a = addStep(g, "collect", near);
    expect(a.step).toMatchObject({ type: "collect", name: "Collect an answer", prompt: "", position: { x: 280, y: 380 } });
    expect(a.step.id).toMatch(/^collect-an-answer-[a-z0-9]{4}$/);
    expect(a.graph.steps).toHaveLength(10);
    const b = addStep(a.graph, "collect", near);
    expect(b.step.id).not.toBe(a.step.id);
    // Without a neighbour: below the lowest step.
    const c = addStep(g, "end");
    expect(c.step).toMatchObject({ type: "end", name: "End the call", position: { x: 1120, y: 540 } });
    expect(addStep({ steps: [], paths: [] }, "prompt").step.position).toEqual({ x: 0, y: 0 });
  });

  it("keeps ids unique when the random suffix repeats", () => {
    const random = vi.spyOn(Math, "random").mockReturnValue(0.5);
    const g = onboardingGraph();
    const a = addStep(g, "prompt");
    const b = addStep(a.graph, "prompt");
    expect(b.step.id).not.toBe(a.step.id);
    random.mockRestore();
  });

  it("adds, edits and removes paths", () => {
    const g = withPathIds(onboardingGraph());
    expect(g.paths.every((p) => typeof p.id === "string")).toBe(true);
    expect(new Set(g.paths.map((p) => p.id)).size).toBe(8);
    const added = addPath(g, "greeting", "end_city", "New path");
    const p = added.paths[added.paths.length - 1];
    expect(p).toMatchObject({ from: "greeting", to: "end_city", label: "New path" });
    const renamed = updatePath(added, p.id!, { label: "Wrong time" });
    expect(renamed.paths.find((x) => x.id === p.id)?.label).toBe("Wrong time");
    expect(removePath(renamed, p.id!).paths).toHaveLength(8);
    expect(withPathIds(g)).toBe(g);
  });

  it("shows what a step says on one plain line, and its type in a word", () => {
    const g = onboardingGraph();
    const plan = g.steps.find((s) => s.id === "explain_plan")!;
    expect(stepSays(plan)).toBe("[excited]{{lead.city}} में हमारे plan के बारे में बताऊँ?[pause 1s]");
    expect(stepSays({ id: "x", type: "prompt", name: "X", prompt: "First line\nsecond" })).toBe("First line");
    expect(stepSays({ id: "x", type: "prompt", name: "X" })).toBe("");
    expect(stepKind(g.steps[0])).toBe("Start");
    expect(stepKind(g.steps[2])).toBe("Collect");
    expect(stepKind(g.steps[4])).toBe("End: Interested");
    expect(stepKind(g.steps[5])).toBe("End: Call back");
    expect(stepKind({ id: "e", type: "end", name: "E" })).toBe("End");
    expect(stepKind(g.steps[6])).toBe("Transfer");
  });
});
