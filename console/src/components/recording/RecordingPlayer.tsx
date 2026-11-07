"use client";

import { AudioLines, Check, ChevronDown, ChevronUp, Clock, Download, Link as LinkIcon, MicOff, Pause, Play, RotateCcw, RotateCw, Volume2, VolumeX } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { Button, Spinner } from "@/components/ui";
import { cx } from "@/components/ui/util";
import { KEY_SEEK_S, SKIP_S, SPEEDS, clock, speedLabel, type Segment } from "@/lib/recording";
import type { RecordingStatus } from "@/lib/types";
import type { Recording } from "./useRecording";
import styles from "./RecordingPlayer.module.css";

export type RecordingPlayerProps = {
  rec: Recording;
  /** Who spoke when, as fractions of the recording. */
  segments: Segment[];
  turns: number;
  /** The file, for the download button. */
  url: string;
  onCopyLink?: () => void;
};

/** The call's audio: waveform with playhead, who-spoke bar, play/skip, time, speed and volume. */
export function RecordingPlayer({ rec, segments, turns, url, onCopyLink }: RecordingPlayerProps) {
  const titleId = useId();

  if (rec.status === "error") {
    return (
      <section className={cx(styles.card, styles.notice)} aria-labelledby={titleId} role="alert">
        <audio {...rec.audioProps} aria-label="Call recording" hidden />
        <span className={cx(styles.noticeIcon, styles.bad)} aria-hidden="true">
          <AudioLines size={18} strokeWidth={1.75} />
        </span>
        <div className={styles.noticeText}>
          <h3 id={titleId} className={styles.noticeTitle}>Couldn&apos;t load this recording.</h3>
          <p className={styles.noticeBody}>Check your connection and try again.</p>
        </div>
        <Button size="sm" onClick={rec.retry}>Try again</Button>
      </section>
    );
  }

  const loading = rec.status === "loading";
  const duration = rec.duration ?? 0;
  const progress = duration > 0 ? Math.min(1, rec.time / duration) : 0;

  return (
    <section className={styles.card} aria-labelledby={titleId} aria-busy={loading || undefined}>
      <audio {...rec.audioProps} aria-label="Call recording" hidden />
      <header className={styles.header}>
        <h3 id={titleId} className={styles.title}>Call recording</h3>
        {loading ? (
          <span className={styles.loadingNote} role="status">
            <Spinner size={14} />
            Loading recording…
          </span>
        ) : (
          <>
            <span className={cx(styles.badge, rec.playing && styles.badgePlaying)}>
              {rec.playing && <AudioLines size={12} strokeWidth={2.25} aria-hidden="true" />}
              {rec.playing ? "Playing" : "Paused"}
            </span>
            <span className={styles.headerActions}>
              <a className={styles.iconButton} href={`${url}${url.includes("?") ? "&" : "?"}download=1`} download aria-label="Download recording" title="Download">
                <Download size={18} strokeWidth={1.75} aria-hidden="true" />
              </a>
              {onCopyLink && (
                <button type="button" className={styles.iconButton} aria-label="Copy link to this call" title="Copy link" onClick={onCopyLink}>
                  <LinkIcon size={18} strokeWidth={1.75} aria-hidden="true" />
                </button>
              )}
            </span>
          </>
        )}
      </header>

      <Waveform rec={rec} progress={progress} duration={duration} disabled={loading} />

      {segments.length > 0 && !loading && (
        <>
          <div className={styles.turnBar} aria-hidden="true">
            {segments.map((s, i) => (
              <span
                key={i}
                className={cx(styles.turn, s.speaker === "agent" ? styles.turnAgent : styles.turnCaller)}
                style={{ left: `${s.from * 100}%`, width: `${(s.to - s.from) * 100}%` }}
              />
            ))}
          </div>
          <div className={styles.legend}>
            <span className={styles.legendItem}><span className={cx(styles.dot, styles.turnCaller)} />Caller</span>
            <span className={styles.legendItem}><span className={cx(styles.dot, styles.turnAgent)} />Agent</span>
            <span className={styles.turns}>{turns} {turns === 1 ? "turn" : "turns"}</span>
          </div>
        </>
      )}

      <div className={styles.controls}>
        <button type="button" className={styles.skip} aria-label={`Back ${SKIP_S} seconds`} disabled={loading} onClick={() => rec.skip(-SKIP_S)}>
          <RotateCcw size={20} strokeWidth={1.75} aria-hidden="true" />
          <span className={styles.skipNum} aria-hidden="true">{SKIP_S}</span>
        </button>
        <button
          type="button"
          className={cx(styles.play, rec.playing && styles.playActive)}
          aria-label={loading ? "Loading recording" : rec.playing ? "Pause" : "Play"}
          disabled={loading}
          onClick={rec.toggle}
        >
          {loading ? <Spinner size={20} /> : rec.playing ? <Pause size={20} strokeWidth={2} aria-hidden="true" /> : <Play size={20} strokeWidth={2} aria-hidden="true" />}
        </button>
        <button type="button" className={styles.skip} aria-label={`Forward ${SKIP_S} seconds`} disabled={loading} onClick={() => rec.skip(SKIP_S)}>
          <RotateCw size={20} strokeWidth={1.75} aria-hidden="true" />
          <span className={styles.skipNum} aria-hidden="true">{SKIP_S}</span>
        </button>
        <span className={cx(styles.time, "mono")}>
          {loading ? "--:--" : clock(rec.time)} / {clock(rec.duration)}
        </span>
        <SpeedMenu rate={rec.rate} disabled={loading} onChange={rec.setRate} />
        <span className={styles.volume}>
          <button type="button" className={styles.iconButton} aria-label={rec.muted ? "Unmute" : "Mute"} disabled={loading} onClick={rec.toggleMute}>
            {rec.muted ? <VolumeX size={18} strokeWidth={1.75} aria-hidden="true" /> : <Volume2 size={18} strokeWidth={1.75} aria-hidden="true" />}
          </button>
          <input
            type="range"
            className={styles.volumeRange}
            aria-label="Volume"
            min={0}
            max={1}
            step={0.05}
            value={rec.muted ? 0 : rec.volume}
            disabled={loading}
            onChange={(e) => rec.setVolume(Number(e.target.value))}
            style={{ ["--fill" as string]: `${(rec.muted ? 0 : rec.volume) * 100}%` }}
          />
        </span>
      </div>
    </section>
  );
}

function Waveform({ rec, progress, duration, disabled }: { rec: Recording; progress: number; duration: number; disabled: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  function seekAt(clientX: number) {
    const box = ref.current?.getBoundingClientRect();
    if (!box || box.width === 0 || duration <= 0) return;
    rec.seek(((clientX - box.left) / box.width) * duration);
  }

  function onKeyDown(e: KeyboardEvent) {
    const moves: Record<string, () => void> = {
      ArrowLeft: () => rec.seek(rec.time - KEY_SEEK_S),
      ArrowRight: () => rec.seek(rec.time + KEY_SEEK_S),
      Home: () => rec.seek(0),
      End: () => rec.seek(duration),
      " ": rec.toggle,
    };
    const move = moves[e.key];
    if (move) {
      e.preventDefault();
      move();
    }
  }

  const pointer = {
    onPointerDown: (e: PointerEvent) => {
      if (disabled) return;
      dragging.current = true;
      e.currentTarget.setPointerCapture?.(e.pointerId);
      seekAt(e.clientX);
    },
    onPointerMove: (e: PointerEvent) => {
      if (dragging.current) seekAt(e.clientX);
    },
    onPointerUp: () => {
      dragging.current = false;
    },
  };

  const played = Math.round(progress * rec.peaks.length);
  return (
    <div className={cx(styles.waveWrap, disabled && styles.waveLoading)}>
      {!disabled && (
        <span className={cx(styles.bubble, "mono")} style={{ left: `${progress * 100}%` }} aria-hidden="true">
          {clock(rec.time)}
        </span>
      )}
      <div
        ref={ref}
        role="slider"
        tabIndex={disabled ? -1 : 0}
        aria-label="Seek"
        aria-disabled={disabled || undefined}
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(rec.time)}
        aria-valuetext={`${clock(rec.time)} of ${clock(rec.duration)}`}
        className={styles.wave}
        onKeyDown={disabled ? undefined : onKeyDown}
        {...pointer}
      >
        {rec.peaks.map((peak, i) => (
          <span key={i} className={cx(styles.bar, !disabled && i < played && styles.barPlayed)} style={{ height: `${Math.round(peak * 100)}%` }} />
        ))}
        {!disabled && <span className={styles.playhead} style={{ left: `${progress * 100}%` }} aria-hidden="true" />}
      </div>
      {disabled && <span className={styles.loadingRule} aria-hidden="true" />}
    </div>
  );
}

function SpeedMenu({ rate, disabled, onChange }: { rate: number; disabled: boolean; onChange: (rate: number) => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const items = useRef<(HTMLButtonElement | null)[]>([]);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    items.current[SPEEDS.indexOf(rate as (typeof SPEEDS)[number])]?.focus();
    function outside(e: MouseEvent) {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [open, rate]);

  function onKeyDown(e: KeyboardEvent) {
    const list = items.current.filter((el): el is HTMLButtonElement => !!el);
    const at = list.indexOf(document.activeElement as HTMLButtonElement);
    const go = (i: number) => {
      e.preventDefault();
      list[(i + list.length) % list.length]?.focus();
    };
    if (e.key === "ArrowDown") go(at + 1);
    else if (e.key === "ArrowUp") go(at - 1);
    else if (e.key === "Escape") {
      e.preventDefault(); // the slide-over ignores a handled Escape, so only the menu closes
      setOpen(false);
      trigger.current?.focus();
    } else if (e.key === "Tab") setOpen(false);
  }

  const Chevron = open ? ChevronUp : ChevronDown;
  return (
    <div ref={root} className={styles.speed} onKeyDown={open ? onKeyDown : undefined}>
      <button
        ref={trigger}
        type="button"
        className={cx(styles.speedButton, "mono")}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={`Playback speed ${speedLabel(rate)}`}
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
      >
        {speedLabel(rate)}
        <Chevron size={14} strokeWidth={2} aria-hidden="true" />
      </button>
      {open && (
        <div id={menuId} role="menu" aria-label="Playback speed" className={styles.speedMenu}>
          <p className={styles.speedHeading} aria-hidden="true">Playback speed</p>
          {SPEEDS.map((speed, i) => (
            <button
              key={speed}
              ref={(el) => {
                items.current[i] = el;
              }}
              type="button"
              role="menuitemradio"
              aria-checked={speed === rate}
              className={cx(styles.speedItem, "mono", speed === rate && styles.speedCurrent)}
              onClick={() => {
                onChange(speed);
                setOpen(false);
                trigger.current?.focus();
              }}
            >
              {speedLabel(speed)}
              {speed === rate && <Check size={14} strokeWidth={2} aria-hidden="true" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** "Call recording" heading plus why there's no player: still processing, never made, failed or deleted. */
export function RecordingNotice({ status, notReached }: { status: Exclude<RecordingStatus, "complete">; notReached?: boolean }) {
  const titleId = useId();
  if (status === "processing") {
    return (
      <section aria-labelledby={titleId} className={styles.group}>
        <h3 className={styles.groupTitle}>Call recording</h3>
        <div className={cx(styles.card, styles.notice, styles.processing)} role="status">
          <span className={cx(styles.noticeIcon, styles.blue)} aria-hidden="true">
            <Clock size={18} strokeWidth={1.75} />
          </span>
          <div className={styles.noticeText}>
            <h4 id={titleId} className={styles.noticeTitle}>Recording is being prepared</h4>
            <p className={styles.noticeBody}>It usually shows up within a minute after the call ends.</p>
          </div>
          <span className={styles.indeterminate} aria-hidden="true" />
        </div>
      </section>
    );
  }
  const body =
    status === "purged"
      ? "Recordings are kept for 90 days."
      : status === "failed"
        ? "Recording failed for this call."
        : notReached
          ? "The caller didn't pick up, so nothing was recorded."
          : "This call wasn't recorded.";
  return (
    <section aria-labelledby={titleId} className={styles.group}>
      <h3 className={styles.groupTitle}>Call recording</h3>
      <div className={styles.empty}>
        <span className={styles.emptyIcon} aria-hidden="true">
          <MicOff size={18} strokeWidth={1.75} />
        </span>
        <h4 id={titleId} className={styles.emptyTitle}>No recording for this call</h4>
        <p className={styles.noticeBody}>{body}</p>
      </div>
    </section>
  );
}
