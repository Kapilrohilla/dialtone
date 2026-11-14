"use client";

import { useEffect, useRef, useState } from "react";
import { AuditFixesPanel } from "@/components/audit-fixes/AuditFixesPanel";
import { Button, Field } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { agentFixesKey, useAgentFixes, useSuggestAgentFixes, type StartAgentFixes } from "@/lib/queries";
import type { Agent, AuditFix } from "@/lib/types";
import styles from "./editor.module.css";

export const FIX_LIMITS = [10, 20, 50] as const;

export type AuditFixesSectionProps = {
  agent: Agent;
  readOnly: boolean;
  /** Before an agent fix is accepted: save what's unsaved. A message stops the accept. */
  beforeAccept: (fix: AuditFix) => Promise<string | null>;
  /** An agent fix changed the saved agent: the editor reloads it. */
  onAgentChanged: () => void;
};

/** "Suggest fixes from recent calls": the last audited calls' problems turned into draft changes to review. */
export function AuditFixesSection({ agent, readOnly, beforeAccept, onAgentChanged }: AuditFixesSectionProps) {
  const { data: run, isError } = useAgentFixes(agent.id);
  const suggest = useSuggestAgentFixes(agent.id);
  const [limit, setLimit] = useState<number>(20);
  const [by, setBy] = useState<NonNullable<StartAgentFixes["by"]>>("version");
  const running = run?.status === "running";

  // Fixes applied on their own when the run finished may have changed the agent under the editor.
  const lastStatus = useRef(run?.status);
  const changed = useRef(onAgentChanged);
  changed.current = onAgentChanged;
  useEffect(() => {
    if (lastStatus.current === "running" && run && run.status !== "running" && run.items.some((i) => i.target === "agent" && i.auto_applied)) {
      changed.current();
    }
    lastStatus.current = run?.status;
  }, [run]);

  const startError = suggest.error ? (suggest.error instanceof ApiError ? suggest.error.detail : "Could not suggest fixes.") : null;

  return (
    <div className={styles.panelSection}>
      <h2 className={styles.panelTitle}>Audit fixes</h2>
      {!readOnly && (
        <>
          <p className={styles.panelNote}>Suggest fixes from recent calls: the problems their audits found, as changes to the draft.</p>
          <Field control="select" label="Calls to look at" value={String(limit)} disabled={running} onChange={(e) => setLimit(Number(e.target.value))}>
            {FIX_LIMITS.map((n) => (
              <option key={n} value={n}>Last {n} calls</option>
            ))}
          </Field>
          {agent.workflow !== null && (
            <Field
              control="select"
              label="Calls from"
              value={by}
              disabled={running}
              onChange={(e) => setBy(e.target.value as typeof by)}
            >
              <option value="version">This agent version</option>
              <option value="workflow_revision">This workflow revision</option>
            </Field>
          )}
          <Button
            className={styles.preview}
            loading={suggest.isPending}
            disabled={running}
            onClick={() => suggest.mutate({ limit, by: agent.workflow !== null ? by : "version" })}
          >
            Suggest fixes
          </Button>
          {startError && <p className={styles.fieldError} role="alert">{startError}</p>}
        </>
      )}
      {isError && <p className={styles.panelNote}>Could not load the fixes.</p>}
      {run ? (
        <AuditFixesPanel
          run={run}
          cacheKey={agentFixesKey(agent.id)}
          readOnly={readOnly}
          beforeAccept={(fix) => (fix.target === "agent" ? beforeAccept(fix) : Promise.resolve(null))}
          onAccepted={(fix) => {
            if (fix.target === "agent") onAgentChanged();
          }}
        />
      ) : (
        run === null && readOnly && <p className={styles.panelNote}>No fixes suggested yet.</p>
      )}
    </div>
  );
}
