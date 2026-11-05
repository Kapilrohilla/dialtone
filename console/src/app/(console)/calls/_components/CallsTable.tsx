import { Chip, Table, Td, Th } from "@/components/ui";
import { formatDuration, formatPhone, formatWhen } from "@/lib/format";
import { outcomeTone } from "@/lib/outcomes";
import type { CallPage } from "@/lib/types";
import { Button } from "@/components/ui";
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
};

export function CallsTable({ page, timeZone, stale, onOpen, onPage }: CallsTableProps) {
  return (
    <div className={stale ? styles.stale : undefined} aria-busy={stale || undefined}>
      <Table rowHeight={52} aria-label="Calls">
        <thead>
          <tr>
            <Th>When</Th>
            <Th>Caller</Th>
            <Th>Outcome</Th>
            <Th>Mood</Th>
            <Th>Duration</Th>
            <Th>Summary</Th>
          </tr>
        </thead>
        <tbody>
          {page.results.map((call) => {
            const caller = formatPhone(call.caller);
            const when = formatWhen(call.started_at, timeZone);
            return (
              <tr key={call.room} className={styles.row}>
                <Td className={styles.when}>
                  <button type="button" className={styles.rowButton} aria-label={`Open call from ${caller}, ${when}`} onClick={() => onOpen(call.room)}>
                    {when}
                  </button>
                </Td>
                <Td className="mono">{caller}</Td>
                <Td><OutcomeChip outcome={call.outcome} /></Td>
                <Td>{call.mood ? capitalise(call.mood) : <span className={styles.none}>—</span>}</Td>
                <Td className="mono">{formatDuration(call.duration_s)}</Td>
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
