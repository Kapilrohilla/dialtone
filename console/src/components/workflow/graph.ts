import type { Edge, Node } from "@xyflow/react";
import { DISPOSITIONS } from "@/lib/outcomes";
import { exprLabel, parse } from "@/lib/tokens";
import type { AnswerSuggestion, Graph, Path, Step, StepType, Suggestion } from "@/lib/types";
import { NODE_H, NODE_W } from "./layout";
import { suggestionError } from "./suggestions";

// Pure graph edits for the workflow builder. Every function returns a new graph and never mutates its input.

export type EdgeTone = "ok" | "amber" | "bad" | "neutral";
/** `suggested`: a draft step from "Suggest with AI"; drawn dashed, not part of the graph, not draggable. */
export type StepNodeData = { step: Step; kind: string; says: string; suggested?: boolean };
export type StepFlowNode = Node<StepNodeData, "step">;
export type PathFlowEdge = Edge<{ path: Path; tone: EdgeTone; suggested?: boolean }>;

const TONE_COLOUR: Record<EdgeTone, string> = { ok: "var(--ok)", amber: "var(--amber)", bad: "var(--bad)", neutral: "var(--rule-strong)" };
const SUGGESTED_STYLE = { stroke: "var(--blue)", strokeWidth: 1.25, strokeDasharray: "5 4" };

/** What a new step of each type is called; also the AddStepMenu's wording. */
export const STEP_NAMES: Record<StepType, string> = {
  start: "Greeting",
  prompt: "Say something",
  collect: "Collect an answer",
  knowledge: "Answer from knowledge",
  transfer: "Transfer to a telecaller",
  end: "End the call",
};

const KIND: Record<StepType, string> = { start: "Start", prompt: "Say", collect: "Collect", knowledge: "Knowledge", transfer: "Transfer", end: "End" };

export const outcomeGroup = (code: string | undefined) => DISPOSITIONS.find((d) => d.code === code)?.group;

/** The small word under a card's title: "Start", "Collect", "End: Interested". */
export function stepKind(step: Step): string {
  const group = step.type === "end" ? outcomeGroup(step.outcome) : undefined;
  return group ? `End: ${group}` : KIND[step.type] ?? step.type;
}

/** The prompt as one plain line for the card: chips read `[laugh]`, variables stay `{{lead.city}}`. */
export function stepSays(step: Step): string {
  const firstLine = (step.prompt ?? "").split("\n")[0];
  return parse(firstLine)
    .map((t) => (t.kind === "text" ? t.text : t.kind === "var" ? `{{${t.path}}}` : `[${exprLabel(t)}]`))
    .join("");
}

export const pathKey = (p: Path) => p.id ?? `${p.from}->${p.to}:${p.label}`;

/** Paths to an Interested end are ok, to a Call back end amber, to a transfer bad; the rest neutral. */
export function edgeTone(path: Path, steps: Step[]): EdgeTone {
  const to = steps.find((s) => s.id === path.to);
  if (to?.type === "transfer") return "bad";
  if (to?.type !== "end") return "neutral";
  const group = outcomeGroup(to.outcome);
  return group === "Interested" ? "ok" : group === "Call back" ? "amber" : "neutral";
}

/** Workflows read top to bottom, so a path leaves the bottom of its card for the top of the next. Only a path to a
 *  card standing to the right on the same row goes across, from the right side into the left. */
export function pathSide(from: Step, to: Step): "across" | "down" {
  const a = from.position ?? { x: 0, y: 0 };
  const b = to.position ?? { x: 0, y: 0 };
  return b.x - a.x >= NODE_W && Math.abs(b.y - a.y) < NODE_H ? "across" : "down";
}

export const suggestedStepId = (item: Suggestion) => `suggested-${item.id}`;

/** React Flow nodes and edges. Paths whose ends are missing are left out (the server's errors name them).
 *  `drafts`: pending answer suggestions, drawn as dashed paths (and "Suggested" cards for new steps). */
export function toFlow(graph: Graph, selectedId?: string, drafts: AnswerSuggestion[] = []): { nodes: StepFlowNode[]; edges: PathFlowEdge[] } {
  const byId = new Map(graph.steps.map((s) => [s.id, s]));
  const nodes = graph.steps.map<StepFlowNode>((step) => ({
    id: step.id,
    type: "step",
    position: step.position ?? { x: 0, y: 0 },
    selected: step.id === selectedId,
    data: { step, kind: stepKind(step), says: stepSays(step) },
  }));
  const edges = graph.paths
    .filter((p) => byId.has(p.from) && byId.has(p.to))
    .map<PathFlowEdge>((path) => {
      const tone = edgeTone(path, graph.steps);
      const side = pathSide(byId.get(path.from)!, byId.get(path.to)!);
      return {
        id: pathKey(path),
        source: path.from,
        target: path.to,
        sourceHandle: side === "across" ? "right" : "bottom",
        targetHandle: side === "across" ? "left" : "top",
        type: "smoothstep",
        label: path.label,
        style: { stroke: TONE_COLOUR[tone], strokeWidth: 1.25 },
        data: { path, tone },
      };
    });
  const perSource = new Map<string, number>();
  for (const item of drafts) {
    const source = byId.get(item.step_id);
    if (!source) continue;
    const p = item.payload;
    let to: string;
    if ("new_step" in p.target) {
      const n = p.target.new_step;
      const k = perSource.get(source.id) ?? 0;
      perSource.set(source.id, k + 1);
      const at = source.position ?? { x: 0, y: 0 };
      const step: Step = { id: suggestedStepId(item), name: n.name, type: n.type, prompt: n.prompt, ...(n.type === "end" ? { outcome: n.outcome } : {}) };
      step.position = { x: at.x + NODE_W + 60 + k * (NODE_W + 40), y: at.y + NODE_H + 140 };
      nodes.push({
        id: step.id,
        type: "step",
        position: step.position,
        draggable: false,
        selectable: false,
        connectable: false,
        data: { step, kind: "New step", says: stepSays(step), suggested: true },
      });
      to = step.id;
      if (n.type === "prompt" && byId.has(n.then.step_id)) {
        const then: Path = { id: `${step.id}-then`, from: step.id, to: n.then.step_id, label: n.then.label };
        edges.push(draftEdge(then, "bottom", "top"));
      }
    } else {
      if (!byId.has(p.target.step_id)) continue;
      to = p.target.step_id;
    }
    edges.push(draftEdge({ id: `suggested-path-${item.id}`, from: source.id, to, label: p.label, examples: p.examples }, "bottom", "top"));
  }
  return { nodes, edges };
}

function draftEdge(path: Path, sourceHandle: string, targetHandle: string): PathFlowEdge {
  return {
    id: path.id!,
    source: path.from,
    target: path.to,
    sourceHandle,
    targetHandle,
    type: "smoothstep",
    label: path.label,
    style: SUGGESTED_STYLE,
    labelStyle: { fill: "var(--blue)" },
    data: { path, tone: "neutral", suggested: true },
  };
}

const suffix = () => Math.random().toString(36).slice(2, 6).padEnd(4, "0");
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

function uniqueId(base: string, taken: Set<string>) {
  for (let i = 0; ; i++) {
    const id = i < 20 ? `${base}-${suffix()}` : `${base}-${suffix()}${i}`;
    if (!taken.has(id)) return id;
  }
}

/** A new step of `type`, 220px below `near` (or below the lowest step). */
export function addStep(graph: Graph, type: StepType, near?: Step): { graph: Graph; step: Step } {
  const name = STEP_NAMES[type];
  const id = uniqueId(slug(name), new Set(graph.steps.map((s) => s.id)));
  let position = { x: 0, y: 0 };
  const anchor =
    near ??
    graph.steps.reduce<Step | undefined>((low, s) => (s.position && (!low?.position || s.position.y > low.position.y) ? s : low), undefined);
  if (anchor?.position) position = { x: anchor.position.x, y: anchor.position.y + 220 };
  const step: Step = { id, type, name, prompt: "", position };
  return { graph: { ...graph, steps: [...graph.steps, step] }, step };
}

/** Removes the step and every path touching it. The only start step can't be removed: the graph comes back as is. */
export function removeStep(graph: Graph, id: string): Graph {
  const step = graph.steps.find((s) => s.id === id);
  if (!step) return graph;
  if (step.type === "start" && graph.steps.filter((s) => s.type === "start").length === 1) return graph;
  return { steps: graph.steps.filter((s) => s.id !== id), paths: graph.paths.filter((p) => p.from !== id && p.to !== id) };
}

/** Which optional fields each type uses; a type change drops the ones the new type doesn't. */
const USES: Record<StepType, (keyof Step)[]> = {
  start: [],
  prompt: ["knowledge_id"],
  collect: ["field"],
  knowledge: ["knowledge_id"],
  transfer: ["outcome"],
  end: ["outcome"],
};

export function retypeStep(graph: Graph, id: string, type: StepType): Graph {
  return {
    ...graph,
    steps: graph.steps.map((s) => {
      if (s.id !== id) return s;
      const next: Step = { ...s, type };
      for (const key of ["field", "knowledge_id", "outcome"] as const) if (!USES[type].includes(key)) delete next[key];
      return next;
    }),
  };
}

export function updateStep(graph: Graph, id: string, patch: Partial<Step>): Graph {
  return { ...graph, steps: graph.steps.map((s) => (s.id === id ? { ...s, ...patch } : s)) };
}

/** Gives every path an id so it can be edited; the server stores it. Returns the same graph when none is missing. */
export function withPathIds(graph: Graph): Graph {
  if (graph.paths.every((p) => p.id)) return graph;
  const taken = new Set(graph.paths.map((p) => p.id).filter((id): id is string => !!id));
  return {
    ...graph,
    paths: graph.paths.map((p) => {
      if (p.id) return p;
      const id = uniqueId("path", taken);
      taken.add(id);
      return { ...p, id };
    }),
  };
}

export function addPath(graph: Graph, from: string, to: string, label: string): Graph {
  const id = uniqueId("path", new Set(graph.paths.map(pathKey)));
  return { ...graph, paths: [...graph.paths, { id, from, to, label }] };
}

export function updatePath(graph: Graph, id: string, patch: Partial<Omit<Path, "id">>): Graph {
  return { ...graph, paths: graph.paths.map((p) => (pathKey(p) === id ? { ...p, ...patch } : p)) };
}

export function removePath(graph: Graph, id: string): Graph {
  return { ...graph, paths: graph.paths.filter((p) => pathKey(p) !== id) };
}

/** Applies an accepted "Suggest with AI" item to the (unsaved) graph. Nothing changes when it can't be accepted:
 *  the graph comes back as is with the reason. A new step goes below its source step, beside its siblings. */
export function applySuggestion(graph: Graph, item: Suggestion, others: Suggestion[] = []): { graph: Graph; error?: string; applied?: Applied } {
  const error = suggestionError(graph, item, others);
  if (error) return { graph, error };
  if (item.kind === "expression") {
    const { before, after } = item.payload;
    return { graph: updateStep(graph, item.step_id, { prompt: after }), applied: { itemId: item.id, kind: "expression", stepId: item.step_id, before, after } };
  }
  const p = item.payload;
  const examples = p.examples.map((e) => e.trim());
  const label = p.label.trim();
  const source = graph.steps.find((s) => s.id === item.step_id)!;
  let g = graph;
  let to: string;
  let newStepId: string | undefined;
  if ("new_step" in p.target) {
    const n = p.target.new_step;
    const added = addStep(g, n.type, source);
    newStepId = added.step.id;
    const siblings = g.steps.filter((s) => s.position && added.step.position && s.position.y === added.step.position.y).length;
    const at = added.step.position ?? { x: 0, y: 0 };
    g = updateStep(added.graph, added.step.id, {
      name: n.name.trim(),
      prompt: n.prompt,
      position: { x: at.x + siblings * (NODE_W + 40), y: at.y },
      ...(n.type === "end" ? { outcome: n.outcome } : {}),
    });
    to = added.step.id;
    if (n.type === "prompt") g = addPath(g, to, n.then.step_id, n.then.label.trim());
  } else {
    to = p.target.step_id;
  }
  g = addPath(g, item.step_id, to, label);
  const pathId = pathKey(g.paths[g.paths.length - 1]);
  return { graph: updatePath(g, pathId, { examples }), applied: { itemId: item.id, kind: "answer", stepId: item.step_id, pathId, newStepId } };
}

/** What an accept added, so Undo can take exactly that back and keep every other edit. */
export type Applied =
  | { itemId: number; kind: "expression"; stepId: string; before: string; after: string }
  | { itemId: number; kind: "answer"; stepId: string; pathId: string; newStepId?: string };

/** Takes an accepted suggestion back out of the graph: its path (and new step), or its expressions when the line
 *  is still what the suggestion made it. */
export function undoSuggestion(graph: Graph, applied: Applied): Graph {
  if (applied.kind === "expression") {
    const step = graph.steps.find((s) => s.id === applied.stepId);
    return step && (step.prompt ?? "") === applied.after ? updateStep(graph, applied.stepId, { prompt: applied.before }) : graph;
  }
  const g = removePath(graph, applied.pathId);
  return applied.newStepId ? removeStep(g, applied.newStepId) : g;
}
