"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button, Field } from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api";
import styles from "../../../sign-in/sign-in.module.css";

export default function SetPasswordPage() {
  const { uid, token } = useParams<{ uid: string; token: string }>();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await apiFetch<void>("/api/auth/set-password", { method: "POST", json: { uid, token, new_password: password } });
      setDone(true);
    } catch (err) {
      const first = err instanceof ApiError ? (err.fields.new_password?.[0] ?? err.detail) : "Something went wrong. Try again.";
      setError(first);
      setBusy(false);
    }
  }

  return (
    <main className={styles.page}>
      <section className={styles.panel}>
        <p className={styles.wordmark}>Carrum Voice</p>
        {done ? (
          <>
            <h1 className={styles.heading}>Password set.</h1>
            <Link href="/sign-in">Sign in</Link>
          </>
        ) : (
          <>
            <h1 className={styles.heading}>Set your password</h1>
            <form onSubmit={submit} className={styles.form}>
              <Field label="New password" type="password" autoComplete="new-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
              <Field label="Confirm password" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
              {error && <p role="alert" className={styles.error}>{error}</p>}
              <Button type="submit" variant="primary" loading={busy} className={styles.submit}>Set password</Button>
            </form>
          </>
        )}
      </section>
    </main>
  );
}
