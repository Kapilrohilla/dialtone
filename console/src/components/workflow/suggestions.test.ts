import { describe, expect, it } from "vitest";
import type { AnswerSuggestion, ExpressionSuggestion } from "@/lib/types";
import { onboardingGraph, suggestionSet } from "@/test/fixtures";
import { applySuggestion, pathKey, toFlow, undoSuggestion } from "./graph";
import { addedTokens, answerError, expressionError, stripExpressions, suggestionError } from "./suggestions";

const items = () => suggestionSet().items;
const newStepAnswer = () => items()[0] as AnswerSuggestion;
const existingAnswer = () => items()[1] as AnswerSuggestion;
const expression = () => items()[2] as ExpressionSuggestion;

describe("suggestion checks", () => {
  it("accepts the server's valid suggestions", () => {
    const g = onboardingGraph();
    for (const item of items()) expect(suggestionError(g, item, items())).toBeNull();
  });

  it("blocks an answer whose name clashes, locally or with another draft", () => {
    const g = onboardingGraph();
    const p = existingAnswer().payload;
    expect(answerError(g, "ask_licence", { ...p, label: " has LICENCE " })).toBe("A path with this name already exists. Rename it to accept.");
    expect(answerError(g, "ask_licence", p, ["licence applied, not received"])).toBe("A path with this name already exists. Rename it to accept.");
    expect(answerError(g, "ask_licence", { ...p, target: { step_id: "explain_plan" } })).toBe(
      "This step already goes there. Add the phrases to that path instead.",
    );
    expect(answerError(g, "ask_licence", { ...p, target: { step_id: "greeting" } })).toBe("A path can't lead to the start step.");
    expect(answerError(g, "ask_licence", { ...p, target: { step_id: "gone" } })).toBe("The step this pointed to was removed.");
    expect(answerError(g, "end_city", p)).toBe("Paths can't leave this kind of step.");
    expect(answerError(g, "ask_licence", { ...p, examples: [] })).toBe("Add at least one thing the caller might say.");
    expect(answerError(g, "ask_licence", { ...p, examples: ["x".repeat(41)] })).toBe("Keep each caller phrase to 40 characters.");
    const n = newStepAnswer().payload;
    if (!("new_step" in n.target)) throw new Error("fixture");
    expect(answerError(g, "ask_licence", { ...n, target: { new_step: { ...n.target.new_step, name: "Ask city" } } })).toBe(
      "A step with this name already exists. Rename the new step.",
    );
    expect(answerError(g, "ask_licence", { ...n, target: { new_step: { ...n.target.new_step, prompt: "[[expr:pause:0.1]] hi" } } })).toBe(
      "Pause is too short (0.1 s). Use at least 0.2 seconds.",
    );
  });

  it("only lets expressions add tokens", () => {
    const g = onboardingGraph();
    const p = expression().payload;
    expect(expressionError(g, "end_no_licence", { ...p, after: "[[expr:sad]] नहीं बढ़ पाएँगे" })).toBe("This would change the agent's words.");
    expect(expressionError(g, "end_no_licence", { ...p, after: p.before })).toBe("This adds no expressions.");
    g.steps.find((s) => s.id === "end_no_licence")!.prompt = "changed";
    expect(expressionError(g, "end_no_licence", p)).toBe("The agent's words for this step have changed.");
    expect(stripExpressions("[[expr:excited]]{{lead.city}} में [[expr:pause:1]]")).toBe("{{lead.city}} में");
  });

  it("marks the expressions a suggestion adds", () => {
    expect([...addedTokens("[[expr:excited]]hi", "[[expr:pause:0.6]] [[expr:excited]]hi[[expr:sad]]")]).toEqual([0, 4]);
  });
});

describe("applySuggestion", () => {
  it("adds a path with its phrases to an existing step, and undo takes it back", () => {
    const g = onboardingGraph();
    const { graph, error, applied } = applySuggestion(g, existingAnswer());
    expect(error).toBeUndefined();
    const added = graph.paths[graph.paths.length - 1];
    expect(added).toMatchObject({ from: "ask_licence", to: "schedule_callback", label: "Licence applied, not received", examples: ["apply किया है"] });
    expect(applied).toMatchObject({ kind: "answer", pathId: pathKey(added) });
    const moved = { ...graph, steps: graph.steps.map((s) => (s.id === "ask_city" ? { ...s, name: "City?" } : s)) };
    const back = undoSuggestion(moved, applied!);
    expect(back.paths).toHaveLength(g.paths.length);
    expect(back.steps.find((s) => s.id === "ask_city")?.name).toBe("City?"); // other edits are kept
  });

  it("adds a new step with its own path onwards", () => {
    const g = onboardingGraph();
    const { graph, applied } = applySuggestion(g, newStepAnswer());
    const step = graph.steps.find((s) => s.name === "Explain licence types")!;
    expect(step).toMatchObject({ type: "prompt", prompt: "[[expr:pause:0.6]] कोई बात नहीं जी।" });
    expect(graph.paths.filter((p) => p.from === step.id)).toMatchObject([{ to: "ask_licence", label: "Explained licence types" }]);
    expect(graph.paths.find((p) => p.to === step.id)).toMatchObject({ from: "ask_licence", label: "Not sure which licence" });
    expect(undoSuggestion(graph, applied!)).toEqual(g);
  });

  it("adds an end step with its outcome", () => {
    const item = newStepAnswer();
    item.payload.target = { new_step: { name: "Licence pending", type: "end", prompt: "ठीक है", outcome: "CBR" } };
    const { graph } = applySuggestion(onboardingGraph(), item);
    expect(graph.steps.find((s) => s.name === "Licence pending")).toMatchObject({ type: "end", outcome: "CBR" });
  });

  it("adds expressions, and leaves the graph as is when an item is blocked", () => {
    const g = onboardingGraph();
    const { graph, applied } = applySuggestion(g, expression());
    expect(graph.steps.find((s) => s.id === "end_no_licence")?.prompt).toBe(expression().payload.after);
    expect(undoSuggestion(graph, applied!)).toEqual(g);
    const clash = existingAnswer();
    clash.payload.label = "No licence";
    const blocked = applySuggestion(g, clash);
    expect(blocked.graph).toBe(g);
    expect(blocked.error).toBe("A path with this name already exists. Rename it to accept.");
  });
});

describe("drafts on the canvas", () => {
  it("draws pending answers dashed, with suggested cards for new steps", () => {
    const answers = items().filter((i): i is AnswerSuggestion => i.kind === "answer");
    const { nodes, edges } = toFlow(onboardingGraph(), undefined, answers);
    const card = nodes.find((n) => n.data.suggested)!;
    expect(card).toMatchObject({ id: "suggested-101", draggable: false, selectable: false });
    expect(card.data.step.name).toBe("Explain licence types");
    const dashed = edges.filter((e) => e.data?.suggested);
    expect(dashed.map((e) => [e.source, e.target])).toEqual([
      ["suggested-101", "ask_licence"],
      ["ask_licence", "suggested-101"],
      ["ask_licence", "schedule_callback"],
    ]);
    expect(dashed.every((e) => e.style?.strokeDasharray)).toBe(true);
  });
});
