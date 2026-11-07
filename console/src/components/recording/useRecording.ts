"use client";

import { useCallback, useEffect, useRef, useState, type SyntheticEvent } from "react";
import { decodePeaks, placeholderPeaks } from "@/lib/recording";

/** What the call table shows for the open call's recording. */
export type PlaybackState = "loading" | "playing" | "paused" | "error";

export type UseRecordingOptions = {
  /** Shapes the stand-in waveform until (or unless) the real one is decoded. */
  seed: string;
  /** From the API, so the total shows while the file loads. */
  duration: number | null;
  /** Start playing as soon as the file is ready (the table's play button opened this call). */
  autoplay?: boolean;
};

/**
 * Loads a recording once, through the signed-in session, and drives a hidden <audio> with it.
 * Fetching the file up front gives a real loading and error state (a bare <audio> fails silently)
 * and lets the browser draw the real waveform. Recordings are small: about 240 KB a minute.
 */
export function useRecording(url: string | null, { seed, duration: knownDuration, autoplay = false }: UseRecordingOptions) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const wantPlay = useRef(autoplay);
  const [attempt, setAttempt] = useState(0);
  const [src, setSrc] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [peaks, setPeaks] = useState<number[]>(() => placeholderPeaks(seed));
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [mediaDuration, setMediaDuration] = useState<number | null>(null);
  const [rate, setRateState] = useState(1);
  const [volume, setVolumeState] = useState(1);
  const [muted, setMuted] = useState(false);

  useEffect(() => {
    if (!url) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    setSrc(null);
    setLoadFailed(false);
    (async () => {
      try {
        const res = await fetch(url, { credentials: "same-origin" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setSrc(objectUrl);
        const decoded = await decodePeaks(await blob.arrayBuffer());
        if (!cancelled && decoded) setPeaks(decoded);
      } catch {
        if (!cancelled) setLoadFailed(true);
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url, attempt]);

  // A removed <audio> can keep playing: stop it when the slide-over closes or another call opens.
  useEffect(() => () => audio.current?.pause(), []);

  // timeupdate fires only a few times a second; follow the frame while playing so the playhead glides.
  useEffect(() => {
    if (!playing || typeof requestAnimationFrame !== "function") return;
    let id = 0;
    const tick = () => {
      if (audio.current) setTime(audio.current.currentTime);
      id = requestAnimationFrame(tick);
    };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [playing]);

  const duration = mediaDuration ?? knownDuration;
  const status: "loading" | "ready" | "error" = loadFailed ? "error" : src ? "ready" : "loading";
  const state: PlaybackState = status === "ready" ? (playing ? "playing" : "paused") : status;

  const play = useCallback(() => {
    const el = audio.current;
    if (!el || !el.src) {
      wantPlay.current = true;
      return;
    }
    // Browsers can refuse to start (autoplay rules): stay paused and let the button try again.
    Promise.resolve(el.play()).catch(() => setPlaying(false));
  }, []);

  const pause = useCallback(() => {
    wantPlay.current = false;
    audio.current?.pause();
  }, []);

  const seek = useCallback(
    (to: number) => {
      const el = audio.current;
      const end = duration ?? Number.POSITIVE_INFINITY;
      const t = Math.min(Math.max(0, to), end);
      if (el) el.currentTime = t;
      setTime(t);
    },
    [duration],
  );

  const audioProps = {
    ref: audio,
    src: src ?? undefined,
    preload: "auto" as const,
    onLoadedMetadata: (e: SyntheticEvent<HTMLAudioElement>) => {
      const el = e.currentTarget;
      if (Number.isFinite(el.duration) && el.duration > 0) setMediaDuration(el.duration);
      el.playbackRate = rate;
      el.volume = volume;
      el.muted = muted;
      if (wantPlay.current) {
        wantPlay.current = false;
        play();
      }
    },
    onPlay: () => setPlaying(true),
    onPause: () => setPlaying(false),
    onEnded: () => setPlaying(false),
    onTimeUpdate: (e: SyntheticEvent<HTMLAudioElement>) => setTime(e.currentTarget.currentTime),
    onError: () => {
      if (src) setLoadFailed(true);
    },
  };

  return {
    audioProps,
    status,
    state,
    playing,
    time,
    duration,
    peaks,
    rate,
    volume,
    muted,
    play,
    pause,
    toggle: () => (playing ? pause() : play()),
    seek,
    /** Jumps there and plays: transcript turns and the table use it. */
    playFrom: (to: number) => {
      seek(to);
      play();
    },
    skip: (by: number) => seek((audio.current?.currentTime ?? time) + by),
    setRate: (next: number) => {
      setRateState(next);
      if (audio.current) audio.current.playbackRate = next;
    },
    setVolume: (next: number) => {
      setVolumeState(next);
      setMuted(next === 0);
      if (audio.current) {
        audio.current.volume = next;
        audio.current.muted = next === 0;
      }
    },
    toggleMute: () => {
      const next = !muted;
      setMuted(next);
      if (audio.current) audio.current.muted = next;
    },
    retry: () => {
      setMediaDuration(null);
      setAttempt((n) => n + 1);
    },
  };
}

export type Recording = ReturnType<typeof useRecording>;
