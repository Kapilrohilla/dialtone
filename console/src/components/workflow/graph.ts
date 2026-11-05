import type { Edge, Node } from "@xyflow/react";
import { DISPOSITIONS } from "@/lib/outcomes";
import { exprLabel, parse } from "@/lib/tokens";
import type { Graph, Path, Step, StepType } from "@/lib/types";
import { NODE_H, NODE_W } from "./layout";

// Pure graph edits for the workflow builder. Every function returns a new graph and never mutates its input.

export type EdgeTone = "ok" | "amber" | "bad" | "neutral";
export type StepNodeData = { step: Step; kind: string; says: string };
export type StepFlowNode = Node<StepNodeData, "step">;
export type PathFlowEdge = Edge<{ path: Path; tone: EdgeTone }>;

const TONE_COLOUR: Record<EdgeTone, string> = { ok: "var(--ok)", amber: "var(--amber)", bad: "var(--bad)", neutral: "var(--rule-strong)" };

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

/** React Flow nodes and edges. Paths whose ends are missing are left out (the server's errors name them). */
export function toFlow(graph: Graph, selectedId?: string): { nodes: StepFlowNode[]; edges: PathFlowEdge[] } {
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
  return { nodes, edges };
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
