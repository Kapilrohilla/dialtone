"use client";

import { Eye, EyeOff } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { Button } from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api";
import { meKey, useLogoUrl, useProjectName } from "@/lib/queries";
import { safeNext } from "@/lib/safe-next";
import { applyAppearance } from "@/lib/theme";
import type { Me } from "@/lib/types";
import { useQueryClient } from "@tanstack/react-query";
import styles from "./sign-in.module.css";

function SignInForm() {
  const router = useRouter();
  const next = useSearchParams().get("next");
  const qc = useQueryClient();
  const projectName = useProjectName();
  const logoUrl = useLogoUrl();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [forgot, setForgot] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await apiFetch<Me>("/api/auth/login", { method: "POST", json: { email, password } });
      qc.setQueryData(meKey, me);
      applyAppearance(me.preferences.appearance);
      router.replace(safeNext(next));
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) setError("Too many attempts. Wait a minute and try again.");
      else setError(err instanceof ApiError ? err.detail : "Something went wrong. Try again.");
      setBusy(false);
    }
  }

  return (
    <main className={styles.page}>
      <section className={styles.panel}>
        <div className={styles.brand}>
          {/* eslint-disable-next-line @next/next/no-img-element -- a small same-origin file; next/image adds nothing here */}
          {logoUrl && <img src={logoUrl} alt="" className={styles.logo} />}
          <p className={styles.wordmark}>{projectName}</p>
        </div>
        <h1 className={styles.heading}>Sign in</h1>
        <form onSubmit={submit} className={styles.form}>
          <div className={styles.field}>
            <label htmlFor="email" className={styles.label}>Work email</label>
            <input id="email" type="email" className={styles.input} placeholder="name@company.com" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className={styles.field}>
            <div className={styles.labelRow}>
              <label htmlFor="password" className={styles.label}>Password</label>
              <button type="button" className={styles.link} aria-expanded={forgot} onClick={() => setForgot((v) => !v)}>Forgot password?</button>
            </div>
            <div className={styles.passwordWrap}>
              <input id="password" type={show ? "text" : "password"} className={styles.input} autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
              <button type="button" className={styles.eye} aria-label={show ? "Hide password" : "Show password"} aria-pressed={show} onClick={() => setShow((v) => !v)}>
                {show ? <EyeOff size={20} strokeWidth={1.75} aria-hidden="true" /> : <Eye size={20} strokeWidth={1.75} aria-hidden="true" />}
              </button>
            </div>
            {forgot && <p className={styles.muted}>Ask your workspace admin for a new invite link.</p>}
          </div>
          {error && <p role="alert" className={styles.error}>{error}</p>}
          <Button type="submit" variant="primary" loading={busy} className={styles.submit}>Sign in</Button>
        </form>
      </section>
      <p className={styles.footer}>No account? Ask your workspace admin for an invite.</p>
    </main>
  );
}

export default function SignInPage() {
  return (
    <Suspense>
      <SignInForm />
    </Suspense>
  );
}
