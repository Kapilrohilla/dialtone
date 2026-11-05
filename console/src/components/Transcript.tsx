"use client";

import { useLayoutEffect, useRef } from "react";
import { ChipText } from "@/components/editor/ChipText";
import { cx } from "@/components/ui/util";
import type { TranscriptTurn } from "@/lib/types";
import styles from "./Transcript.module.css";

export type TranscriptProps = {
  lines: TranscriptTurn[];
  /** Accessible name of the log. */
  label?: string;
  /** Shown while `lines` is empty. */
  empty?: string;
  className?: string;
};

const NEAR_BOTTOM_PX = 24;

/** Who said what. Caller labels are amber, agent labels blue; the agent's expressions show as the editor's chips
 *  before its line. Follows new lines only while the reader is at the bottom. */
export function Transcript({ lines, label = "Transcript", empty = "Nothing has been said yet.", className }: TranscriptProps) {
  const ref = useRef<HTMLDivElement>(null);
  const atBottom = useRef(true);

  useLayoutEffect(() => {
    const el = ref.current;
    if (el && atBottom.current) el.scrollTop = el.scrollHeight;
  }, [lines.length]);

  function onScroll() {
    const el = ref.current;
    if (el) atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX;
  }

  return (
    <div ref={ref} role="log" aria-label={label} tabIndex={0} className={cx(styles.log, className)} onScroll={onScroll}>
      {lines.length === 0 && <p className={styles.empty}>{empty}</p>}
      {lines.map((line, i) => {
        const agent = line.speaker === "agent";
        return (
          <div key={`${line.at}-${i}`} className={styles.line}>
            <span className={cx(styles.who, agent ? styles.agent : styles.caller)}>{agent ? "Agent" : "Caller"}</span>
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
