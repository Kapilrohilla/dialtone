"use client";

import { Sparkles } from "lucide-react";
import { useState } from "react";
import { Button, Dialog } from "@/components/ui";
import { timeAgo } from "@/lib/format";
import type { StartSuggestions } from "@/lib/queries";
import type { SuggestKind, SuggestScope, SuggestionSet } from "@/lib/types";
import styles from "./workflow.module.css";

export type SuggestDialogProps = {
  open: boolean;
  /** The step "Suggest more answers" was clicked under, or the selected step; "This step" needs one. */
  step: { id: string; name: string } | null;
  initialScope: SuggestScope;
  dirty: boolean;
  /** The open draft, to warn before replacing someone's pending suggestions. */
  current: SuggestionSet | null | undefined;
  meId: number | undefined;
  saving: boolean;
  onClose: () => void;
  /** `saveFirst`: save the unsaved graph, then ask. */
  onSuggest: (request: StartSuggestions, saveFirst: boolean) => void;
};

/** "Suggest with AI": what to look at and what to suggest. */
export function SuggestDialog(props: SuggestDialogProps) {
  return props.open ? <SuggestDialogBody {...props} /> : null;
}

function SuggestDialogBody({ step, initialScope, dirty, current, meId, saving, onClose, onSuggest }: SuggestDialogProps) {
  const [scope, setScope] = useState<SuggestScope>(step ? initialScope : "workflow");
  const [kinds, setKinds] = useState<Set<SuggestKind>>(new Set(["answers", "expressions"]));
  const pending = current && current.status !== "closed" ? current.items.filter((i) => i.status === "pending").length : 0;
  const mine = current?.created_by?.id === meId;
  const request: StartSuggestions = {
    scope,
    ...(scope === "step" && step ? { step_id: step.id } : {}),
    kinds: (["answers", "expressions"] as SuggestKind[]).filter((k) => kinds.has(k)),
  };
  const ready = request.kinds.length > 0;
  const toggle = (k: SuggestKind) =>
    setKinds((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });

  return (
    <Dialog
      open
      onClose={onClose}
      title="Suggest with AI"
      footer={
        dirty ? (
          <>
            <Button onClick={onClose}>Cancel</Button>
            <Button disabled={!ready || saving} onClick={() => onSuggest(request, false)}>Suggest anyway</Button>
            <Button variant="primary" disabled={!ready} loading={saving} onClick={() => onSuggest(request, true)}>Save and suggest</Button>
          </>
        ) : (
          <>
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" disabled={!ready} onClick={() => onSuggest(request, false)}>
              <Sparkles size={16} strokeWidth={1.75} aria-hidden="true" />
              Suggest
            </Button>
          </>
        )
      }
    >
      <div className={styles.suggestForm}>
        <fieldset className={styles.fieldset}>
          <legend className={styles.label}>Look at</legend>
          <label className={styles.choice}>
            <input type="radio" name="suggest-scope" checked={scope === "step"} disabled={!step} onChange={() => setScope("step")} />
            {step ? `This step (${step.name.trim() || "Untitled step"})` : "This step (select one first)"}
          </label>
          <label className={styles.choice}>
            <input type="radio" name="suggest-scope" checked={scope === "workflow"} onChange={() => setScope("workflow")} />
            Whole workflow
          </label>
        </fieldset>
        <fieldset className={styles.fieldset}>
          <legend className={styles.label}>Suggest</legend>
          <label className={styles.choice}>
            <input type="checkbox" checked={kinds.has("answers")} onChange={() => toggle("answers")} />
            Other answers callers give
          </label>
          <label className={styles.choice}>
            <input type="checkbox" checked={kinds.has("expressions")} onChange={() => toggle("expressions")} />
            Expressions for the agent&apos;s lines
          </label>
        </fieldset>
        {pending > 0 && (
          <p className={styles.dialogText}>
            {mine
              ? `This replaces your ${pending} pending ${pending === 1 ? "suggestion" : "suggestions"}.`
              : `This replaces ${pending} pending ${pending === 1 ? "suggestion" : "suggestions"} from ${current?.created_by?.name ?? "a teammate"}.`}
          </p>
        )}
        {dirty && <p className={styles.dialogText}>Suggestions use the last saved version. Save first?</p>}
      </div>
    </Dialog>
  );
}

export type SuggestionBannerProps = {
  set: SuggestionSet;
  pending: number;
  readOnly: boolean;
  onReview: () => void;
  onDiscard: () => void;
};

/** Shown to anyone opening a workflow with a draft waiting (and to the author once a closed panel's run is done). */
export function SuggestionBanner({ set, pending, readOnly, onReview, onDiscard }: SuggestionBannerProps) {
  if (set.status === "running") {
    return (
      <div className={styles.suggestBanner} role="status">
        <Sparkles size={16} strokeWidth={1.75} aria-hidden="true" />
        <span className={styles.suggestBannerText}>Getting suggestions…</span>
        <Button size="sm" variant="text" onClick={onReview}>Open</Button>
      </div>
    );
  }
  return (
    <div className={styles.suggestBanner} role="status">
      <Sparkles size={16} strokeWidth={1.75} aria-hidden="true" />
      <span className={styles.suggestBannerText}>
        <strong>{pending} {pending === 1 ? "suggestion is" : "suggestions are"} waiting for review</strong>
        <span className={styles.muted}> From {set.created_by?.name ?? "a teammate"}, {timeAgo(set.created_at)}</span>
      </span>
      <Button size="sm" onClick={onReview}>Review</Button>
      {!readOnly && <Button size="sm" variant="text" onClick={onDiscard}>Discard draft</Button>}
    </div>
  );
}
