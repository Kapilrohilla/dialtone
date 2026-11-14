"use client";

import { useEffect, useState, type KeyboardEvent } from "react";
import { Button, Field } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { AREA_LABELS } from "@/lib/audit";
import { useCallFeedback, useSaveCallFeedback } from "@/lib/queries";
import type { AuditAreaKey, CallFeedbackInput } from "@/lib/types";
import styles from "./RateCall.module.css";

const SCORES = [1, 2, 3, 4, 5] as const;
const MAX_REMARKS = 2000;

/** 1–5 as a radio group; choosing the selected score again clears it (an area can stay unrated). */
export function ScoreRow({ label, value, onChange }: { label: string; value: number | null; onChange: (v: number | null) => void }) {
  function onKeyDown(e: KeyboardEvent, score: number) {
    const step = e.key === "ArrowRight" || e.key === "ArrowUp" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowDown" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = Math.min(5, Math.max(1, score + step));
    onChange(next);
    (e.currentTarget.parentElement?.children[next - 1] as HTMLElement | undefined)?.focus();
  }
  return (
    <div className={styles.row}>
      <span className={styles.label}>{label}</span>
      <div role="radiogroup" aria-label={label} className={styles.scores}>
        {SCORES.map((s) => (
          <button
            key={s}
            type="button"
            role="radio"
            aria-checked={value === s}
            aria-label={`${s} of 5`}
            tabIndex={value === s || (value == null && s === 1) ? 0 : -1}
            className={styles.score}
            onClick={() => onChange(value === s ? null : s)}
            onKeyDown={(e) => onKeyDown(e, s)}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

const empty = (): CallFeedbackInput => ({ ratings: {}, overall: null, remarks: "" });

/**
 * Your own rating of a call: 1–5 on each audit area and overall, plus remarks. Starts from your saved rating,
 * if any; saving again replaces it.
 */
export function RateCall({ room, onSaved }: { room: string; onSaved?: () => void }) {
  const { data: all, isError: loadFailed } = useCallFeedback(room);
  const save = useSaveCallFeedback(room);
  const mine = all?.find((f) => f.mine);
  const [form, setForm] = useState<CallFeedbackInput>(empty);
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load your saved rating once, unless you've already started rating.
  useEffect(() => {
    if (mine && !touched) setForm({ ratings: { ...mine.ratings }, overall: mine.overall, remarks: mine.remarks });
  }, [mine, touched]);

  function edit(next: Partial<CallFeedbackInput>) {
    setTouched(true);
    setError(null);
    setForm((f) => ({ ...f, ...next }));
  }

  function setArea(key: AuditAreaKey, v: number | null) {
    const ratings = { ...form.ratings };
    if (v == null) delete ratings[key];
    else ratings[key] = v;
    edit({ ratings });
  }

  const blank = Object.keys(form.ratings).length === 0 && form.overall == null && !form.remarks.trim();

  async function submit() {
    try {
      await save.mutateAsync({ ...form, remarks: form.remarks.trim() });
      setTouched(false);
      onSaved?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Couldn't save your rating.");
    }
  }

  return (
    <form
      className={styles.form}
      aria-label="Rate this call"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <ScoreRow label="Overall" value={form.overall} onChange={(v) => edit({ overall: v })} />
      {AREA_LABELS.map(([key, label]) => (
        <ScoreRow key={key} label={label} value={form.ratings[key] ?? null} onChange={(v) => setArea(key, v)} />
      ))}
      <Field
        control="textarea"
        label="Remarks"
        rows={3}
        maxLength={MAX_REMARKS}
        placeholder="What felt off? e.g. cut in while I gave my number, long pause after my question"
        value={form.remarks}
        onChange={(e) => edit({ remarks: e.target.value })}
      />
      {loadFailed && <p className={styles.note}>Your earlier rating couldn&apos;t be loaded.</p>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
      <div className={styles.actions}>
        {save.isSuccess && !touched && <span className={styles.saved} role="status">Saved</span>}
        <Button type="submit" size="sm" variant="primary" loading={save.isPending} disabled={blank}>
          {mine ? "Update rating" : "Save rating"}
        </Button>
      </div>
    </form>
  );
}
