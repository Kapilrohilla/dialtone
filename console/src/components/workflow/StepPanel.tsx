"use client";

import { useId, type ReactNode } from "react";
import { TokenEditor } from "@/components/editor/TokenEditor";
import { Button, Disclosure, Field } from "@/components/ui";
import { DISPOSITIONS, OUTCOME_GROUPS } from "@/lib/outcomes";
import type { Expression, Graph, KnowledgeListItem, Path, Step, StepType } from "@/lib/types";
import { PathRows } from "./PathRows";
import styles from "./workflow.module.css";

export type StepPanelProps = {
  step: Step | null;
  graph: Graph;
  readOnly: boolean;
  knowledge: KnowledgeListItem[] | undefined;
  builtins?: Expression[];
  onChange: (patch: Partial<Omit<Step, "type">>) => void;
  onTypeChange: (type: StepType) => void;
  onAddPath: () => void;
  onPathChange: (id: string, patch: Partial<Omit<Path, "id">>) => void;
  onPathRemove: (id: string) => void;
  onDelete: () => void;
  /** "Suggest more answers" under "Then go to"; editors only. */
  onSuggest?: () => void;
  /** Settings for the whole workflow, shown while no step is selected. */
  workflowSettings?: ReactNode;
};

const TYPE_LABELS: Record<StepType, string> = {
  start: "Start",
  prompt: "Say something",
  collect: "Collect an answer",
  knowledge: "Answer from knowledge",
  transfer: "Transfer to a telecaller",
  end: "End the call",
};

/** The selected step's settings: name, what the agent says, its type's own field, and where it goes next. */
export function StepPanel(props: StepPanelProps) {
  const { step, graph, readOnly } = props;
  if (!step) {
    return (
      <aside className={styles.panel} aria-label="Step">
        {props.workflowSettings}
        <p className={styles.panelEmpty}>Select a step to edit it.</p>
      </aside>
    );
  }
  const onlyStart = step.type === "start" && graph.steps.filter((s) => s.type === "start").length === 1;
  const otherStart = graph.steps.some((s) => s.type === "start" && s.id !== step.id);

  return (
    <aside className={styles.panel} aria-label="Step">
      <h2 className={styles.panelHeading}>{step.name.trim() || "Untitled step"}</h2>
      <Field label="Step name" value={step.name} maxLength={80} readOnly={readOnly} onChange={(e) => props.onChange({ name: e.target.value })} />
      <Says key={step.id} {...props} step={step} />
      <TypeFields {...props} step={step} />
      <PathRows step={step} graph={graph} readOnly={readOnly} onAdd={props.onAddPath} onChange={props.onPathChange} onRemove={props.onPathRemove} onSuggest={props.onSuggest} />
      {!readOnly && (
        <Disclosure>
          <div className={styles.advanced}>
            <Field
              label="Step type"
              control="select"
              value={step.type}
              onChange={(e) => props.onTypeChange(e.target.value as StepType)}
            >
              {(Object.keys(TYPE_LABELS) as StepType[])
                .filter((t) => t !== "start" || !otherStart)
                .map((t) => (
                  <option key={t} value={t}>{TYPE_LABELS[t]}</option>
                ))}
            </Field>
            <div className={styles.group}>
              <Button variant="danger" size="sm" className={styles.addPath} disabled={onlyStart} onClick={props.onDelete}>
                Delete step
              </Button>
              {onlyStart && <p className={styles.muted}>Every workflow needs its start step.</p>}
            </div>
          </div>
        </Disclosure>
      )}
    </aside>
  );
}

function Says({ step, readOnly, builtins, onChange }: StepPanelProps & { step: Step }) {
  const labelId = useId();
  return (
    <div className={styles.group}>
      <span id={labelId} className={styles.label}>What the agent says</span>
      <TokenEditor
        mode="line"
        value={step.prompt ?? ""}
        onChange={(prompt) => onChange({ prompt })}
        readOnly={readOnly}
        builtins={builtins}
        aria-label="What the agent says"
        className={styles.says}
      />
    </div>
  );
}

function TypeFields({ step, readOnly, knowledge, onChange }: StepPanelProps & { step: Step }) {
  if (step.type === "collect") {
    return (
      <Field
        label="Save the answer as"
        hint="Lowercase letters, digits and underscores"
        value={step.field ?? ""}
        maxLength={32}
        readOnly={readOnly}
        onChange={(e) => onChange({ field: e.target.value })}
      />
    );
  }
  if (step.type === "knowledge" || step.type === "prompt") {
    const required = step.type === "knowledge";
    const missing = step.knowledge_id !== undefined && !knowledge?.some((d) => d.id === step.knowledge_id);
    return (
      <Field
        label="Use knowledge"
        control="select"
        value={step.knowledge_id === undefined ? "" : String(step.knowledge_id)}
        disabled={readOnly}
        onChange={(e) => onChange({ knowledge_id: e.target.value ? Number(e.target.value) : undefined })}
      >
        <option value="" disabled={required}>{required ? "Choose a document" : "None"}</option>
        {missing && <option value={String(step.knowledge_id)}>A document that no longer exists</option>}
        {knowledge?.map((d) => (
          <option key={d.id} value={String(d.id)}>{d.title}</option>
        ))}
      </Field>
    );
  }
  if (step.type === "end") {
    return (
      <Field label="Outcome" control="select" value={step.outcome ?? ""} disabled={readOnly} onChange={(e) => onChange({ outcome: e.target.value })}>
        <option value="" disabled>Choose an outcome</option>
        {step.outcome && !DISPOSITIONS.some((d) => d.code === step.outcome) && <option value={step.outcome}>An outcome that no longer exists</option>}
        {OUTCOME_GROUPS.map((group) => (
          <optgroup key={group} label={group}>
            {DISPOSITIONS.filter((d) => d.group === group).map((d) => (
              <option key={d.code} value={d.code}>{d.label}</option>
            ))}
          </optgroup>
        ))}
      </Field>
    );
  }
  if (step.type === "transfer") return <p className={styles.muted}>Hands the caller to the telecalling team.</p>;
  return null;
}
