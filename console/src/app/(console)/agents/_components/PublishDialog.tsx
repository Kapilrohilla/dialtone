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
};

export function PublishDialog({ agent, liveAgent, onClose, onPublished }: PublishDialogProps) {
  const publish = usePublish();
  const replaced = liveAgent && agent && liveAgent.id !== agent.id ? liveAgent : null;
  const errors = publish.error instanceof ApiError ? (publish.error.fields.errors ?? [publish.error.detail]) : [];

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
      {errors.length > 0 && (
        <div role="alert" className={styles.errors}>
          <p className={styles.errorsTitle}>Fix these first:</p>
          <ul>
            {errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}
    </Dialog>
  );
}
