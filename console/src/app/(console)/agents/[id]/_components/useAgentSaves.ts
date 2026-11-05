"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, isSignedOut } from "@/lib/api";
import { useUpdateAgent, type AgentUpdate } from "@/lib/queries";
import type { Agent, ScriptSection } from "@/lib/types";
import { useAutosave, type AutosaveStatus } from "@/lib/useAutosave";

export type FieldSave = {
  status: AutosaveStatus;
  error?: ApiError;
  /** The error is shown next to its control (the dead-air timings), so the top bar only says it wasn't saved. */
  inline?: boolean;
};

const draftKey = (id: number) => `cv-draft-agent-${id}`;

function readDraft(key: string): ScriptSection[] | null {
  try {
    const raw = sessionStorage.getItem(key);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    return Array.isArray(parsed) ? (parsed as ScriptSection[]) : null;
  } catch {
    return null;
  }
}

function writeDraft(key: string, script: ScriptSection[]) {
  try {
    sessionStorage.setItem(key, JSON.stringify(script));
  } catch {
    // Storage full or blocked: the text is still on the page.
  }
}

function removeDraft(key: string) {
  try {
    sessionStorage.removeItem(key);
  } catch {
    // Nothing to clean up.
  }
}

const asApiError = (e: unknown) => (e instanceof ApiError ? e : new ApiError(0, "Could not save. Check your connection and try again."));

/**
 * The editor's saving: the script autosaves as a whole, every other field is PATCHed on its own when it is
 * committed. A signed-out error stops autosaving; the script stays on the page and in a sessionStorage draft.
 */
export function useAgentSaves(agent: Agent) {
  const { mutateAsync } = useUpdateAgent(agent.id, { signInRedirect: false });
  const key = draftKey(agent.id);
  const [sections, setSections] = useState<ScriptSection[]>(agent.script);
  const [custom, setCustom] = useState<Record<string, string>>(agent.custom_expressions);
  const [signedOut, setSignedOut] = useState(false);
  const [field, setField] = useState<FieldSave>({ status: "idle" });
  const [restorable, setRestorable] = useState<ScriptSection[] | null>(null);
  const initial = useRef(sections);
  const latest = useRef(sections);
  const pending = useRef(new Set<Promise<unknown>>());

  const saveScript = useCallback(
    async (script: ScriptSection[]) => {
      try {
        await mutateAsync({ script });
      } catch (e) {
        if (isSignedOut(e)) setSignedOut(true);
        throw asApiError(e);
      }
      if (script === latest.current) removeDraft(key);
    },
    [mutateAsync, key],
  );
  const autosave = useAutosave(sections, saveScript, 800, !signedOut);
  const { flush } = autosave;

  useEffect(() => {
    latest.current = sections;
    if (sections !== initial.current) writeDraft(key, sections);
  }, [sections, key]);

  // A draft left by an earlier visit (signed out, tab closed mid-save) is offered when it differs from the server.
  useEffect(() => {
    const stored = readDraft(key);
    if (!stored) return;
    if (JSON.stringify(stored) === JSON.stringify(initial.current)) removeDraft(key);
    else setRestorable(stored);
  }, [key]);

  const saveFields = useCallback(
    async (body: AgentUpdate): Promise<boolean> => {
      setField({ status: "saving" });
      const request = mutateAsync(body);
      pending.current.add(request);
      try {
        await request;
        setField({ status: "saved" });
        return true;
      } catch (e) {
        if (isSignedOut(e)) setSignedOut(true);
        const error = asApiError(e);
        setField({ status: "error", error, inline: "settings" in body && !!error.fields.settings });
        return false;
      } finally {
        pending.current.delete(request);
      }
    },
    [mutateAsync],
  );

  /** Saves the script now and waits for field saves in flight. Rejects when the script can't be saved. */
  const flushAll = useCallback(async () => {
    await flush();
    await Promise.allSettled([...pending.current]);
  }, [flush]);

  function createExpression(name: string, hint: string) {
    const next = { ...custom, [name]: hint };
    setCustom(next);
    void saveFields({ custom_expressions: next });
  }

  function restore() {
    if (restorable) setSections(restorable);
    setRestorable(null);
  }

  function discard() {
    removeDraft(key);
    setRestorable(null);
  }

  return { sections, setSections, custom, createExpression, autosave, field, saveFields, flushAll, signedOut, restorable, restore, discard };
}
