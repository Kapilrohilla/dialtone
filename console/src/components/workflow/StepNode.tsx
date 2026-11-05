"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { memo } from "react";
import { cx } from "@/components/ui/util";
import type { StepFlowNode } from "./graph";
import styles from "./workflow.module.css";

/** A step card: name, a muted word for its type, and the first line of what the agent says. */
export const StepNode = memo(function StepNode({ data, selected, isConnectable }: NodeProps<StepFlowNode>) {
  const { step, kind, says } = data;
  return (
    <div className={cx(styles.node, selected && styles.selected)}>
      {step.type !== "start" && (
        <>
          <Handle id="top" type="target" position={Position.Top} isConnectable={isConnectable} className={styles.handle} />
          <Handle id="left" type="target" position={Position.Left} isConnectable={isConnectable} className={styles.handle} />
        </>
      )}
      <span className={styles.nodeTitle}>{step.name.trim() || "Untitled step"}</span>
      <span className={styles.nodeKind}>{kind}</span>
      {says && <span className={styles.nodeSays}>{says}</span>}
      {step.type !== "end" && (
        <>
          <Handle id="bottom" type="source" position={Position.Bottom} isConnectable={isConnectable} className={styles.handle} />
          <Handle id="right" type="source" position={Position.Right} isConnectable={isConnectable} className={styles.handle} />
        </>
      )}
    </div>
  );
});
