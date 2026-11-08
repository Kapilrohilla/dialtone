"use client";

import { AudioLines, Pause, Play } from "lucide-react";
import { useEffect, useLayoutEffect, useRef } from "react";
import { ChipText } from "@/components/editor/ChipText";
import { cx } from "@/components/ui/util";
import { clock } from "@/lib/recording";
import type { TranscriptTurn } from "@/lib/types";
import styles from "./Transcript.module.css";

export type TranscriptProps = {
  lines: TranscriptTurn[];
  /** Accessible name of the log. */
  label?: string;
  /** Shown while `lines` is empty. */
  empty?: string;
  className?: string;
  /** Seconds into the recording per line (null: unknown). Shows a time on each line. */
  times?: (number | null)[];
  /** Turns each line's time into a "play from here" button. */
  onSeek?: (index: number) => void;
  /** The line being heard; it's outlined and kept in view. */
  activeIndex?: number;
  playing?: boolean;
};

const NEAR_BOTTOM_PX = 24;
/** After the reader scrolls the log, playback stops pulling it to the active line for a while. */
const READER_SCROLL_HOLD_MS = 4_000;

/** Who said what. Caller labels are amber, agent labels blue; the agent's expressions show as the editor's chips
 *  before its line. Follows new lines only while the reader is at the bottom. */
export function Transcript({ lines, label = "Transcript", empty = "Nothing has been said yet.", className, times, onSeek, activeIndex = -1, playing = false }: TranscriptProps) {
  const ref = useRef<HTMLDivElement>(null);
  const atBottom = useRef(true);
  const readerScrolledAt = useRef(0);
  const programmatic = useRef(false);

  // The live feed is a sliding window (its length stops growing at the cap), so follow the newest line, not the count.
  const newest = lines.length ? `${lines[lines.length - 1].at}|${lines[lines.length - 1].text}` : "";
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && atBottom.current) el.scrollTop = el.scrollHeight;
  }, [newest]);

  // Keep the line being played in view, unless the reader just scrolled somewhere else.
  useEffect(() => {
    const el = ref.current;
    if (!el || activeIndex < 0 || !playing || Date.now() - readerScrolledAt.current < READER_SCROLL_HOLD_MS) return;
    const line = el.querySelectorAll<HTMLElement>("[data-line]")[activeIndex];
    if (!line) return;
    const top = line.offsetTop - el.offsetTop;
    if (top < el.scrollTop || top + line.offsetHeight > el.scrollTop + el.clientHeight) {
      programmatic.current = true;
      el.scrollTop = Math.max(0, top - 8);
    }
  }, [activeIndex, playing]);

  function onScroll() {
    const el = ref.current;
    if (el) atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX;
    if (programmatic.current) programmatic.current = false;
    else readerScrolledAt.current = Date.now();
  }

  return (
    <div ref={ref} role="log" aria-label={label} tabIndex={0} className={cx(styles.log, className)} onScroll={onScroll}>
      {lines.length === 0 && <p className={styles.empty}>{empty}</p>}
      {lines.map((line, i) => {
        const agent = line.speaker === "agent";
        // `at` is stable as the window slides; a counter separates lines sharing a timestamp.
        const key = `${line.at}#${lines.slice(0, i).filter((l) => l.at === line.at).length}`;
        return (
          <div key={key} data-line className={cx(styles.line, times && styles.timed, i === activeIndex && styles.active)} aria-current={i === activeIndex ? "true" : undefined}>
            <span className={cx(styles.who, agent ? styles.agent : styles.caller)}>
              {agent ? "Agent" : "Caller"}
              {times && i === activeIndex && playing && (
                <span className={styles.playingTag}>
                  <AudioLines size={11} strokeWidth={2.25} aria-hidden="true" />
                  Playing
                </span>
              )}
            </span>
            {times && <LineTime at={times[i]} active={i === activeIndex && playing} onSeek={onSeek ? () => onSeek(i) : undefined} />}
            <p className={styles.text}>
              {line.expressions.length > 0 && (
                <span className={styles.chips}>
                  <ChipText text={line.expressions.map((name) => `[[expr:${name}]]`).join("")} />
                </span>
              )}
              {line.text}
            </p>
          </div>
        );
      })}
    </div>
  );
}

function LineTime({ at, active, onSeek }: { at: number | null; active: boolean; onSeek?: () => void }) {
  if (at == null) return <span className={styles.time} />;
  const label = clock(at);
  if (!onSeek) return <span className={cx(styles.time, "mono")}>{label}</span>;
  const Icon = active ? Pause : Play;
  return (
    <button type="button" className={cx(styles.time, styles.seek, "mono")} aria-label={`Play from ${label}`} onClick={onSeek}>
      <Icon size={11} strokeWidth={2.25} aria-hidden="true" />
      {label}
    </button>
  );
}
