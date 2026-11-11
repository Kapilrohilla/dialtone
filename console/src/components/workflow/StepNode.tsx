"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Sparkles } from "lucide-react";
import { memo } from "react";
import { cx } from "@/components/ui/util";
import type { StepFlowNode } from "./graph";
import styles from "./workflow.module.css";

/** A step card: name, a muted word for its type, and the first line of what the agent says. */
export const StepNode = memo(function StepNode({ data, selected, isConnectable }: NodeProps<StepFlowNode>) {
  const { step, kind, says, suggested } = data;
  // Every card has all four handles so every saved path is drawn (React Flow skips an edge whose handle is
  // missing). New paths can't be drawn into a start step or out of an end step; those handles stay hidden.
  const canEnter = isConnectable && step.type !== "start";
  const canLeave = isConnectable && step.type !== "end";
  return (
    <div className={cx(styles.node, selected && styles.selected, suggested && styles.suggestedNode)}>
      <Handle id="top" type="target" position={Position.Top} isConnectable={canEnter} className={styles.handle} />
      <Handle id="left" type="target" position={Position.Left} isConnectable={canEnter} className={styles.handle} />
      {suggested && (
        <span className={styles.suggestedChip}>
          <Sparkles size={13} strokeWidth={1.75} aria-hidden="true" />
          Suggested
        </span>
      )}
      <span className={styles.nodeTitle}>{step.name.trim() || "Untitled step"}</span>
      <span className={styles.nodeKind}>{kind}</span>
      {says && <span className={styles.nodeSays}>{says}</span>}
      <Handle id="bottom" type="source" position={Position.Bottom} isConnectable={canLeave} className={styles.handle} />
      <Handle id="right" type="source" position={Position.Right} isConnectable={canLeave} className={styles.handle} />
    </div>
  );
});
