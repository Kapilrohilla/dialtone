"use client";

import { useState } from "react";
import { Button, Dialog, Field, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useChangePassword } from "@/lib/queries";
import styles from "../settings.module.css";

export function PasswordDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} title="Change password">
      <PasswordForm onClose={onClose} />
    </Dialog>
  );
}

// The footer lives outside the body in Dialog, so the buttons sit inside the form here instead.
function PasswordForm({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [mismatch, setMismatch] = useState(false);
  const fields = change.error instanceof ApiError ? change.error.fields : {};
  const general = change.error instanceof ApiError ? (Object.keys(fields).length ? null : change.error.detail) : change.isError ? "Couldn't reach the server. Try again." : null;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next !== confirm) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          toast.show("Password changed.", "ok");
          onClose();
        },
      },
    );
  }

  return (
    <form className={styles.form} onSubmit={submit}>
      <Field label="Current password" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} error={fields.current_password?.[0]} required />
      <Field label="New password" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} error={fields.new_password?.[0]} required />
      <Field
        label="Confirm new password"
        type="password"
        autoComplete="new-password"
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
        error={mismatch ? "The two passwords do not match." : null}
        required
      />
      {general && <p role="alert" className={styles.note}>{general}</p>}
      <div className={styles.footer} style={{ padding: 0 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button type="submit" variant="primary" loading={change.isPending}>
          Change password
        </Button>
      </div>
    </form>
  );
}
