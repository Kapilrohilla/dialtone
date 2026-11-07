import { DISPOSITIONS } from "@/lib/outcomes";
import { MAX_PAUSE_S, MIN_PAUSE_S, parse } from "@/lib/tokens";
import type { AnswerPayload, ExpressionPayload, Graph, Step, Suggestion } from "@/lib/types";

// The server's suggestion checks (dashboard/workflows/suggestions.py), run on the unsaved graph before Accept so a
// local edit that clashes blocks Accept with the same reason. Unknown expressions are left to the server: the console
// doesn't know the agents' custom ones.

export const MAX_LABEL = 60;
export const MAX_STEP_NAME = 60;
export const MAX_EXAMPLES = 5;
export const MAX_EXAMPLE = 40;
const ANSWER_STEP_TYPES = new Set(["start", "prompt", "collect", "knowledge"]);

const norm = (s: unknown) => (typeof s === "string" ? s.split(/\s+/).filter(Boolean).join(" ").toLowerCase() : "");

/** The words alone: every `[[expr:…]]` token removed, whitespace normalised. */
export function stripExpressions(text: string): string {
  return text.replace(/\[\[expr:[a-z_]+(?::\d+(?:\.\d+)?)?\]\]/g, " ").split(/\s+/).filter(Boolean).join(" ");
}

function pauseError(text: string): string | null {
  for (const t of parse(text)) {
    if (t.kind !== "expr" || t.name !== "pause" || t.seconds === undefined) continue;
    if (t.seconds > MAX_PAUSE_S) return `Pause is too long (${t.seconds} s). Use at most ${MAX_PAUSE_S} seconds.`;
    if (t.seconds < MIN_PAUSE_S) return `Pause is too short (${t.seconds} s). Use at least ${MIN_PAUSE_S} seconds.`;
  }
  return null;
}

export function answerError(graph: Graph, stepId: string, p: AnswerPayload, takenLabels: string[] = []): string | null {
  const source = graph.steps.find((s) => s.id === stepId);
  if (!source) return "The step this came from was removed.";
  if (!ANSWER_STEP_TYPES.has(source.type)) return "Paths can't leave this kind of step.";
  const label = (p.label ?? "").trim();
  if (!label) return "Path name can't be empty.";
  if (label.length > MAX_LABEL) return `Keep path name to ${MAX_LABEL} characters.`;
  const out = graph.paths.filter((x) => x.from === stepId);
  if ([...out.map((x) => x.label), ...takenLabels].some((l) => norm(l) === norm(label)))
    return "A path with this name already exists. Rename it to accept.";
  const examples = (p.examples ?? []).map((e) => e.trim());
  if (examples.length === 0) return "Add at least one thing the caller might say.";
  if (examples.some((e) => !e)) return "A caller phrase is empty.";
  if (examples.some((e) => e.length > MAX_EXAMPLE)) return `Keep each caller phrase to ${MAX_EXAMPLE} characters.`;
  if (examples.length > MAX_EXAMPLES) return `Use at most ${MAX_EXAMPLES} caller phrases.`;
  const target = p.target;
  if (!target) return "Choose where this path goes.";
  if ("new_step" in target) {
    const n = target.new_step;
    const name = (n.name ?? "").trim();
    if (!name) return "New step name can't be empty.";
    if (name.length > MAX_STEP_NAME) return `Keep new step name to ${MAX_STEP_NAME} characters.`;
    if (graph.steps.some((s) => norm(s.name) === norm(name))) return "A step with this name already exists. Rename the new step.";
    const pause = pauseError(n.prompt ?? "");
    if (pause) return pause;
    if (n.type === "prompt") {
      const then = graph.steps.find((s) => s.id === n.then?.step_id);
      if (!then) return "The step after the new step was removed.";
      if (then.type === "start") return "A path can't lead to the start step.";
      if (!(n.then.label ?? "").trim()) return "The next path's name can't be empty.";
      return null;
    }
    if (n.type === "end") return DISPOSITIONS.some((d) => d.code === n.outcome) ? null : "Choose an outcome for the new end step.";
    return "A new step must say something or end the call.";
  }
  const to = graph.steps.find((s) => s.id === target.step_id);
  if (!to) return "The step this pointed to was removed.";
  if (to.id === stepId) return "A path can't lead back to its own step.";
  if (to.type === "start") return "A path can't lead to the start step.";
  if (out.some((x) => x.to === to.id)) return "This step already goes there. Add the phrases to that path instead.";
  return null;
}

export function expressionError(graph: Graph, stepId: string, p: ExpressionPayload): string | null {
  const step = graph.steps.find((s) => s.id === stepId);
  if (!step) return "The step this came from was removed.";
  if ((step.prompt ?? "") !== p.before) return "The agent's words for this step have changed.";
  if (stripExpressions(p.after) !== stripExpressions(p.before)) return "This would change the agent's words.";
  const pause = pauseError(p.after);
  if (pause) return pause;
  if (p.after.trim() === p.before.trim()) return "This adds no expressions.";
  return null;
}

/** Why `item` can't be accepted into `graph` right now, or null. `others`: the rest of the draft, for name clashes. */
export function suggestionError(graph: Graph, item: Suggestion, others: Suggestion[] = []): string | null {
  if (item.kind === "expression") return expressionError(graph, item.step_id, item.payload);
  const taken = others
    .filter((o) => o.id !== item.id && o.kind === "answer" && o.status === "pending" && o.step_id === item.step_id)
    .map((o) => (o.kind === "answer" ? o.payload.label : ""));
  return answerError(graph, item.step_id, item.payload, taken);
}

/** For an expression's "Suggested" line: which expression tokens of `after` are new (index into parse(after)). */
export function addedTokens(before: string, after: string): Set<number> {
  const old = parse(before).filter((t) => t.kind === "expr");
  const added = new Set<number>();
  let k = 0;
  parse(after).forEach((t, i) => {
    if (t.kind !== "expr") return;
    const o = old[k];
    if (o && o.kind === "expr" && o.name === t.name && o.seconds === t.seconds) k++;
    else added.add(i);
  });
  return added;
}

export const targetName = (graph: Graph, p: AnswerPayload): string => {
  if ("new_step" in p.target) return p.target.new_step.name;
  const id = p.target.step_id;
  const s: Step | undefined = graph.steps.find((x) => x.id === id);
  return s ? s.name.trim() || "Untitled step" : "A missing step";
};
