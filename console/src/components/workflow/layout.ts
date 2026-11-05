import dagre from "@dagrejs/dagre";
import type { Graph } from "@/lib/types";

export const NODE_W = 260;
export const NODE_H = 88;

/** Fills in a position for each step that has none, from a top-to-bottom dagre layout of the whole graph.
 *  Steps that already have a position keep it. Returns the same graph when nothing is missing. */
export function layoutMissing(graph: Graph): Graph {
  if (graph.steps.every((s) => s.position)) return graph;
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "TB", nodesep: 48, ranksep: 72 });
  g.setDefaultEdgeLabel(() => ({}));
  const ids = new Set(graph.steps.map((s) => s.id));
  for (const s of graph.steps) g.setNode(s.id, { width: NODE_W, height: NODE_H });
  for (const p of graph.paths) if (ids.has(p.from) && ids.has(p.to)) g.setEdge(p.from, p.to);
  dagre.layout(g);
  return {
    ...graph,
    steps: graph.steps.map((s) => {
      if (s.position) return s;
      const n = g.node(s.id);
      // dagre gives centres; React Flow wants the top-left corner.
      return { ...s, position: { x: Math.round(n.x - NODE_W / 2), y: Math.round(n.y - NODE_H / 2) } };
    }),
  };
}
