"use client";

import { Button, Dialog } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { usePublish } from "@/lib/queries";
import styles from "./agents.module.css";

export type PublishDialogProps = {
  /** The agent being published; null keeps the dialog closed. */
  agent: { id: number; name: string } | null;
  /** The agent answering calls right now, if any. It stops when `agent` is published. */
  liveAgent?: { id: number; name: string } | null;
  onClose: () => void;
  onPublished?: () => void;
  /** Something worth checking that doesn't block publishing, e.g. a voice that doesn't match the agent's gender. */
  warning?: string | null;
};

export function PublishDialog({ agent, liveAgent, onClose, onPublished, warning }: PublishDialogProps) {
  const publish = usePublish();
  const replaced = liveAgent && agent && liveAgent.id !== agent.id ? liveAgent : null;
  const failure = publish.error;
  const listed = failure instanceof ApiError ? (failure.fields.errors ?? []) : [];
  const message = !failure || listed.length > 0 ? null : failure instanceof ApiError ? failure.detail : "Could not publish. Try again.";

  function close() {
    publish.reset();
    onClose();
  }

  function confirm() {
    if (!agent) return;
    publish.mutate(agent.id, {
      onSuccess: () => {
        onPublished?.();
        close();
      },
    });
  }

  return (
    <Dialog
      open={agent !== null}
      onClose={close}
      title={agent ? `Publish ${agent.name}?` : "Publish"}
      footer={
        <>
          <Button onClick={close}>Cancel</Button>
          <Button variant="primary" loading={publish.isPending} onClick={confirm}>Publish</Button>
        </>
      }
    >
      <p className={styles.dialogText}>
        {replaced ? `${replaced.name} will stop answering calls.` : "It will answer the next call."}
      </p>
      {warning && <p className={styles.dialogText}>Check before publishing: {warning}</p>}
      {listed.length > 0 && (
        <div role="alert" className={styles.errors}>
          <p className={styles.errorsTitle}>Fix these first:</p>
          <ul>
            {listed.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}
      {message && (
        <p role="alert" className={styles.errors}>{message}</p>
      )}
    </Dialog>
  );
}
