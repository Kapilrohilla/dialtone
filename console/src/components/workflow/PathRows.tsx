"use client";

import { Plus, X } from "lucide-react";
import { Button } from "@/components/ui";
import type { Graph, Path, Step } from "@/lib/types";
import { pathKey } from "./graph";
import styles from "./workflow.module.css";

export type PathRowsProps = {
  step: Step;
  graph: Graph;
  readOnly: boolean;
  onAdd: () => void;
  onChange: (id: string, patch: Partial<Omit<Path, "id">>) => void;
  onRemove: (id: string) => void;
};

const nameOf = (s: Step | undefined) => (s ? s.name.trim() || "Untitled step" : "A missing step");

/** "Then go to": one row per path leaving the step, label and target. End steps can't gain paths. */
export function PathRows({ step, graph, readOnly, onAdd, onChange, onRemove }: PathRowsProps) {
  const paths = graph.paths.filter((p) => p.from === step.id);
  const targets = graph.steps.filter((s) => s.id !== step.id);
  if (step.type === "end" && paths.length === 0) return null;

  return (
    <div className={styles.group} role="group" aria-labelledby={`then-${step.id}`}>
      <span id={`then-${step.id}`} className={styles.label}>Then go to</span>
      {paths.length === 0 && <p className={styles.muted}>No paths yet.</p>}
      {paths.map((p, i) => {
        const id = pathKey(p);
        const target = graph.steps.find((s) => s.id === p.to);
        if (readOnly) {
          return (
            <div key={id} className={styles.pathRowReadOnly}>
              <span>{p.label}</span>
              <span className={styles.pathTarget}>{nameOf(target)}</span>
            </div>
          );
        }
        return (
          <div key={id} className={styles.pathRow}>
            <input
              className={styles.input}
              aria-label={`Label of path ${i + 1}`}
              value={p.label}
              maxLength={60}
              onChange={(e) => onChange(id, { label: e.target.value })}
            />
            <select className={styles.input} aria-label={`Where path ${i + 1} goes`} value={target ? p.to : ""} onChange={(e) => onChange(id, { to: e.target.value })}>
              {!target && <option value="" disabled>A missing step</option>}
              {targets.map((s) => (
                <option key={s.id} value={s.id}>{nameOf(s)}</option>
              ))}
            </select>
            <button type="button" className={styles.iconButton} aria-label={`Remove path ${p.label.trim() || i + 1}`} onClick={() => onRemove(id)}>
              <X size={16} strokeWidth={1.75} aria-hidden="true" />
            </button>
          </div>
        );
      })}
      {!readOnly && step.type !== "end" && (
        <Button size="sm" variant="text" className={styles.addPath} disabled={targets.length === 0} onClick={onAdd}>
          <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
          Add path
        </Button>
      )}
    </div>
  );
}
