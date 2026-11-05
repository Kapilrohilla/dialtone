import { Chip, type ChipTone } from "@/components/ui";
import { formatElapsed, formatPhone } from "@/lib/format";
import type { LiveCall } from "@/lib/types";
import styles from "../live.module.css";

const BAD = new Set(["frustrated", "angry", "upset"]);
const OK = new Set(["interested", "happy", "positive"]);

/** One-word mood as a chip; nothing when the call has no mood yet. */
export function MoodChip({ mood }: { mood: string }) {
  const word = mood.trim();
  if (!word) return null;
  const key = word.toLowerCase();
  const tone: ChipTone = BAD.has(key) ? "bad" : OK.has(key) ? "ok" : "neutral";
  return <Chip tone={tone} className={styles.mood}>{key[0].toUpperCase() + key.slice(1)}</Chip>;
}

export type LiveListProps = { calls: LiveCall[]; selected: string | undefined; now: Date; onSelect: (room: string) => void };

export function LiveList({ calls, selected, now, onSelect }: LiveListProps) {
  return (
    <>
      {calls.map((call) => (
        <button key={call.room} type="button" className={styles.row} aria-current={call.room === selected} onClick={() => onSelect(call.room)}>
          <span className={`${styles.phone} mono`}>{formatPhone(call.caller)}</span>
          <span className={`${styles.time} mono`}>{formatElapsed(call.started_at, now)}</span>
          <span className={styles.city}>{call.city || "—"}</span>
          <MoodChip mood={call.mood} />
        </button>
      ))}
    </>
  );
}
