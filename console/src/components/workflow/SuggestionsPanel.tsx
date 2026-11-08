"use client";

import { Info, Sparkles, X } from "lucide-react";
import { Fragment, useState, type ReactNode } from "react";
import { ChipText } from "@/components/editor/ChipText";
import editorStyles from "@/components/editor/editor.module.css";
import { Button, Chip, Spinner, Tabs } from "@/components/ui";
import { cx } from "@/components/ui/util";
import { exprLabel, parse } from "@/lib/tokens";
import type { AnswerSuggestion, Expression, ExpressionSuggestion, Graph, Suggestion, SuggestionSet } from "@/lib/types";
import { SuggestionEditForm, type EditResult } from "./SuggestionEditForm";
import { addedTokens, suggestionError, targetName } from "./suggestions";
import styles from "./workflow.module.css";

export type StartError = { message: string; retry: boolean };

export type SuggestionsPanelProps = {
  /** The open draft; undefined while the first request is on its way. */
  set: SuggestionSet | null | undefined;
  /** The unsaved graph: Accept and its checks work on it. */
  graph: Graph;
  readOnly: boolean;
  builtins?: Expression[];
  /** Items accepted on this page and not saved yet: they are part of the graph now, not drafts. */
  acceptedIds: Set<number>;
  canUndo: boolean;
  /** Starting the run failed (e.g. the daily limit). */
  startError: StartError | null;
  starting: boolean;
  onClose: () => void;
  /** Applies one item (with the author's edit, if any) to the graph; returns why it couldn't, or null. */
  onAccept: (item: Suggestion) => string | null;
  onAcceptAll: (items: Suggestion[]) => void;
  onUndo: () => void;
  onDismiss: (item: Suggestion) => void;
  /** "Save to draft": stores the edit on the server; resolves to field errors, or null when saved. */
  onSaveDraft: (item: Suggestion, payload: Suggestion["payload"]) => Promise<string | null>;
  onDiscardAll: () => void;
  onSuggestAgain: () => void;
};

type Tab = "answers" | "expressions";

const stepName = (graph: Graph, id: string) => {
  const s = graph.steps.find((x) => x.id === id);
  return s ? s.name.trim() || "Untitled step" : "A removed step";
};

/** "Suggest with AI" review: what the AI proposed, each item to accept, edit or dismiss. Nothing changes the workflow
 *  until Accept, and nothing reaches calls until Save and republish. */
export function SuggestionsPanel(props: SuggestionsPanelProps) {
  const { set, graph, readOnly, acceptedIds, startError, starting } = props;
  const [tab, setTab] = useState<Tab | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [reviewAnyway, setReviewAnyway] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const header = (
    <div className={styles.suggestHeader}>
      <div>
        <h2 className={styles.suggestTitle}>
          <Sparkles size={18} strokeWidth={1.75} aria-hidden="true" />
          Suggestions
        </h2>
        {set && set.step_ids.length > 0 && (
          <p className={styles.muted}>{set.scope === "step" ? `For ${stepName(graph, set.step_ids[0])}` : `For ${set.step_ids.length} steps`}</p>
        )}
      </div>
      <button type="button" className={styles.iconButton} aria-label="Close suggestions" onClick={props.onClose}>
        <X size={18} strokeWidth={1.75} aria-hidden="true" />
      </button>
    </div>
  );

  const shell = (body: ReactNode, footer?: ReactNode) => (
    <aside className={cx(styles.panel, styles.suggestPanel)} aria-label="Suggestions">
      {header}
      <div className={styles.suggestBody}>{body}</div>
      {footer && <div className={styles.suggestFooter}>{footer}</div>}
    </aside>
  );

  if (startError) {
    return shell(
      <StateBox title="Couldn't get suggestions." body={startError.message} alert>
        {startError.retry && !readOnly && <Button onClick={props.onSuggestAgain}>Try again</Button>}
      </StateBox>,
    );
  }
  if (starting || set === undefined || set?.status === "running") {
    const n = set?.step_ids.length ?? 0;
    return shell(
      <div className={styles.suggestState} role="status" aria-live="polite">
        <Spinner size={20} />
        <p className={styles.suggestStateTitle}>{n ? `Looking at ${n} ${n === 1 ? "step" : "steps"}…` : "Getting suggestions…"}</p>
        <p className={styles.muted}>This takes up to 30 seconds. You can keep editing, or close this panel: the suggestions will wait for you.</p>
      </div>,
    );
  }
  if (!set) {
    return shell(<StateBox title="No suggestions" body="Ask for suggestions from the top bar or under a step's paths." />);
  }
  if (set.status === "error") {
    return shell(
      <StateBox title="Couldn't get suggestions. Your workflow hasn't changed." body={set.error === "Took too long." ? "It took too long." : set.error} alert>
        {!readOnly && <Button onClick={props.onSuggestAgain}>Try again</Button>}
      </StateBox>,
    );
  }
  if (set.status === "empty" || set.items.length === 0) {
    return shell(
      <StateBox
        title="Nothing to suggest"
        body={set.scope === "step" ? "This step already covers the answers callers usually give." : "This workflow already covers the answers callers usually give."}
      >
        <div className={styles.suggestActions}>
          {!readOnly && <Button onClick={props.onSuggestAgain}>Suggest again</Button>}
          <Button variant="text" onClick={props.onClose}>Close</Button>
        </div>
      </StateBox>,
    );
  }

  const pending = set.items.filter((i) => i.status === "pending" && !acceptedIds.has(i.id));
  const editingItem = editing === null ? undefined : pending.find((i) => i.id === editing);
  if (editingItem && !readOnly) {
    return (
      <aside className={cx(styles.panel, styles.suggestPanel)} aria-label="Edit suggestion">
        <SuggestionEditForm
          key={editingItem.id}
          item={editingItem}
          graph={graph}
          others={pending}
          builtins={props.builtins}
          onCancel={() => setEditing(null)}
          onSaveDraft={async (payload) => {
            const err = await props.onSaveDraft(editingItem, payload);
            if (!err) setEditing(null);
            return err;
          }}
          onAccept={(payload): EditResult => {
            const err = props.onAccept({ ...editingItem, payload } as Suggestion);
            if (!err) setEditing(null);
            return err;
          }}
        />
      </aside>
    );
  }

  const answers = pending.filter((i): i is AnswerSuggestion => i.kind === "answer");
  const expressions = pending.filter((i): i is ExpressionSuggestion => i.kind === "expression");
  const current: Tab = tab ?? (answers.length || !expressions.length ? "answers" : "expressions");
  const shown: Suggestion[] = current === "answers" ? answers : expressions;
  const reasonOf = (item: Suggestion) => suggestionError(graph, item, pending) ?? (item.invalid_reason || null);
  const stale = pending.some((i) => i.stale);
  const acceptable = shown.filter((i) => !reasonOf(i));

  const undo = props.canUndo && !readOnly && (
    <div className={styles.suggestUndo}>
      <span>Accepted. Save to keep it.</span>
      <Button size="sm" variant="text" onClick={props.onUndo}>Undo</Button>
    </div>
  );

  if (pending.length === 0) {
    return shell(
      <>
        {undo}
        <StateBox title="All reviewed" body="Every suggestion has been accepted or dismissed. Save to keep what you accepted." />
      </>,
    );
  }

  if (stale && !reviewAnyway) {
    const valid = pending.filter((i) => !reasonOf(i));
    const invalid = pending.filter((i) => reasonOf(i));
    return shell(
      <>
        <div className={styles.suggestWarn} role="alert">
          <p className={styles.suggestStateTitle}>These suggestions are out of date.</p>
          <p>Someone changed {set.scope === "step" ? "this step" : "these steps"} after the suggestions were made.</p>
          <div className={styles.suggestActions}>
            {!readOnly && <Button onClick={props.onSuggestAgain}>Suggest again</Button>}
            <Button variant="text" onClick={() => setReviewAnyway(true)}>Review anyway</Button>
          </div>
        </div>
        {valid.length > 0 && (
          <section aria-label="Still valid suggestions">
            <h3 className={styles.label}>Still valid suggestions</h3>
            <ul className={styles.suggestSummary}>{valid.map((i) => <li key={i.id}>{summary(graph, i)}</li>)}</ul>
          </section>
        )}
        {invalid.length > 0 && (
          <section aria-label="No longer valid suggestions">
            <h3 className={styles.label}>No longer valid suggestions</h3>
            <ul className={styles.suggestSummary}>
              {invalid.map((i) => (
                <li key={i.id}>
                  <s>{summary(graph, i)}</s>
                  <span className={styles.suggestBlocked}>{reasonOf(i)}</span>
                </li>
              ))}
            </ul>
          </section>
        )}
      </>,
    );
  }

  return shell(
    <>
      <p className={styles.suggestNotice}>
        <Info size={16} strokeWidth={1.75} aria-hidden="true" />
        <span>These are a draft. Your workflow hasn&apos;t changed. Accept what you want, then Save.</span>
      </p>
      {set.total_steps > set.step_ids.length && set.scope === "workflow" && (
        <p className={styles.muted}>Looked at {set.step_ids.length} of {set.total_steps} steps.</p>
      )}
      {set.failed_step_ids.length > 0 && <p className={styles.muted}>Some steps couldn&apos;t be checked.</p>}
      {undo}
      {notice && <p className={styles.suggestBlocked} role="alert">{notice}</p>}
      <Tabs<Tab>
        label="Suggestion kinds"
        tabs={[
          { id: "answers", label: `Answers ${answers.length}` },
          { id: "expressions", label: `Expressions ${expressions.length}` },
        ]}
        value={current}
        onChange={(t) => {
          setTab(t);
          setNotice(null);
        }}
      >
        {shown.length === 0 ? (
          <p className={styles.muted}>{current === "answers" ? "No other answers to suggest." : "No expressions to suggest."}</p>
        ) : (
          <ul className={styles.suggestList}>
            {shown.map((item) => (
              <li key={item.id} className={styles.suggestItem}>
                <ItemRow
                  item={item}
                  graph={graph}
                  readOnly={readOnly}
                  reason={reasonOf(item)}
                  onAccept={() => setNotice(props.onAccept(item))}
                  onEdit={() => setEditing(item.id)}
                  onDismiss={() => props.onDismiss(item)}
                />
              </li>
            ))}
          </ul>
        )}
      </Tabs>
      {current === "expressions" && shown.length > 0 && (
        <p className={styles.muted}>Expressions guide the agent&apos;s tone. They are hints, not exact audio.</p>
      )}
    </>,
    !readOnly && (
      <>
        <Button variant="text" onClick={props.onDiscardAll}>Discard all</Button>
        <Button disabled={acceptable.length === 0} onClick={() => props.onAcceptAll(acceptable)}>
          <Sparkles size={16} strokeWidth={1.75} aria-hidden="true" />
          Accept all {acceptable.length}
        </Button>
      </>
    ),
  );
}

function StateBox({ title, body, alert, children }: { title: string; body?: string; alert?: boolean; children?: ReactNode }) {
  return (
    <div className={styles.suggestState} role={alert ? "alert" : undefined}>
      <p className={styles.suggestStateTitle}>{title}</p>
      {body && <p className={styles.muted}>{body}</p>}
      {children}
    </div>
  );
}

function summary(graph: Graph, item: Suggestion): string {
  if (item.kind === "answer") return `${stepName(graph, item.step_id)}: “${item.payload.label}” → ${targetName(graph, item.payload)}`;
  return `${stepName(graph, item.step_id)}: expressions`;
}

type RowProps = {
  item: Suggestion;
  graph: Graph;
  readOnly: boolean;
  reason: string | null;
  onAccept: () => void;
  onEdit: () => void;
  onDismiss: () => void;
};

function ItemRow({ item, graph, readOnly, reason, onAccept, onEdit, onDismiss }: RowProps) {
  const title = item.kind === "answer" ? `“${item.payload.label}”` : stepName(graph, item.step_id);
  return (
    <article aria-label={item.kind === "answer" ? `Answer ${item.payload.label}` : `Expressions for ${title}`}>
      <div className={styles.suggestRowHead}>
        <h3 className={styles.suggestRowTitle}>{title}</h3>
        {!readOnly && (
          <div className={styles.suggestRowActions}>
            {!reason && <Button size="sm" onClick={onAccept}>Accept</Button>}
            <Button size="sm" variant="text" onClick={onEdit}>Edit</Button>
            <button type="button" className={styles.iconButton} aria-label={`Dismiss ${item.kind === "answer" ? item.payload.label : `expressions for ${title}`}`} onClick={onDismiss}>
              <X size={16} strokeWidth={1.75} aria-hidden="true" />
            </button>
          </div>
        )}
      </div>
      <dl className={styles.suggestFacts}>
        {item.kind === "answer" ? <AnswerFacts item={item} graph={graph} /> : <ExpressionFacts item={item} />}
      </dl>
      {reason && <p className={styles.suggestBlocked}>{reason}</p>}
    </article>
  );
}

function AnswerFacts({ item, graph }: { item: AnswerSuggestion; graph: Graph }) {
  const p = item.payload;
  return (
    <>
      <dt>From</dt>
      <dd>{stepName(graph, item.step_id)}</dd>
      <dt>Goes to</dt>
      <dd className={styles.suggestTarget}>
        {"new_step" in p.target && <Chip tone="blue">New step</Chip>}
        <span>{targetName(graph, p)}</span>
      </dd>
      <dt>Caller might say</dt>
      <dd>
        <ul className={styles.phraseList} aria-label={`Caller phrases for ${p.label}`}>
          {p.examples.map((e) => (
            <li key={e} className={styles.phrase}>&ldquo;{e}&rdquo;</li>
          ))}
        </ul>
      </dd>
      {p.reason && (
        <>
          <dt>Why</dt>
          <dd>{p.reason}</dd>
        </>
      )}
    </>
  );
}

function ExpressionFacts({ item }: { item: ExpressionSuggestion }) {
  const { before, after, reason } = item.payload;
  const added = addedTokens(before, after);
  return (
    <>
      <dt>Now</dt>
      <dd><ChipText text={before} /></dd>
      <dt className={styles.suggestBlue}>Suggested</dt>
      <dd data-testid={`suggested-${item.id}`}>
        {parse(after).map((t, i) => {
          if (t.kind === "text") return <Fragment key={i}>{t.text}</Fragment>;
          if (t.kind === "var") return <span key={i} className={cx(editorStyles.chip, editorStyles.variable)}>{`{{${t.path}}}`}</span>;
          return (
            <span key={i} className={cx(editorStyles.chip, editorStyles.expr, added.has(i) && styles.addedChip)} data-added={added.has(i) || undefined}>
              [{exprLabel(t)}]
            </span>
          );
        })}
      </dd>
      {reason && (
        <>
          <dt>Why</dt>
          <dd>{reason}</dd>
        </>
      )}
    </>
  );
}
