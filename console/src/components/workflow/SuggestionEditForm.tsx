"use client";

import { ArrowLeft, Check, Sparkles } from "lucide-react";
import { useId, useState } from "react";
import { TokenEditor } from "@/components/editor/TokenEditor";
import { Button, Field } from "@/components/ui";
import { DISPOSITIONS, OUTCOME_GROUPS } from "@/lib/outcomes";
import type { AnswerPayload, Expression, ExpressionPayload, Graph, Suggestion, SuggestedNewStep } from "@/lib/types";
import { PhraseChips } from "./PhraseChips";
import { MAX_LABEL, MAX_STEP_NAME, suggestionError } from "./suggestions";
import styles from "./workflow.module.css";

/** null when it worked, else why not (shown under the form). */
export type EditResult = string | null;

export type SuggestionEditFormProps = {
  item: Suggestion;
  graph: Graph;
  /** The rest of the draft, for name clashes. */
  others: Suggestion[];
  builtins?: Expression[];
  onCancel: () => void;
  onSaveDraft: (payload: Suggestion["payload"]) => Promise<EditResult>;
  onAccept: (payload: Suggestion["payload"]) => EditResult;
};

const NEW = "__new__";
const nameOf = (graph: Graph, id: string) => {
  const s = graph.steps.find((x) => x.id === id);
  return s ? s.name.trim() || "Untitled step" : "A missing step";
};

/** Edit one suggestion before accepting it: an answer's name, phrases and target, or an expression's line. */
export function SuggestionEditForm(props: SuggestionEditFormProps) {
  const [payload, setPayload] = useState<Suggestion["payload"]>(props.item.payload);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const draft = { ...props.item, payload } as Suggestion;
  const check = suggestionError(props.graph, draft, props.others);

  async function saveDraft() {
    setSaving(true);
    try {
      setError(await props.onSaveDraft(payload));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.suggestEdit}>
      <button type="button" className={styles.linkButton} onClick={props.onCancel}>
        <ArrowLeft size={16} strokeWidth={1.75} aria-hidden="true" />
        All suggestions
      </button>
      <div className={styles.suggestHeader}>
        <h2 className={styles.suggestTitle}>Edit suggestion</h2>
        <span className={styles.suggestedChip}>
          <Sparkles size={13} strokeWidth={1.75} aria-hidden="true" />
          Suggested
        </span>
      </div>
      {draft.kind === "answer" ? (
        <AnswerFields graph={props.graph} stepId={draft.step_id} value={draft.payload} builtins={props.builtins} onChange={setPayload} />
      ) : (
        <ExpressionFields graph={props.graph} stepId={draft.step_id} value={draft.payload} builtins={props.builtins} onChange={setPayload} />
      )}
      {(error ?? check) && <p className={styles.suggestBlocked} role="alert">{error ?? check}</p>}
      <div className={styles.suggestFooter}>
        <Button variant="text" onClick={props.onCancel}>Cancel</Button>
        <Button onClick={saveDraft} loading={saving}>Save to draft</Button>
        <Button disabled={!!check} onClick={() => setError(props.onAccept(payload))}>
          <Check size={16} strokeWidth={1.75} aria-hidden="true" />
          Accept
        </Button>
      </div>
    </div>
  );
}

type AnswerFieldsProps = {
  graph: Graph;
  stepId: string;
  value: AnswerPayload;
  builtins?: Expression[];
  onChange: (p: AnswerPayload) => void;
};

function AnswerFields({ graph, stepId, value, builtins, onChange }: AnswerFieldsProps) {
  const saysId = useId();
  // The AI's new step is kept while the author tries an existing target, so switching back restores it.
  const [newStep, setNewStep] = useState<SuggestedNewStep>(
    "new_step" in value.target
      ? value.target.new_step
      : { name: "", type: "prompt", prompt: "", then: { step_id: stepId, label: "Done" } },
  );
  const isNew = "new_step" in value.target;
  const targets = graph.steps.filter((s) => s.id !== stepId && s.type !== "start");
  const setNew = (n: SuggestedNewStep) => {
    setNewStep(n);
    onChange({ ...value, target: { new_step: n } });
  };

  return (
    <>
      <Field
        label="Path name"
        hint="The agent uses this to decide when to take this path."
        value={value.label}
        maxLength={MAX_LABEL}
        onChange={(e) => onChange({ ...value, label: e.target.value })}
      />
      <div className={styles.group}>
        <span className={styles.label}>When the caller says something like</span>
        <PhraseChips label="Caller phrases" value={value.examples} onChange={(examples) => onChange({ ...value, examples })} />
      </div>
      <Field
        label="Then go to"
        control="select"
        value={isNew ? NEW : "step_id" in value.target ? value.target.step_id : ""}
        onChange={(e) => onChange({ ...value, target: e.target.value === NEW ? { new_step: newStep } : { step_id: e.target.value } })}
      >
        <option value={NEW}>{newStep.name.trim() ? `New step: ${newStep.name.trim()}` : "A new step"}</option>
        {targets.map((s) => (
          <option key={s.id} value={s.id}>{s.name.trim() || "Untitled step"}</option>
        ))}
      </Field>
      {isNew && (
        <>
          <Field label="New step name" value={newStep.name} maxLength={MAX_STEP_NAME} onChange={(e) => setNew({ ...newStep, name: e.target.value })} />
          <div className={styles.group}>
            <span id={saysId} className={styles.label}>What the agent says</span>
            <TokenEditor
              mode="line"
              value={newStep.prompt}
              onChange={(prompt) => setNew({ ...newStep, prompt })}
              builtins={builtins}
              aria-label="What the agent says in the new step"
              className={styles.says}
            />
          </div>
          {newStep.type === "prompt" ? (
            <Field
              label="After this step, go to"
              control="select"
              value={newStep.then.step_id}
              onChange={(e) => setNew({ ...newStep, then: { ...newStep.then, step_id: e.target.value } })}
            >
              {!graph.steps.some((s) => s.id === newStep.then.step_id) && <option value={newStep.then.step_id} disabled>A missing step</option>}
              {graph.steps.filter((s) => s.type !== "start").map((s) => (
                <option key={s.id} value={s.id}>{nameOf(graph, s.id)}</option>
              ))}
            </Field>
          ) : (
            <Field label="Outcome" control="select" value={newStep.outcome} onChange={(e) => setNew({ ...newStep, outcome: e.target.value })}>
              <option value="" disabled>Choose an outcome</option>
              {OUTCOME_GROUPS.map((group) => (
                <optgroup key={group} label={group}>
                  {DISPOSITIONS.filter((d) => d.group === group).map((d) => (
                    <option key={d.code} value={d.code}>{d.label}</option>
                  ))}
                </optgroup>
              ))}
            </Field>
          )}
        </>
      )}
    </>
  );
}

type ExpressionFieldsProps = {
  graph: Graph;
  stepId: string;
  value: ExpressionPayload;
  builtins?: Expression[];
  onChange: (p: ExpressionPayload) => void;
};

function ExpressionFields({ graph, stepId, value, builtins, onChange }: ExpressionFieldsProps) {
  const saysId = useId();
  return (
    <>
      <p className={styles.panelHeading}>{nameOf(graph, stepId)}</p>
      <div className={styles.group}>
        <span id={saysId} className={styles.label}>What the agent says</span>
        <TokenEditor
          mode="line"
          value={value.after}
          onChange={(after) => onChange({ ...value, after })}
          builtins={builtins}
          aria-label="What the agent says, with expressions"
          className={styles.says}
        />
        <p className={styles.muted}>Add or move expressions. The words must stay the same.</p>
      </div>
    </>
  );
}
