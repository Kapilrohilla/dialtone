"use client";

import Link from "next/link";
import { useState } from "react";
import { Transcript } from "@/components/Transcript";
import { Button, Dialog } from "@/components/ui";
import { cx } from "@/components/ui/util";
import { formatElapsed, formatPhone } from "@/lib/format";
import { useEndCall, useTransfer } from "@/lib/queries";
import type { LiveCall } from "@/lib/types";
import { Details } from "./Details";
import { StepLine } from "./StepLine";
import styles from "../live.module.css";

export type LiveCallViewProps = {
  call: LiveCall;
  /** The clock the timer reads; for an ended call, the moment it was last seen live. */
  now: Date;
  ended: boolean;
  /** Viewers read along; only editors and above can transfer or end. */
  canAct: boolean;
};

export function LiveCallView({ call, now, ended, canAct }: LiveCallViewProps) {
  const [confirm, setConfirm] = useState<"transfer" | "end" | null>(null);
  const transfer = useTransfer();
  const end = useEndCall();
  const busy = transfer.isPending || end.isPending;

  function run(action: "transfer" | "end") {
    setConfirm(null);
    (action === "transfer" ? transfer : end).mutate(call.room);
  }

  return (
    <div className={cx(styles.main, ended && styles.ended)}>
      {ended && (
        <p className={styles.endedNote}>
          This call has ended.
          <Link href={`/calls?room=${encodeURIComponent(call.room)}`}>Open in call history</Link>
        </p>
      )}
      <div className={styles.header}>
        <div className={styles.who}>
          <h2 className={`${styles.headPhone} mono`}>{formatPhone(call.caller)}</h2>
          <span className={styles.headCity}>{call.city || "—"}</span>
          <span className={`${styles.timer} mono`} aria-label="Call length">{formatElapsed(call.started_at, now)}</span>
        </div>
        {canAct && !ended && (
          <div className={styles.actions}>
            <Button loading={transfer.isPending} disabled={busy} onClick={() => setConfirm("transfer")}>Transfer to a telecaller</Button>
            <Button variant="danger" loading={end.isPending} disabled={busy} onClick={() => setConfirm("end")}>End call</Button>
          </div>
        )}
      </div>
      <StepLine steps={call.step_path} />
      <Transcript lines={call.transcript_tail} label="Live transcript" empty="Nothing has been said yet." className={styles.transcript} />
      <Details captured={call.captured} />

      <Dialog
        open={confirm === "transfer"}
        onClose={() => setConfirm(null)}
        title="Transfer call"
        footer={
          <>
            <Button onClick={() => setConfirm(null)}>Cancel</Button>
            <Button variant="primary" onClick={() => run("transfer")}>Transfer</Button>
          </>
        }
      >
        <p className={styles.dialogText}>Transfer this caller to the telecalling team?</p>
      </Dialog>
      <Dialog
        open={confirm === "end"}
        onClose={() => setConfirm(null)}
        title="End call"
        footer={
          <>
            <Button onClick={() => setConfirm(null)}>Keep call</Button>
            <Button variant="danger" onClick={() => run("end")}>End call</Button>
          </>
        }
      >
        <p className={styles.dialogText}>End this call now? The caller will be disconnected.</p>
      </Dialog>
    </div>
  );
}
