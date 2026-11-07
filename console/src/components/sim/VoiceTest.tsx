"use client";

import { useEffect, useRef, useState } from "react";
import type { Room, TextStreamReader } from "livekit-client";
import { Button, SlideOver } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useWebCall } from "@/lib/queries";
import styles from "./Simulator.module.css";

export type VoiceTestProps = {
  /** The agent whose draft answers. */
  agentId: number;
  onClose: () => void;
};

type Phase = "connecting" | "waiting" | "live" | "ended" | "failed";
type Line = { id: string; speaker: "you" | "agent"; text: string };

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

/**
 * Talk to the agent's draft from the browser over WebRTC. No phone call, so no SIP minutes: the dashboard
 * hands out a LiveKit token whose room dispatches the voice agent, which runs the same pipeline as a real
 * call. Mount it to start the call; unmounting hangs up.
 */
export function VoiceTest({ agentId, onClose }: VoiceTestProps) {
  const webCall = useWebCall(agentId);
  const [phase, setPhase] = useState<Phase>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [agentState, setAgentState] = useState<string | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [muted, setMuted] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const room = useRef<Room | null>(null);
  const audio = useRef<HTMLDivElement>(null);
  /** False once unmounted, so a call that connects afterwards is hung up straight away. */
  const alive = useRef(true);
  /** Bumped per call, so events from an earlier call never touch the current one. */
  const run = useRef(0);
  const started = useRef(false);

  function upsertLine(id: string, speaker: Line["speaker"], text: string) {
    setLines((now) => {
      const at = now.findIndex((l) => l.id === id);
      if (at === -1) return text ? [...now, { id, speaker, text }] : now;
      const next = now.slice();
      next[at] = { id, speaker, text };
      return next;
    });
  }

  async function start() {
    const at = ++run.current;
    const current = () => alive.current && at === run.current;
    setPhase("connecting");
    setError(null);
    setAgentState(null);
    setLines([]);
    setMuted(false);
    setSeconds(0);

    let access;
    try {
      access = await webCall.mutateAsync();
    } catch (e) {
      if (!current()) return;
      setError(e instanceof ApiError ? e.detail : "The voice test couldn't start.");
      setPhase("failed");
      return;
    }
    if (!current()) return;

    const lk = await import("livekit-client");
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
      if (current() && p.isAgent) setPhase("live");
    });
    r.on(lk.RoomEvent.ParticipantAttributesChanged, (changed, p) => {
      if (current() && p.isAgent && changed["lk.agent.state"]) setAgentState(changed["lk.agent.state"]);
    });
    r.on(lk.RoomEvent.Disconnected, () => {
      if (current()) setPhase((p) => (p === "failed" ? p : "ended"));
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
    setPhase([...r.remoteParticipants.values()].some((p) => p.isAgent) ? "live" : "waiting");
    try {
      await r.localParticipant.setMicrophoneEnabled(true);
    } catch (e) {
      if (!current()) return;
      setError(micError(e));
      setPhase("failed");
      void r.disconnect();
    }
  }

  function hangUp() {
    run.current += 1;
    void room.current?.disconnect();
    room.current = null;
    setPhase("ended");
  }

  async function toggleMute() {
    const r = room.current;
    if (!r) return;
    await r.localParticipant.setMicrophoneEnabled(muted);
    setMuted(!muted);
  }

  useEffect(() => {
    alive.current = true;
    if (!started.current) {
      started.current = true;
      void start();
    }
    return () => {
      alive.current = false;
      void room.current?.disconnect();
      room.current = null;
    };
    // Once per mount: the call.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (phase !== "live") return;
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, [phase]);

  function callAgain() {
    void start();
  }

  const status =
    phase === "connecting" ? "Connecting…"
    : phase === "waiting" ? "Waiting for the agent to join…"
    : phase === "live" ? `${AGENT_STATES[agentState ?? ""] ?? "Connected"} · ${elapsed(seconds)}${muted ? " · Muted" : ""}`
    : null;

  const footer =
    phase === "ended" || phase === "failed" ? (
      <div className={styles.ended}>
        <span className={styles.endedText}>{phase === "ended" ? "The call ended." : "The call didn't start."}</span>
        <Button onClick={callAgain}>Call again</Button>
      </div>
    ) : (
      <div className={styles.composerRow}>
        <Button onClick={() => void toggleMute()} disabled={phase === "connecting"} aria-pressed={muted}>
          {muted ? "Unmute" : "Mute"}
        </Button>
        <Button variant="danger" onClick={hangUp}>Hang up</Button>
      </div>
    );

  return (
    <SlideOver open onClose={onClose} title="Voice test" footer={footer}>
      <p className={styles.note}>
        Talk to the draft through your microphone, like a phone call but in the browser. No phone number is
        called, so no call minutes are used. The call is listed in call history as a web test.
      </p>
      {status && <p className={styles.step} aria-live="polite">{status}</p>}
      {error && <p role="alert" className={styles.error}>{error}</p>}
      <div role="log" aria-label="Conversation" aria-live="polite" className={styles.log}>
        {lines.map((l) => (
          <div key={l.id} className={styles.turn}>
            <span className={l.speaker === "you" ? styles.caller : styles.agent}>{l.speaker === "you" ? "You" : "Agent"}</span>
            <p className={styles.text}>{l.text}</p>
          </div>
        ))}
      </div>
      <div ref={audio} hidden />
    </SlideOver>
  );
}
