"use client";

import { useState } from "react";
import { Button, Field, Panel, StateBlock, Switch, useToast } from "@/components/ui";
import { TopBar } from "@/components/shell/TopBar";
import { ApiError } from "@/lib/api";
import { SAMPLE_PCTS } from "@/lib/audit";
import { useMe, useUpdateWorkspace } from "@/lib/queries";
import { canManageTeam } from "@/lib/roles";
import type { AuditAreaKey, Workspace } from "@/lib/types";
import styles from "../settings.module.css";

/** Account-wide call switches. They save on their own and reach the next call; nothing needs publishing. */
export default function CallsSettingsPage() {
  const { data: me, isError, error, refetch } = useMe();
  const update = useUpdateWorkspace();
  const toast = useToast();

  if (!me) {
    return (
      <>
        <TopBar title="Call handling" />
        <div className={styles.page}>
          {isError ? (
            <StateBlock state="error" title="Could not load your settings" body={error instanceof ApiError ? error.detail : undefined} onRetry={() => refetch()} />
          ) : (
            <StateBlock state="loading" title="Loading" />
          )}
        </div>
      </>
    );
  }

  const canChange = canManageTeam(me.role);
  const sending = update.isPending ? update.variables?.dead_air_enabled : undefined;
  const sendingRecording = update.isPending ? update.variables?.recording_enabled : undefined;

  function setRecording(next: boolean) {
    update.mutate(
      { recording_enabled: next },
      {
        onSuccess: (ws) =>
          toast.show(ws.recording_enabled ? "Calls are recorded from the next call." : "Calls aren't recorded from the next call.", "ok"),
        onError: (e) => toast.show(e instanceof ApiError ? e.detail : "Could not save.", "bad"),
      },
    );
  }

  function setCheckIns(next: boolean) {
    update.mutate(
      { dead_air_enabled: next },
      {
        onSuccess: (ws) =>
          toast.show(
            ws.dead_air_enabled
              ? "Check-ins are on from the next call, for agents and workflows that have them on."
              : "Check-ins are off for every agent from the next call.",
            "ok",
          ),
        onError: (e) => toast.show(e instanceof ApiError ? e.detail : "Could not save.", "bad"),
      },
    );
  }

  return (
    <>
      <TopBar title="Call handling" />
      <div className={styles.page}>
        <Panel>
          <section className={styles.section} aria-labelledby="recording-h">
            <h2 id="recording-h">Recording</h2>
            <div className={styles.switches}>
              <Switch
                label="Record calls"
                checked={sendingRecording ?? me.workspace.recording_enabled}
                disabled={!canChange || update.isPending}
                onChange={setRecording}
              />
            </div>
            <p className={styles.note}>
              Callers hear &ldquo;यह call quality के लिए record हो रही है।&rdquo; at the start. Recordings show in Call history and are
              kept for 90 days. Phone calls and browser voice tests are both recorded. Changes reach the next call.
            </p>
          </section>
          <AuditSettings workspace={me.workspace} canChange={canChange} />
          <section className={styles.section} aria-labelledby="silent-h" style={{ borderBottom: 0, paddingBottom: 0 }}>
            <h2 id="silent-h">Silent callers</h2>
            <div className={styles.switches}>
              <Switch
                label="Check in when the caller goes quiet"
                checked={sending ?? me.workspace.dead_air_enabled}
                disabled={!canChange || update.isPending}
                onChange={setCheckIns}
              />
            </div>
            <p className={styles.note}>
              When a caller goes quiet, the agent asks if they can hear it, asks once more, then ends the call politely. This
              switch covers all of {me.workspace.name}. Each workflow and each agent also has its own switch, and the agent
              checks in only when all of them are on. Changes reach the next call.
            </p>
            {!canChange && <p className={styles.note}>Only owners and admins can change this.</p>}
          </section>
        </Panel>
      </div>
    </>
  );
}

const AREA_LABELS: [AuditAreaKey, string][] = [
  ["naturalness", "Sounds human"],
  ["listening", "Listening"],
  ["empathy", "Empathy and tone"],
  ["pacing", "Pacing and turn-taking"],
  ["flow", "Flow and goal"],
  ["accuracy", "Accuracy"],
];

/** Call audits: Gemini scores the AI side of finished calls. The switch and the sample save at once; the
 *  weights and the extra instructions save with a button. */
function AuditSettings({ workspace, canChange }: { workspace: Workspace; canChange: boolean }) {
  const update = useUpdateWorkspace();
  const toast = useToast();
  const [weights, setWeights] = useState<Record<string, string>>(() =>
    Object.fromEntries(AREA_LABELS.map(([key]) => [key, String(workspace.audit_weights?.[key] ?? 0)])),
  );
  const [instructions, setInstructions] = useState(workspace.audit_instructions ?? "");
  const sendingOn = update.isPending ? update.variables?.audit_enabled : undefined;

  const parsed = Object.fromEntries(Object.entries(weights).map(([k, v]) => [k, Number(v)])) as Record<AuditAreaKey, number>;
  const weightError = Object.values(parsed).some((n) => !Number.isInteger(n) || n < 0 || n > 100)
    ? "Each weight must be a whole number from 0 to 100."
    : Object.values(parsed).every((n) => n === 0)
      ? "At least one area needs a weight above 0."
      : null;
  const total = Object.values(parsed).reduce((a, b) => a + (Number.isFinite(b) ? b : 0), 0);
  const dirty =
    instructions !== (workspace.audit_instructions ?? "") || AREA_LABELS.some(([key]) => parsed[key] !== workspace.audit_weights?.[key]);

  const failed = (e: unknown) => toast.show(e instanceof ApiError ? e.detail : "Could not save.", "bad");

  return (
    <section className={styles.section} aria-labelledby="audit-h">
      <h2 id="audit-h">Call audits</h2>
      <div className={styles.switches}>
        <Switch
          label="Score calls with AI"
          checked={sendingOn ?? workspace.audit_enabled}
          disabled={!canChange || update.isPending}
          onChange={(next) =>
            update.mutate(
              { audit_enabled: next },
              {
                onSuccess: (ws) => toast.show(ws.audit_enabled ? "Finished calls are scored from now on." : "Calls aren't scored automatically any more.", "ok"),
                onError: failed,
              },
            )
          }
        />
      </div>
      <p className={styles.note}>
        After each call, Gemini scores the agent&rsquo;s side from 0 to 100, with quotes from the call as evidence. Scores show in Call history.
        Calls with fewer than 2 agent lines aren&rsquo;t scored. Editors can also audit any call from its details.
      </p>
      <Field
        control="select"
        label="Calls to score"
        value={String(workspace.audit_sample_pct)}
        disabled={!canChange || update.isPending}
        hint="Scoring fewer calls costs less."
        onChange={(e) =>
          update.mutate({ audit_sample_pct: Number(e.target.value) }, { onSuccess: () => toast.show("Saved.", "ok"), onError: failed })
        }
      >
        {SAMPLE_PCTS.map((pct) => (
          <option key={pct} value={pct}>{pct === 100 ? "Every call" : `${pct}% of calls`}</option>
        ))}
      </Field>
      <fieldset className={styles.form} disabled={!canChange} style={{ border: 0, padding: 0, margin: 0 }}>
        <legend className={styles.note} style={{ marginBottom: 8 }}>
          How much each area counts in the overall score (now {total} in total; they don&rsquo;t need to add up to 100).
        </legend>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
          {AREA_LABELS.map(([key, label]) => (
            <Field
              key={key}
              label={label}
              type="number"
              min={0}
              max={100}
              step={1}
              inputMode="numeric"
              value={weights[key]}
              onChange={(e) => setWeights((w) => ({ ...w, [key]: e.target.value }))}
            />
          ))}
        </div>
        {weightError && <p className={styles.note} role="alert">{weightError}</p>}
        <Field
          control="textarea"
          label="Extra instructions for scoring"
          hint="For example: Our callers are drivers; keep it informal."
          maxLength={1000}
          rows={3}
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
        />
        <div>
          <Button
            variant="primary"
            disabled={!dirty || Boolean(weightError)}
            loading={update.isPending && update.variables?.audit_weights !== undefined}
            onClick={() =>
              update.mutate(
                { audit_weights: parsed, audit_instructions: instructions },
                { onSuccess: () => toast.show("Scoring settings saved. They apply to the next audit.", "ok"), onError: failed },
              )
            }
          >
            Save scoring settings
          </Button>
        </div>
      </fieldset>
    </section>
  );
}
