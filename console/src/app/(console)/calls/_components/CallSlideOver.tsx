import { Button, SlideOver, StateBlock } from "@/components/ui";
import { Transcript } from "@/components/Transcript";
import { ApiError } from "@/lib/api";
import { answerLabel } from "@/lib/answers";
import { formatPhone, formatWhen } from "@/lib/format";
import { useCall, useMarkNeedsPerson, useMe } from "@/lib/queries";
import { canEdit } from "@/lib/roles";
import { OutcomeChip } from "./CallsTable";
import styles from "../calls.module.css";

const answerText = (v: unknown) => (typeof v === "string" ? v : typeof v === "object" && v !== null ? JSON.stringify(v) : String(v));

export type CallSlideOverProps = { room: string; timeZone: string; onClose: () => void };

export function CallSlideOver({ room, timeZone, onClose }: CallSlideOverProps) {
  const { data: call, isError, error, refetch } = useCall(room);
  const { data: me } = useMe();
  const mark = useMarkNeedsPerson();

  const footer =
    call && canEdit(me?.role) ? (
      mark.isSuccess ? (
        <p className={styles.marked}>Marked for a call back. It shows on the dashboard under Needs a person.</p>
      ) : (
        <Button variant="primary" loading={mark.isPending} onClick={() => mark.mutate(room)}>Mark for call back</Button>
      )
    ) : undefined;

  return (
    <SlideOver open onClose={onClose} title="Call details" footer={footer}>
      {call ? (
        <>
          <div className={styles.head}>
            <span className={`${styles.headPhone} mono`}>{formatPhone(call.caller)}</span>
            <OutcomeChip outcome={call.outcome} />
            <span className={styles.headWhen}>{formatWhen(call.started_at, timeZone)}</span>
          </div>
          {call.recording_url && <audio controls src={call.recording_url} aria-label="Call recording" className={styles.player} />}
          <section aria-labelledby="call-what">
            <h3 id="call-what" className={styles.sectionTitle}>What happened</h3>
            <p className={styles.para}>{call.summary || call.reason || "No summary for this call."}</p>
          </section>
          {call.step_path.length > 0 && (
            <section aria-labelledby="call-steps">
              <h3 id="call-steps" className={styles.sectionTitle}>Steps</h3>
              <p className={styles.steps}>{call.step_path.join(" → ")}</p>
            </section>
          )}
          {Object.keys(call.answers).length > 0 && (
            <section aria-labelledby="call-answers">
              <h3 id="call-answers" className={styles.sectionTitle}>Answers</h3>
              <dl className={styles.answers}>
                {Object.entries(call.answers).map(([key, value]) => (
                  <div key={key} className={styles.pair}>
                    <dt>{answerLabel(key)}</dt>
                    <dd>{answerText(value)}</dd>
                  </div>
                ))}
              </dl>
            </section>
          )}
          <section aria-labelledby="call-transcript">
            <h3 id="call-transcript" className={styles.sectionTitle}>Transcript</h3>
            <Transcript lines={call.transcript} label="Call transcript" empty="No transcript. Transcripts are kept for 90 days." className={styles.transcript} />
          </section>
        </>
      ) : isError ? (
        <StateBlock
          state="error"
          title={error instanceof ApiError && error.status === 404 ? "This call could not be found." : "Could not load this call."}
          onRetry={error instanceof ApiError && error.status === 404 ? undefined : () => refetch()}
        />
      ) : (
        <StateBlock state="loading" title="Loading call" />
      )}
    </SlideOver>
  );
}
