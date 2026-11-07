"use client";

import { Panel, StateBlock, Switch, useToast } from "@/components/ui";
import { TopBar } from "@/components/shell/TopBar";
import { ApiError } from "@/lib/api";
import { useMe, useUpdateWorkspace } from "@/lib/queries";
import { canManageTeam } from "@/lib/roles";
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
