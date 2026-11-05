"use client";

import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ChipText } from "@/components/editor/ChipText";
import { Button, Chip, SlideOver } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { DISPOSITIONS, outcomeTone } from "@/lib/outcomes";
import { useSimulate, type SimMessage, type SimRequest } from "@/lib/queries";
import type { SimResponse } from "@/lib/types";
import styles from "./Simulator.module.css";

export type SimulatorProps = {
  /** "agent": the agent's current draft (Test call). "workflow": the workflow on its own (Try it). */
  kind: "agent" | "workflow";
  id: number;
  /** Defaults to "Test call" for an agent and "Try it" for a workflow. */
  title?: string;
  /** The agent's custom expressions, so their chips get the custom tint rather than the unknown one. */
  customExpressions?: Record<string, string>;
  onClose: () => void;
};

const MAX_TEXT = 2000;
const OPENING: SimRequest = { messages: [], state: null };

function outcomeOf(outcome: SimResponse["outcome"]) {
  const code = outcome && typeof outcome.disposition === "string" ? outcome.disposition : null;
  return DISPOSITIONS.find((d) => d.code === code) ?? null;
}

/** A text conversation with the agent or workflow in a slide-over. Mount it to open; it asks for the opening line. */
export function Simulator({ kind, id, title, customExpressions, onClose }: SimulatorProps) {
  const sim = useSimulate(kind, id);
  const inputId = useId();
  const [turns, setTurns] = useState<SimMessage[]>([]);
  const [state, setState] = useState<SimResponse["state"] | null>(null);
  const [step, setStep] = useState<SimResponse["step"]>(null);
  const [ended, setEnded] = useState<{ outcome: ReturnType<typeof outcomeOf> } | null>(null);
  const [text, setText] = useState("");
  const [failed, setFailed] = useState<{ message: string; request: SimRequest; typed?: string } | null>(null);
  /** Bumped by "Start again" so a reply to the previous conversation is dropped. */
  const run = useRef(0);
  const started = useRef(false);

  /** `typed`: the input text this request sends, cleared from the input once the reply arrives. */
  function send(request: SimRequest, typed?: string) {
    const at = run.current;
    setFailed(null);
    sim.mutate(request, {
      onSuccess: (r) => {
        if (at !== run.current) return;
        setTurns(r.reply ? [...request.messages, { role: "agent", text: r.reply }] : request.messages);
        setState(r.state);
        setStep(r.step);
        // Only what was sent: anything typed while waiting stays.
        if (typed !== undefined) setText((now) => (now.startsWith(typed) ? now.slice(typed.length).replace(/^\s+/, "") : now));
        if (r.ended) setEnded({ outcome: outcomeOf(r.outcome) });
      },
      onError: (e) => {
        if (at !== run.current) return;
        setFailed({ message: e instanceof ApiError ? e.detail : "The test simulator failed.", request, typed });
      },
    });
  }

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    send(OPENING);
    // Once per mount: the opening line.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function startAgain() {
    run.current += 1;
    setTurns([]);
    setState(null);
    setStep(null);
    setEnded(null);
    setText("");
    send(OPENING);
  }

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const said = text.trim();
    if (!said || sim.isPending) return;
    send({ messages: [...turns, { role: "caller", text: said }], state }, text);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  const composer = ended ? (
    <div className={styles.ended}>
      <p className={styles.endedText}>
        The call ended.
        {ended.outcome && <Chip tone={outcomeTone(ended.outcome.group)}>{ended.outcome.label}</Chip>}
      </p>
      <Button onClick={startAgain}>Start again</Button>
    </div>
  ) : (
    <form className={styles.composer} onSubmit={submit}>
      {failed && (
        <div role="alert" className={styles.error}>
          <span>{failed.message}</span>
          <Button size="sm" variant="text" onClick={() => send(failed.request, failed.typed)}>Try again</Button>
        </div>
      )}
      <label htmlFor={inputId} className={styles.srOnly}>Your reply</label>
      <textarea
        id={inputId}
        className={styles.input}
        rows={2}
        maxLength={MAX_TEXT}
        value={text}
        placeholder="Type what the caller says"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
      />
      <div className={styles.composerRow}>
        <span className={styles.hint}>Enter sends, Shift+Enter starts a new line.</span>
        <Button type="submit" loading={sim.isPending} disabled={!text.trim()}>Send</Button>
      </div>
    </form>
  );

  return (
    <SlideOver open onClose={onClose} title={title ?? (kind === "agent" ? "Test call" : "Try it")} footer={composer}>
      <p className={styles.note}>Type as the caller. Nothing is saved and nobody is called.</p>
      {step && <p className={styles.step}>Step: {step.name}</p>}
      <div role="log" aria-label="Conversation" aria-live="polite" className={styles.log}>
        {turns.map((t, i) => (
          <div key={i} className={styles.turn}>
            <span className={t.role === "caller" ? styles.caller : styles.agent}>{t.role === "caller" ? "Caller" : "Agent"}</span>
            <p className={styles.text}>{t.role === "agent" ? <ChipText text={t.text} customExpressions={customExpressions} /> : t.text}</p>
          </div>
        ))}
        {sim.isPending && <p className={styles.waiting}>{turns.length ? "The agent is replying…" : "Calling…"}</p>}
      </div>
    </SlideOver>
  );
}
