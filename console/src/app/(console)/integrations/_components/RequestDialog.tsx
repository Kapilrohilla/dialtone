"use client";

import { useState } from "react";
import { Button, Dialog, Field, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useRequestIntegration } from "@/lib/queries";
import styles from "../integrations.module.css";

export function RequestDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} title="Request an integration">
      <RequestForm onClose={onClose} />
    </Dialog>
  );
}

function RequestForm({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const request = useRequestIntegration();
  const [tool, setTool] = useState("");
  const [note, setNote] = useState("");
  const fields = request.error instanceof ApiError ? request.error.fields : {};
  const general = request.error instanceof ApiError ? (Object.keys(fields).length ? null : request.error.detail) : request.isError ? "Couldn't reach the server. Try again." : null;

  return (
    <form
      className={styles.form}
      onSubmit={(e) => {
        e.preventDefault();
        request.mutate(
          { tool: tool.trim(), note: note.trim() },
          {
            onSuccess: () => {
              toast.show("Request sent.", "ok");
              onClose();
            },
          },
        );
      }}
    >
      <Field label="Which tool?" value={tool} onChange={(e) => setTool(e.target.value)} maxLength={100} required error={fields.tool?.[0]} />
      <Field label="What should it do?" control="textarea" rows={4} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} error={fields.note?.[0]} />
      {general && <p role="alert" className={styles.note}>{general}</p>}
      <div className={styles.footer}>
        <Button onClick={onClose}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={tool.trim() === ""} loading={request.isPending}>
          Send request
        </Button>
      </div>
    </form>
  );
}
