import { AudioLines, Clock, MicOff, Pause, Play } from "lucide-react";
import { Button, Chip, Spinner, Table, Td, Th } from "@/components/ui";
import type { PlaybackState } from "@/components/recording/useRecording";
import { cx } from "@/components/ui/util";
import { formatPhone, formatWhen } from "@/lib/format";
import { scoreTone } from "@/lib/audit";
import { outcomeTone } from "@/lib/outcomes";
import { clock } from "@/lib/recording";
import type { CallPage, CallRow, RecordingStatus } from "@/lib/types";
import styles from "../calls.module.css";

export const capitalise = (word: string) => (word ? word[0].toUpperCase() + word.slice(1) : word);

export function OutcomeChip({ outcome }: { outcome: string }) {
  return outcome ? <Chip tone={outcomeTone(outcome)}>{outcome}</Chip> : <span className={styles.none}>—</span>;
}

export type CallsTableProps = {
  page: CallPage;
  timeZone: string;
  /** Showing the previous page while the next one loads. */
  stale: boolean;
  onOpen: (room: string) => void;
  onPage: (page: number) => void;
  /** The call open in the slide-over, highlighted. */
  openRoom?: string | null;
  /** What the open call's player is doing. */
  playback?: PlaybackState | null;
  /** The row's play button: opens the call and plays, or toggles it when it's already open. */
  onPlay?: (room: string) => void;
};

export const recordingStatusOf = (row: CallRow): RecordingStatus => row.recording_status ?? (row.has_recording ? "complete" : "none");

export function CallsTable({ page, timeZone, stale, onOpen, onPage, openRoom, playback, onPlay }: CallsTableProps) {
  return (
    <div className={stale ? styles.stale : undefined} aria-busy={stale || undefined}>
      <Table rowHeight={52} aria-label="Calls">
        <thead>
          <tr>
            <Th>When</Th>
            <Th>Caller</Th>
            <Th>Outcome</Th>
            <Th>Mood</Th>
            <Th>Score</Th>
            <Th>Duration</Th>
            <Th>Summary</Th>
          </tr>
        </thead>
        <tbody>
          {page.results.map((call) => {
            const caller = formatPhone(call.caller);
            const when = formatWhen(call.started_at, timeZone);
            return (
              <tr key={call.room} className={cx(styles.row, call.room === openRoom && styles.selected)}>
                <Td className={styles.when}>
                  <button type="button" className={styles.rowButton} aria-label={`Open call from ${caller}, ${when}`} onClick={() => onOpen(call.room)}>
                    {when}
                  </button>
                </Td>
                <Td className="mono">{caller}</Td>
                <Td><OutcomeChip outcome={call.outcome} /></Td>
                <Td>{call.mood ? capitalise(call.mood) : <span className={styles.none}>—</span>}</Td>
                <Td><ScoreChip score={call.audit_score} /></Td>
                <Td className={styles.durationCell}>
                  <RecordingCell
                    row={call}
                    caller={caller}
                    state={call.room === openRoom ? (playback ?? null) : null}
                    onPlay={onPlay ? () => onPlay(call.room) : undefined}
                  />
                </Td>
                <Td className={styles.summaryCell}>
                  {call.summary ? <span className={styles.summary}>{call.summary}</span> : <span className={styles.none}>No summary</span>}
                </Td>
              </tr>
            );
          })}
        </tbody>
      </Table>
      <nav aria-label="Pages" className={styles.pager}>
        <Button size="sm" disabled={page.page <= 1} onClick={() => onPage(page.page - 1)}>Previous</Button>
        <span aria-live="polite">Page {page.page} of {page.pages}</span>
        <Button size="sm" disabled={page.page >= page.pages} onClick={() => onPage(page.page + 1)}>Next</Button>
      </nav>
    </div>
  );
}

/** The AI audit's overall score: red under 60, amber 60–79, green 80 and up; "—" when the call isn't scored. */
export function ScoreChip({ score }: { score: number | null | undefined }) {
  if (score == null) return <span className={styles.none} aria-label="Not audited">—</span>;
  return (
    <Chip tone={scoreTone(score)} className={styles.score}>
      <span className="mono">{score}</span>
    </Chip>
  );
}

/** Duration column: a play button for finished recordings, otherwise why there's nothing to play. */
function RecordingCell({ row, caller, state, onPlay }: { row: CallRow; caller: string; state: PlaybackState | null; onPlay?: () => void }) {
  const status = recordingStatusOf(row);
  const duration = row.duration_s == null ? "—" : clock(row.duration_s);
  if (status === "processing") {
    return (
      <span className={styles.recNote}>
        <Clock size={16} strokeWidth={1.75} aria-hidden="true" />
        Processing
      </span>
    );
  }
  if (status !== "complete" || !onPlay) {
    return (
      <span className={styles.recCell}>
        {status !== "complete" && (
          <span className={styles.recNote}>
            <MicOff size={16} strokeWidth={1.75} aria-hidden="true" />
            No recording
          </span>
        )}
        <span className={cx("mono", status !== "complete" && styles.none)}>{duration}</span>
      </span>
    );
  }
  const playing = state === "playing";
  const current = state !== null;
  return (
    <span className={cx(styles.recCell, current && styles.recCurrent)}>
      {playing && <AudioLines size={16} strokeWidth={2} className={styles.eq} aria-hidden="true" />}
      <button
        type="button"
        className={cx(styles.rowPlay, current && styles.rowPlayCurrent)}
        aria-label={playing ? `Pause recording of call from ${caller}` : `Play recording of call from ${caller}`}
        aria-pressed={playing}
        onClick={onPlay}
      >
        {state === "loading" ? <Spinner size={14} /> : playing ? <Pause size={14} strokeWidth={2.25} aria-hidden="true" /> : <Play size={14} strokeWidth={2.25} aria-hidden="true" />}
      </button>
      <span className="mono">{duration}</span>
    </span>
  );
}
