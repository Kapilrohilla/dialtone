"use client";

import {
  Background,
  BackgroundVariant,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/base.css";
import { Maximize, Minus, Plus } from "lucide-react";
import { useMemo, useState, type KeyboardEvent } from "react";
import type { AnswerSuggestion, Graph, StepType } from "@/lib/types";
import { AddStepMenu } from "./AddStepMenu";
import { toFlow, type StepFlowNode } from "./graph";
import { StepNode } from "./StepNode";
import styles from "./workflow.module.css";

const nodeTypes = { step: StepNode };

export type CanvasProps = {
  graph: Graph;
  selectedId: string | null;
  readOnly: boolean;
  onSelect: (id: string | null) => void;
  onMove: (id: string, position: { x: number; y: number }) => void;
  onConnect: (from: string, to: string) => void;
  onAdd: (type: StepType) => void;
  /** Delete or Backspace on the selected step; the page asks first. */
  onDelete: (id: string) => void;
  /** Pending "Suggest with AI" answers, drawn dashed. They are not part of the graph. */
  drafts?: AnswerSuggestion[];
};

/** The workflow as cards and labelled paths. The graph is the source of truth; React Flow only keeps sizes. */
export function Canvas(props: CanvasProps) {
  return (
    <ReactFlowProvider>
      <Flow {...props} />
    </ReactFlowProvider>
  );
}

/** Cards rebuilt from the graph keep the sizes React Flow measured, so they stay visible. */
function keepMeasured(next: StepFlowNode[], prev: StepFlowNode[]) {
  const byId = new Map(prev.map((n) => [n.id, n]));
  return next.map((n) => {
    const old = byId.get(n.id);
    return old?.measured ? { ...n, measured: old.measured } : n;
  });
}

/** New paths never go into a start step or out of an end step. */
function canConnect(graph: Graph, from: string | null, to: string | null) {
  const type = (id: string | null) => graph.steps.find((s) => s.id === id)?.type;
  return !!from && !!to && from !== to && type(from) !== "end" && type(to) !== "start";
}

const isTyping = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));

function Flow({ graph, selectedId, readOnly, onSelect, onMove, onConnect, onAdd, onDelete, drafts }: CanvasProps) {
  const flow = useMemo(() => toFlow(graph, selectedId ?? undefined, drafts), [graph, selectedId, drafts]);
  const [nodes, setNodes] = useState(flow.nodes);
  const [shown, setShown] = useState(flow);
  if (shown !== flow) {
    setShown(flow);
    setNodes(keepMeasured(flow.nodes, nodes));
  }

  function onNodesChange(changes: NodeChange<StepFlowNode>[]) {
    // Sizes and in-progress drags are React Flow's; selection goes to the page.
    setNodes((ns) => applyNodeChanges(changes.filter((c) => c.type === "dimensions" || c.type === "position"), ns));
    const picked = changes.find((c) => c.type === "select" && c.selected);
    if (picked && "id" in picked) onSelect(picked.id);
    else if (changes.some((c) => c.type === "select")) onSelect(null);
  }

  function onKeyDown(e: KeyboardEvent) {
    if ((e.key !== "Delete" && e.key !== "Backspace") || readOnly || !selectedId || isTyping(e.target)) return;
    e.preventDefault();
    onDelete(selectedId);
  }

  return (
    <div className={styles.canvas} onKeyDown={onKeyDown}>
      <ReactFlow
        nodes={nodes}
        edges={flow.edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeDragStop={(_e, _node, dragged) => dragged.forEach((n) => onMove(n.id, { x: Math.round(n.position.x), y: Math.round(n.position.y) }))}
        isValidConnection={(c) => canConnect(graph, c.source, c.target)}
        onConnect={(c: Connection) => canConnect(graph, c.source, c.target) && onConnect(c.source, c.target)}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        edgesFocusable={false}
        deleteKeyCode={null}
        selectionKeyCode={null}
        multiSelectionKeyCode={null}
        fitView
        fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
        minZoom={0.2}
        attributionPosition="top-right"
      >
        <Background variant={BackgroundVariant.Dots} color="var(--rule-strong)" gap={20} size={1.5} className={styles.dots} />
        {!readOnly && (
          <Panel position="bottom-left">
            <AddStepMenu onAdd={onAdd} />
          </Panel>
        )}
        <Panel position="bottom-right">
          <ZoomControls />
        </Panel>
      </ReactFlow>
    </div>
  );
}

function ZoomControls() {
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  return (
    <div className={styles.canvasTools}>
      <button type="button" className={styles.toolButton} aria-label="Zoom out" onClick={() => zoomOut()}>
        <Minus size={16} strokeWidth={1.75} aria-hidden="true" />
      </button>
      <button type="button" className={styles.toolButton} aria-label="Zoom in" onClick={() => zoomIn()}>
        <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
      </button>
      <button type="button" className={styles.toolButton} aria-label="Fit the whole workflow" onClick={() => fitView({ padding: 0.15, maxZoom: 1 })}>
        <Maximize size={16} strokeWidth={1.75} aria-hidden="true" />
      </button>
    </div>
  );
}
