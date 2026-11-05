"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, isSignedOut } from "@/lib/api";
import { useUpdateAgent, type AgentUpdate } from "@/lib/queries";
import type { Agent, ScriptSection } from "@/lib/types";
import { useToast } from "@/components/ui";
import { useAutosave } from "@/lib/useAutosave";

/** Field saves outside the script. Each failure is kept per group (a control or set of controls) until that
 *  group saves successfully, so a later save elsewhere never hides it. */
export type FieldSave = { saving: boolean; saved: boolean; errors: Record<string, ApiError> };

/** The dead-air timings group; its error is shown under the timings. */
export const TIMINGS_GROUP = "timings";

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

/** The group a field save belongs to when none is named: the fields sent. */
export const groupOf = (body: AgentUpdate) => Object.keys(body).sort().join("+");

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
  const [errors, setErrors] = useState<Record<string, ApiError>>({});
  const [saving, setSaving] = useState(0);
  const [saved, setSaved] = useState(false);
  /** The errors as of now, for flushAll right after awaiting the saves in flight. */
  const errorsRef = useRef(errors);
  const customRef = useRef(custom);
  const toast = useToast();
  const [restorable, setRestorable] = useState<ScriptSection[] | null>(null);
  const initial = useRef(sections);
  const latest = useRef(sections);
  const pending = useRef(new Set<Promise<unknown>>());
  /** Each group's last save: the next one in the same group waits for it, so saves land in the order made. */
  const chains = useRef(new Map<string, Promise<unknown>>());

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

  const setGroupError = useCallback((group: string, error: ApiError | null) => {
    const next = { ...errorsRef.current };
    if (error) next[group] = error;
    else delete next[group];
    errorsRef.current = next;
    setErrors(next);
  }, []);

  const track = useCallback(async <T,>(request: Promise<T>): Promise<T> => {
    pending.current.add(request);
    setSaving((n) => n + 1);
    try {
      return await request;
    } finally {
      pending.current.delete(request);
      setSaving((n) => n - 1);
    }
  }, []);

  /** PATCHes `body` after the group's earlier save has finished. `group` names what the error belongs to;
   *  it defaults to the fields sent. */
  const saveFields = useCallback(
    async (body: AgentUpdate, group: string = groupOf(body)): Promise<boolean> => {
      const request = (chains.current.get(group) ?? Promise.resolve()).then(() => mutateAsync(body));
      const settled = request.catch(() => undefined);
      chains.current.set(group, settled);
      void settled.then(() => {
        if (chains.current.get(group) === settled) chains.current.delete(group);
      });
      try {
        await track(request);
        setGroupError(group, null);
        setSaved(true);
        return true;
      } catch (e) {
        if (isSignedOut(e)) setSignedOut(true);
        setGroupError(group, asApiError(e));
        return false;
      }
    },
    [mutateAsync, track, setGroupError],
  );

  /** A check made before sending (e.g. whole seconds) blocks the group like a server error; null clears it. */
  const markInvalid = useCallback((group: string, message: string | null) => setGroupError(group, message ? new ApiError(0, message) : null), [setGroupError]);

  // Field values the server refused are still on screen: ask before the tab closes.
  useEffect(() => {
    if (Object.keys(errors).length === 0) return;
    function onBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [errors]);

  /** Saves the script now and waits for field saves in flight. Rejects when anything is unsaved. */
  const flushAll = useCallback(async () => {
    await flush();
    await Promise.allSettled([...pending.current]);
    const failed = Object.values(errorsRef.current)[0];
    if (failed) throw failed;
  }, [flush]);

  /** Saved on the agent first; the chip is inserted (resolves true) only once the server has it. */
  async function createExpression(name: string, hint: string): Promise<boolean> {
    const next = { ...customRef.current, [name]: hint };
    try {
      await track(mutateAsync({ custom_expressions: next }));
    } catch (e) {
      if (isSignedOut(e)) setSignedOut(true);
      toast.show(asApiError(e).detail, "bad");
      return false;
    }
    customRef.current = next;
    setCustom(next);
    return true;
  }

  function restore() {
    if (restorable) setSections(restorable);
    setRestorable(null);
  }

  function discard() {
    removeDraft(key);
    setRestorable(null);
  }

  const field: FieldSave = { saving: saving > 0, saved, errors };

  return { sections, setSections, custom, createExpression, autosave, field, saveFields, markInvalid, flushAll, signedOut, restorable, restore, discard };
}
