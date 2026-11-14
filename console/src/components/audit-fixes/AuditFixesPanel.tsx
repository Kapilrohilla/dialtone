"use client";

import { Info } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { ChipText } from "@/components/editor/ChipText";
import { Button, Chip, Field, Spinner, Switch } from "@/components/ui";
import { PhraseChips } from "@/components/workflow/PhraseChips";
import { ApiError } from "@/lib/api";
import { DISPOSITIONS } from "@/lib/outcomes";
import { useAcceptAuditFix, usePatchAuditFix, useWorkflow } from "@/lib/queries";
import { clock } from "@/lib/recording";
import type {
  AnswerPayload,
  AuditFix,
  AuditFixKind,
  AuditFixRun,
  ExpressionPayload,
  Graph,
  KnowledgeFixPayload,
  ScriptFixPayload,
  SettingsFixPayload,
  SuggestedNewStep,
} from "@/lib/types";
import styles from "./AuditFixesPanel.module.css";

export type AuditFixesPanelProps = {
  run: AuditFixRun;
  /** The cached run's query key: edits, dismissals and accepts replace it. */
  cacheKey: readonly unknown[];
  /** Viewers see the fixes but can't act on them. */
  readOnly: boolean;
  /** Runs before Accept (e.g. saving the editor's unsaved changes); a message stops the accept and is shown. */
  beforeAccept?: (fix: AuditFix) => Promise<string | null>;
  /** After a fix is in the draft. */
  onAccepted?: (fix: AuditFix) => void;
};

const KIND_LABELS: Record<AuditFixKind, string> = {
  answer: "New path",
  expression: "Expressions",
  prompt: "Wording",
  script: "Script",
  knowledge: "Knowledge",
  settings: "Settings",
};

export const SETTING_LABELS: Record<string, string> = {
  language: "Language",
  persona_name: "Persona name",
  name_pronunciation: "Name pronunciation",
  consent_line: "Consent line",
  mood_adaptation: "Adjust to caller's mood",
};

const settingValue = (v: unknown) => (typeof v === "boolean" ? (v ? "On" : "Off") : v === "" || v == null ? "Not set" : String(v));

/** About how many overall points: "≈4", "≈1.5". */
const points = (n: number) => `≈${Math.round(n * 10) / 10} ${Math.round(n * 10) / 10 === 1 ? "point" : "points"}`;

/** Fixes suggested from call audits: each to accept into the draft, edit first, or dismiss. */
export function AuditFixesPanel({ run, cacheKey, readOnly, beforeAccept, onAccepted }: AuditFixesPanelProps) {
  const needsGraph = run.items.some((i) => i.kind === "answer");
  const { data: workflow } = useWorkflow(run.workflow?.id ?? 0, { enabled: needsGraph && !!run.workflow });

  if (run.status === "running") {
    return (
      <p className={styles.state} role="status">
        <Spinner size={14} /> Finding fixes{run.calls > 1 ? ` in ${run.calls} calls` : ""}… This takes up to a minute.
      </p>
    );
  }
  if (run.status === "error") {
    return (
      <p className={styles.error} role="alert">
        {run.error === "Took too long." ? "It took too long. Try again." : run.error || "Couldn't suggest fixes. Try again."}
      </p>
    );
  }

  const dropped =
    run.dropped > 0 ? (
      <p className={styles.muted}>
        {run.dropped} {run.dropped === 1 ? "suggestion failed checks and was" : "suggestions failed checks and were"} left out.
      </p>
    ) : null;

  if (run.status === "empty" || run.items.length === 0) {
    return (
      <div className={styles.panel}>
        <p className={styles.stateTitle}>No fixes this time</p>
        <p className={styles.muted}>
          {run.scope === "batch" ? `Nothing in the last ${run.calls} calls had a fix that passed checks.` : "Nothing in this call had a fix that passed checks."}
        </p>
        {dropped}
      </div>
    );
  }

  return (
    <div className={styles.panel}>
      <p className={styles.notice}>
        <Info size={16} strokeWidth={1.75} aria-hidden="true" />
        <span>Accepting changes the draft. Publish the agent for callers to hear it.</span>
      </p>
      {run.scope === "batch" && <p className={styles.muted}>From {run.calls} audited {run.calls === 1 ? "call" : "calls"}{run.agent_version ? ` on v${run.agent_version}` : ""}.</p>}
      {run.auto_applied > 0 && (
        <p className={styles.muted}>{run.auto_applied} {run.auto_applied === 1 ? "fix was" : "fixes were"} applied to the draft automatically.</p>
      )}
      {dropped}
      <ul className={styles.list} aria-label="Suggested fixes">
        {run.items.map((fix) => (
          <li key={`${fix.target}-${fix.id}`} className={styles.item}>
            <FixItem
              run={run}
              fix={fix}
              cacheKey={cacheKey}
              readOnly={readOnly}
              graph={workflow?.id === run.workflow?.id ? workflow?.graph : undefined}
              beforeAccept={beforeAccept}
              onAccepted={onAccepted}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}

type FixItemProps = {
  run: AuditFixRun;
  fix: AuditFix;
  cacheKey: readonly unknown[];
  readOnly: boolean;
  graph?: Graph;
  beforeAccept?: AuditFixesPanelProps["beforeAccept"];
  onAccepted?: AuditFixesPanelProps["onAccepted"];
};

function FixItem({ run, fix, cacheKey, readOnly, graph, beforeAccept, onAccepted }: FixItemProps) {
  const patch = usePatchAuditFix(run, cacheKey);
  const accept = useAcceptAuditFix(run, cacheKey);
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const title = fix.title || KIND_LABELS[fix.kind];
  const where =
    fix.target === "workflow"
      ? fix.step_name && `Step: ${fix.step_name}`
      : fix.kind === "script"
        ? `Section: ${fix.payload.title}`
        : "";

  async function onAccept() {
    setError(null);
    setChecking(true);
    try {
      const blocked = await beforeAccept?.(fix);
      if (blocked) {
        setError(blocked);
        return;
      }
      await accept.mutateAsync(fix);
      onAccepted?.(fix);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Could not accept this fix.");
    } finally {
      setChecking(false);
    }
  }

  function setStatus(status: "pending" | "dismissed") {
    setError(null);
    patch.mutate({ fix, status }, { onError: (e) => setError(e instanceof ApiError ? e.detail : "Could not save.") });
  }

  const dismissed = fix.status === "dismissed";
  return (
    <article aria-label={title} className={dismissed ? styles.dismissed : undefined}>
      <div className={styles.head}>
        <h4 className={styles.title}>{title}</h4>
        <Chip tone={fix.target === "workflow" ? "blue" : "amber"}>
          {fix.target === "workflow" ? "Workflow" : "Agent"} · {KIND_LABELS[fix.kind]}
        </Chip>
      </div>
      <p className={styles.meta}>
        {[
          where,
          fix.pool > 0 ? `In ${fix.calls} of ${fix.pool} ${fix.pool === 1 ? "call" : "calls"}` : "",
          fix.score_cost > 0 ? points(fix.score_cost) : "",
          fix.area_label,
          fix.edited ? "Edited" : "",
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
      {fix.payload.reason && <p className={styles.reason}>{fix.payload.reason}</p>}

      {editing && !readOnly && fix.status === "pending" ? (
        <EditForm
          fix={fix}
          saving={patch.isPending}
          onCancel={() => setEditing(false)}
          onSave={async (edited) => {
            try {
              await patch.mutateAsync({ fix, edited_payload: edited });
              setEditing(false);
              return null;
            } catch (e) {
              return e instanceof ApiError ? e : new ApiError(0, "Could not save. Check your connection and try again.");
            }
          }}
        />
      ) : (
        <Change fix={fix} graph={graph} />
      )}

      {fix.evidence.length > 0 && <Moments fix={fix} sameCall={run.scope === "call"} />}

      {fix.status === "pending" && fix.invalid_reason && <p className={styles.error}>{fix.invalid_reason}</p>}
      {fix.status === "accepted" && (
        <p className={styles.accepted} role="status">
          Accepted — in draft
          {fix.auto_applied ? " · Auto-applied" : ""}
          {fix.applied_revision != null ? ` · workflow revision ${fix.applied_revision}` : ""}
        </p>
      )}
      {error && <p className={styles.error} role="alert">{error}</p>}

      {!readOnly && !editing && fix.status !== "accepted" && (
        <div className={styles.actions}>
          {fix.status === "pending" ? (
            <>
              <Button size="sm" variant="primary" disabled={!!fix.invalid_reason} loading={checking} onClick={onAccept}>Accept</Button>
              <Button size="sm" onClick={() => setEditing(true)}>Edit</Button>
              {fix.edited && (
                <Button size="sm" variant="text" disabled={patch.isPending} onClick={() => patch.mutate({ fix, edited_payload: null })}>
                  Use the suggestion
                </Button>
              )}
              <Button size="sm" variant="text" disabled={patch.isPending} onClick={() => setStatus("dismissed")}>Dismiss</Button>
            </>
          ) : (
            <>
              <span className={styles.muted}>Dismissed</span>
              <Button size="sm" variant="text" disabled={patch.isPending} onClick={() => setStatus("pending")}>Restore</Button>
            </>
          )}
        </div>
      )}
      {readOnly && dismissed && <p className={styles.muted}>Dismissed</p>}
    </article>
  );
}

/** Before and after. */
function Change({ fix, graph }: { fix: AuditFix; graph?: Graph }) {
  switch (fix.kind) {
    case "answer":
      return <AnswerChange payload={fix.payload} stepName={fix.step_name} graph={graph} />;
    case "expression":
    case "prompt":
    case "script":
      return (
        <dl className={styles.diff}>
          <dt>Now</dt>
          <dd className={styles.before}><ChipText text={fix.payload.before} /></dd>
          <dt>Suggested</dt>
          <dd className={styles.after}><ChipText text={fix.payload.after} /></dd>
        </dl>
      );
    case "knowledge":
      return (
        <dl className={styles.diff}>
          <dt>New knowledge</dt>
          <dd className={styles.after}>
            <strong>{fix.payload.title}</strong>
            <span className={styles.body}>{fix.payload.body}</span>
          </dd>
        </dl>
      );
    case "settings":
      return (
        <ul className={styles.settings} aria-label="Setting changes">
          {Object.entries(fix.payload.changes).map(([key, value]) => (
            <li key={key}>
              {SETTING_LABELS[key] ?? key}: <s className={styles.old}>{settingValue(fix.payload.before?.[key])}</s> →{" "}
              <span className={styles.new}>{settingValue(value)}</span>
            </li>
          ))}
        </ul>
      );
  }
}

function AnswerChange({ payload, stepName, graph }: { payload: AnswerPayload; stepName: string; graph?: Graph }) {
  const name = (id: string) => {
    const s = graph?.steps.find((x) => x.id === id);
    return s ? s.name.trim() || "Untitled step" : graph ? "A missing step" : id;
  };
  const target = payload.target;
  return (
    <dl className={styles.diff}>
      <dt>New path</dt>
      <dd className={styles.after}>
        &ldquo;{payload.label}&rdquo;{stepName ? ` from ${stepName}` : ""}
      </dd>
      {payload.examples.length > 0 && (
        <>
          <dt>Caller might say</dt>
          <dd>
            <ul className={styles.phrases} aria-label={`Caller phrases for ${payload.label}`}>
              {payload.examples.map((e) => (
                <li key={e}>&ldquo;{e}&rdquo;</li>
              ))}
            </ul>
          </dd>
        </>
      )}
      <dt>Goes to</dt>
      {"new_step" in target ? (
        <dd>
          <NewStep step={target.new_step} name={name} />
        </dd>
      ) : (
        <dd>{name(target.step_id)}</dd>
      )}
    </dl>
  );
}

function NewStep({ step, name }: { step: SuggestedNewStep; name: (id: string) => string }) {
  return (
    <>
      New step: {step.name}
      {step.prompt && (
        <span className={styles.body}>
          Says: <ChipText text={step.prompt} />
        </span>
      )}
      <span className={styles.body}>
        {step.type === "prompt"
          ? `Then: ${name(step.then.step_id)}`
          : `Ends the call: ${DISPOSITIONS.find((d) => d.code === step.outcome)?.label ?? step.outcome}`}
      </span>
    </>
  );
}

function Moments({ fix, sameCall }: { fix: AuditFix; sameCall: boolean }) {
  return (
    <div>
      <h5 className={styles.momentsTitle}>Moments</h5>
      <ul className={styles.moments} aria-label={`Moments for ${fix.title || KIND_LABELS[fix.kind]}`}>
        {fix.evidence.map((e, i) => (
          <li key={i} className={styles.moment}>
            <span className={styles.momentWhere}>
              {!sameCall && (
                <Link href={`/calls?room=${encodeURIComponent(e.call)}`} className={styles.link}>{e.call}</Link>
              )}
              {e.at_s != null && <span className="mono">{clock(e.at_s)}</span>}
            </span>
            <span>
              {e.quote && <q className={styles.quote}>{e.quote}</q>}
              {e.quote && e.note ? " " : ""}
              {e.note && <span className={styles.note}>{e.note}</span>}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

type EditFormProps = {
  fix: AuditFix;
  saving: boolean;
  onCancel: () => void;
  /** Resolves to the error (field errors in `fields`), or null when saved. */
  onSave: (edited: object) => Promise<ApiError | null>;
};

/** A small form per kind: the new words, the path's name and phrases, the knowledge, or the setting values. */
function EditForm({ fix, saving, onCancel, onSave }: EditFormProps) {
  const [payload, setPayload] = useState<AuditFix["payload"]>(fix.payload);
  const [error, setError] = useState<ApiError | null>(null);
  const used = new Set<string>();
  const fieldError = (name: string) => {
    const list = error?.fields[name];
    if (!list?.length) return null;
    used.add(name);
    return list[0];
  };

  let fields: ReactNode;
  if (fix.kind === "answer") {
    const p = payload as AnswerPayload;
    const examplesError = fieldError("examples");
    fields = (
      <>
        <Field label="Path name" value={p.label} maxLength={60} error={fieldError("label")} onChange={(e) => setPayload({ ...p, label: e.target.value })} />
        <div className={styles.group}>
          <span className={styles.label}>When the caller says something like</span>
          <PhraseChips label="Caller phrases" value={p.examples} onChange={(examples) => setPayload({ ...p, examples })} />
          {examplesError && <p className={styles.error}>{examplesError}</p>}
        </div>
      </>
    );
  } else if (fix.kind === "expression" || fix.kind === "prompt" || fix.kind === "script") {
    const p = payload as ExpressionPayload | ScriptFixPayload;
    fields = (
      <Field
        control="textarea"
        label={fix.kind === "script" ? "New section text" : "What the agent says"}
        hint={fix.kind === "expression" ? "Add or move expressions. The words must stay the same." : undefined}
        rows={4}
        value={p.after}
        error={fieldError("after")}
        onChange={(e) => setPayload({ ...p, after: e.target.value })}
      />
    );
  } else if (fix.kind === "knowledge") {
    const p = payload as KnowledgeFixPayload;
    fields = (
      <>
        <Field label="Title" value={p.title} error={fieldError("title")} onChange={(e) => setPayload({ ...p, title: e.target.value })} />
        <Field control="textarea" label="Text" rows={5} value={p.body} error={fieldError("body")} onChange={(e) => setPayload({ ...p, body: e.target.value })} />
      </>
    );
  } else {
    const p = payload as SettingsFixPayload;
    const set = (key: string, value: string | boolean) => setPayload({ ...p, changes: { ...p.changes, [key]: value } });
    fields = (
      <>
        {Object.entries(p.changes).map(([key, value]) =>
          typeof value === "boolean" ? (
            <Switch key={key} label={SETTING_LABELS[key] ?? key} checked={value} onChange={(next) => set(key, next)} />
          ) : (
            <Field key={key} label={SETTING_LABELS[key] ?? key} value={String(value)} error={fieldError(key)} onChange={(e) => set(key, e.target.value)} />
          ),
        )}
        {fieldError("changes") && <p className={styles.error}>{fieldError("changes")}</p>}
      </>
    );
  }

  const other = error
    ? Object.entries(error.fields).find(([k]) => !used.has(k))?.[1][0] ?? (Object.keys(error.fields).length ? null : error.detail)
    : null;

  return (
    <form
      className={styles.edit}
      aria-label={`Edit ${fix.title || KIND_LABELS[fix.kind]}`}
      onSubmit={async (e) => {
        e.preventDefault();
        setError(await onSave(payload));
      }}
    >
      {fields}
      {other && <p className={styles.error} role="alert">{other}</p>}
      <div className={styles.actions}>
        <Button size="sm" variant="primary" type="submit" loading={saving}>Save</Button>
        <Button size="sm" variant="text" onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );
}
