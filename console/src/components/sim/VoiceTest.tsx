"use client";

import { ChevronDown, ExternalLink, PhoneOff, X } from "lucide-react";
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { Room, TextStreamReader } from "livekit-client";
import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useWebCall } from "@/lib/queries";
import styles from "./VoiceTest.module.css";

type Phase = "connecting" | "waiting" | "live" | "ended" | "failed";
type Line = { id: string; speaker: "you" | "agent"; text: string };
export type VoiceTestAgent = { id: number; name: string };
type LiveKit = typeof import("livekit-client");

/** What LiveKit voice agents publish as the `lk.agent.state` attribute. */
const AGENT_STATES: Record<string, string> = {
  initializing: "The agent is getting ready…",
  listening: "Listening",
  thinking: "Thinking…",
  speaking: "Speaking",
};

const TRANSCRIPTION_TOPIC = "lk.transcription";

function micError(e: unknown): string {
  const name = e instanceof Error ? e.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "The browser blocked the microphone. Allow it for this site and call again.";
  }
  if (name === "NotFoundError") return "No microphone was found.";
  return "The microphone couldn't be started.";
}

function elapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

const hasAgent = (r: Room) => [...r.remoteParticipants.values()].some((p) => p.isAgent);

type VoiceTestContext = {
  /** Calls `agent`'s draft. If that agent is already on a call, just opens the dock. */
  start: (agent: VoiceTestAgent) => void;
};

const Ctx = createContext<VoiceTestContext | null>(null);

export function useVoiceTest(): VoiceTestContext {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useVoiceTest needs a <VoiceTestProvider> above it.");
  return ctx;
}

/**
 * Talk to an agent's draft from the browser over WebRTC. No phone call, so no SIP minutes: the dashboard
 * hands out a LiveKit token whose room dispatches the voice agent, which runs the same pipeline as a real
 * call.
 *
 * The call lives here, in the console layout, not on the agent page: moving between console pages keeps it
 * going in a floating dock. It hangs up on Hang up, on closing the browser tab, or when the console itself
 * goes away (signing out).
 */
export function VoiceTestProvider({ children }: { children: ReactNode }) {
  const webCall = useWebCall();
  const [agent, setAgent] = useState<VoiceTestAgent | null>(null);
  const [phase, setPhase] = useState<Phase>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [agentState, setAgentState] = useState<string | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [muted, setMuted] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  /** When the agent joined, and the clock; a hidden tab throttles timers, so the time is worked out, not counted. */
  const [liveSince, setLiveSince] = useState<number | null>(null);
  const [now, setNow] = useState(0);
  const room = useRef<Room | null>(null);
  const lkRef = useRef<LiveKit | null>(null);
  const audio = useRef<HTMLDivElement>(null);
  /** Bumped per call (and on hang up), so events from an earlier call never touch the current one. */
  const run = useRef(0);
  /** False once unmounted, so a call that connects afterwards is hung up straight away. */
  const alive = useRef(true);
  const phaseRef = useRef<Phase>(phase);
  phaseRef.current = phase;
  const agentRef = useRef<VoiceTestAgent | null>(agent);
  agentRef.current = agent;

  function upsertLine(id: string, speaker: Line["speaker"], text: string) {
    setLines((cur) => {
      const at = cur.findIndex((l) => l.id === id);
      if (at === -1) return text ? [...cur, { id, speaker, text }] : cur;
      const next = cur.slice();
      next[at] = { id, speaker, text };
      return next;
    });
  }

  function goLive() {
    setPhase("live");
    const t = Date.now();
    setLiveSince((s) => s ?? t);
    setNow(t);
  }

  /** Ends the current call in the UI and drops our side of the room. */
  const endCall = useCallback(() => {
    run.current += 1;
    const r = room.current;
    room.current = null;
    void r?.disconnect();
    setReconnecting(false);
    setNow(Date.now());
    setPhase((p) => (p === "failed" ? p : "ended"));
    // An end you might not have seen (the dock was a pill): show it.
    setCollapsed(false);
  }, []);

  /** The room's real state, for when events may have been missed (a background tab, a reconnect). */
  const recheck = useCallback(() => {
    const r = room.current;
    const lk = lkRef.current;
    if (!r || !lk) return;
    if (r.state === lk.ConnectionState.Disconnected) endCall();
    else if (phaseRef.current === "live" && r.state === lk.ConnectionState.Connected && !hasAgent(r)) endCall();
  }, [endCall]);

  async function connect(target: VoiceTestAgent) {
    const at = ++run.current;
    const current = () => alive.current && at === run.current;
    setPhase("connecting");
    setError(null);
    setAgentState(null);
    setLines([]);
    setMuted(false);
    setReconnecting(false);
    setLiveSince(null);

    let access;
    try {
      access = await webCall.mutateAsync(target.id);
    } catch (e) {
      if (!current()) return;
      setError(e instanceof ApiError ? e.detail : "The voice test couldn't start.");
      setPhase("failed");
      return;
    }
    if (!current()) return;

    const lk = await import("livekit-client");
    lkRef.current = lk;
    if (!current()) return;
    const r = new lk.Room({
      adaptiveStream: false,
      audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    room.current = r;

    r.on(lk.RoomEvent.TrackSubscribed, (track) => {
      if (track.kind !== lk.Track.Kind.Audio) return;
      const el = track.attach();
      audio.current?.appendChild(el);
    });
    r.on(lk.RoomEvent.TrackUnsubscribed, (track) => {
      track.detach().forEach((el) => el.remove());
    });
    r.on(lk.RoomEvent.ParticipantConnected, (p) => {
      if (current() && p.isAgent) goLive();
    });
    // The agent hung up (or crashed): the call is over even if the room lingers.
    r.on(lk.RoomEvent.ParticipantDisconnected, (p) => {
      if (current() && p.isAgent) endCall();
    });
    r.on(lk.RoomEvent.ParticipantAttributesChanged, (changed, p) => {
      if (current() && p.isAgent && changed["lk.agent.state"]) setAgentState(changed["lk.agent.state"]);
    });
    r.on(lk.RoomEvent.Reconnecting, () => {
      if (current()) setReconnecting(true);
    });
    r.on(lk.RoomEvent.SignalReconnecting, () => {
      if (current()) setReconnecting(true);
    });
    r.on(lk.RoomEvent.Reconnected, () => {
      if (!current()) return;
      setReconnecting(false);
      recheck();
    });
    // Also what a failed reconnect ends in.
    r.on(lk.RoomEvent.Disconnected, () => {
      if (current()) endCall();
    });
    // The agent's and your speech as text, one stream per segment. A segment can be sent again (your
    // words while you're still speaking), so each new stream replaces that segment's text.
    r.registerTextStreamHandler(TRANSCRIPTION_TOPIC, async (reader: TextStreamReader, from) => {
      const id = reader.info.attributes?.["lk.segment_id"] ?? reader.info.id;
      const speaker: Line["speaker"] = from.identity === r.localParticipant.identity ? "you" : "agent";
      let text = "";
      for await (const chunk of reader) {
        if (!current()) return;
        text += chunk;
        upsertLine(id, speaker, text);
      }
    });

    try {
      await r.connect(access.url, access.token);
    } catch {
      if (!current()) return;
      room.current = null;
      setError(
        `Couldn't reach LiveKit at ${access.url}. If you use the console through \`make tunnel\`, restart it so it forwards port 7880.`,
      );
      setPhase("failed");
      return;
    }
    if (!current()) {
      void r.disconnect();
      return;
    }
    // Opened by a click, so the browser lets the agent's audio play.
    void r.startAudio();
    if (hasAgent(r)) goLive();
    else setPhase("waiting");
    try {
      await r.localParticipant.setMicrophoneEnabled(true);
    } catch (e) {
      if (!current()) return;
      setError(micError(e));
      setPhase("failed");
      endCall();
    }
  }

  const start = useCallback((target: VoiceTestAgent) => {
    const busy = phaseRef.current !== "ended" && phaseRef.current !== "failed";
    if (agentRef.current?.id === target.id && busy) {
      setCollapsed(false);
      return;
    }
    // Calling another agent replaces the call in progress.
    run.current += 1;
    void room.current?.disconnect();
    room.current = null;
    setAgent(target);
    setCollapsed(false);
    void connect(target);
    // connect only reads refs and stable setters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function toggleMute() {
    const r = room.current;
    if (!r) return;
    await r.localParticipant.setMicrophoneEnabled(muted);
    setMuted(!muted);
  }

  function close() {
    endCall();
    setAgent(null);
  }

  useEffect(() => {
    alive.current = true;
    // Closing or reloading the tab hangs up at once, rather than leaving the agent talking to nobody.
    const onPageHide = () => void room.current?.disconnect();
    // A background tab can miss the end of the call: look again when it's back.
    const onVisible = () => {
      if (document.visibilityState === "visible") recheck();
    };
    window.addEventListener("pagehide", onPageHide);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("pagehide", onPageHide);
      document.removeEventListener("visibilitychange", onVisible);
      alive.current = false;
      run.current += 1;
      void room.current?.disconnect();
      room.current = null;
    };
  }, [recheck]);

  useEffect(() => {
    if (phase !== "live") return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [phase]);

  const seconds = liveSince === null ? 0 : Math.max(0, Math.floor((now - liveSince) / 1000));
  const over = phase === "ended" || phase === "failed";
  const status =
    phase === "connecting" ? "Connecting…"
    : phase === "waiting" ? "Waiting for the agent to join…"
    : phase === "live" && reconnecting ? "Reconnecting…"
    : phase === "live" ? `${AGENT_STATES[agentState ?? ""] ?? "Connected"} · ${elapsed(seconds)}${muted ? " · Muted" : ""}`
    : null;

  return (
    <Ctx.Provider value={{ start }}>
      {children}
      {agent && collapsed && !over && (
        <div className={styles.pill} role="region" aria-label="Voice test">
          <button type="button" className={styles.pillOpen} onClick={() => setCollapsed(false)} aria-label="Open voice test">
            <span className={styles.dot} data-reconnecting={reconnecting || undefined} aria-hidden="true" />
            <span className="mono">{phase === "live" ? elapsed(seconds) : "…"}</span>
          </button>
          <button type="button" className={styles.pillHangUp} onClick={endCall} aria-label="Hang up">
            <PhoneOff size={16} strokeWidth={2} aria-hidden="true" />
          </button>
        </div>
      )}
      {agent && !(collapsed && !over) && (
        <section className={styles.dock} role="region" aria-label="Voice test">
          <header className={styles.header}>
            <div className={styles.title}>
              <span className={styles.kicker}>Voice test</span>
              <span className={styles.name}>{agent.name}</span>
            </div>
            <Link href={`/agents/${agent.id}`} className={styles.open}>
              Open agent
              <ExternalLink size={14} strokeWidth={1.75} aria-hidden="true" />
            </Link>
            {over ? (
              <button type="button" className={styles.icon} onClick={close} aria-label="Close">
                <X size={18} strokeWidth={1.75} aria-hidden="true" />
              </button>
            ) : (
              <button type="button" className={styles.icon} onClick={() => setCollapsed(true)} aria-label="Collapse">
                <ChevronDown size={18} strokeWidth={1.75} aria-hidden="true" />
              </button>
            )}
          </header>
          <div className={styles.body}>
            {status && (
              <div className={styles.statusRow}>
                <span
                  className={styles.meter}
                  data-active={(phase === "live" && !reconnecting && agentState === "speaking") || undefined}
                  aria-hidden="true"
                >
                  <span />
                  <span />
                  <span />
                  <span />
                  <span />
                </span>
                <p className={styles.status} aria-live="polite">{status}</p>
              </div>
            )}
            {phase === "ended" && <p className={styles.endedText}>The call ended.</p>}
            {phase === "failed" && <p className={styles.endedText}>The call didn&apos;t start.</p>}
            {error && <p role="alert" className={styles.error}>{error}</p>}
            {lines.length > 0 && (
              <div role="log" aria-label="Conversation" aria-live="polite" className={styles.log}>
                {lines.slice(-2).map((l) => (
                  <p key={l.id} className={styles.line}>
                    <span className={l.speaker === "you" ? styles.you : styles.agent}>{l.speaker === "you" ? "You" : "Agent"}</span>{" "}
                    {l.text}
                  </p>
                ))}
              </div>
            )}
          </div>
          <footer className={styles.footer}>
            {over ? (
              <Button size="sm" onClick={() => void connect(agent)}>Call again</Button>
            ) : (
              <>
                <Button size="sm" onClick={() => void toggleMute()} disabled={phase === "connecting"} aria-pressed={muted}>
                  {muted ? "Unmute" : "Mute"}
                </Button>
                <Button size="sm" variant="danger" onClick={endCall}>Hang up</Button>
              </>
            )}
          </footer>
        </section>
      )}
      <div ref={audio} hidden />
    </Ctx.Provider>
  );
}
