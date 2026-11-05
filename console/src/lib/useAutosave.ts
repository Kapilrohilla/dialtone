"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiError } from "@/lib/api";

export type AutosaveStatus = "idle" | "saving" | "saved" | "error";

export type Autosave = {
  status: AutosaveStatus;
  /** The last failed save's error, until a later save succeeds. */
  error?: ApiError;
  /** Saves any unsaved value now. Resolves when everything is saved; rejects with the error if a save fails. */
  flush: () => Promise<void>;
};

/**
 * Saves `value` `delayMs` after it last changed (compared with Object.is; the first value counts as saved).
 * One save is in flight at a time: a change made while saving is saved right after. `enabled: false` stops
 * scheduling saves (flush still saves).
 */
export function useAutosave<T>(value: T, save: (v: T) => Promise<unknown>, delayMs = 800, enabled = true): Autosave {
  const [status, setStatus] = useState<AutosaveStatus>("idle");
  const [error, setError] = useState<ApiError | undefined>();
  const latest = useRef(value);
  const saved = useRef(value);
  const saveRef = useRef(save);
  const running = useRef<Promise<void> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    saveRef.current = save;
  }, [save]);

  const run = useCallback((): Promise<void> => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    // The save in flight picks up whatever changed meanwhile before it settles.
    if (running.current) return running.current;
    if (Object.is(latest.current, saved.current)) return Promise.resolve();
    const loop = async () => {
      try {
        while (!Object.is(latest.current, saved.current)) {
          const v = latest.current;
          setStatus("saving");
          try {
            await saveRef.current(v);
          } catch (e) {
            setStatus("error");
            setError(e as ApiError);
            throw e;
          }
          saved.current = v;
        }
        setStatus("saved");
        setError(undefined);
      } finally {
        running.current = null;
      }
    };
    running.current = loop();
    return running.current;
  }, []);

  useEffect(() => {
    latest.current = value;
    if (!enabled || Object.is(value, saved.current)) return;
    timer.current = setTimeout(() => {
      timer.current = null;
      run().catch(() => {
        // Shown through `status` and `error`.
      });
    }, delayMs);
    return () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
    };
  }, [value, enabled, delayMs, run]);

  return { status, error, flush: run };
}
