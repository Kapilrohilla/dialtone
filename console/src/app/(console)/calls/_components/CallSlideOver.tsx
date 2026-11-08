import { useEffect, useMemo, useRef, type MutableRefObject } from "react";
import { Button, SlideOver, StateBlock, useToast } from "@/components/ui";
import { RecordingNotice, RecordingPlayer } from "@/components/recording/RecordingPlayer";
import { useRecording, type PlaybackState } from "@/components/recording/useRecording";
import { Transcript } from "@/components/Transcript";
import { ApiError } from "@/lib/api";
import { answerLabel } from "@/lib/answers";
import { formatPhone, formatWhen } from "@/lib/format";
import { useCall, useMarkNeedsPerson, useMe } from "@/lib/queries";
import { activeTurn, speakerSegments, turnOffsets } from "@/lib/recording";
import { canEdit } from "@/lib/roles";
import type { CallDetail } from "@/lib/types";
import { OutcomeChip } from "./CallsTable";
import styles from "../calls.module.css";

const answerText = (v: unknown) => (typeof v === "string" ? v : typeof v === "object" && v !== null ? JSON.stringify(v) : String(v));

/** Lets the call table's play button drive the open call's player. */
export type PlaybackControls = { toggle: () => void };

export type CallSlideOverProps = {
  room: string;
  timeZone: string;
  onClose: () => void;
  /** Start playing once the recording loads: the table's play button opened this call. */
  autoplay?: boolean;
  /** The player's state, for the table row; null when there's nothing to play. */
  onPlayback?: (state: PlaybackState | null) => void;
  controls?: MutableRefObject<PlaybackControls | null>;
};

export function CallSlideOver({ room, timeZone, onClose, autoplay, onPlayback, controls }: CallSlideOverProps) {
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

  const title = call ? (
    <span className={styles.headTitle}>
      <span className={`${styles.headPhone} mono`}>{formatPhone(call.caller)}</span>
      <OutcomeChip outcome={call.outcome} />
    </span>
  ) : (
    "Call details"
  );

  return (
    <SlideOver open onClose={onClose} title={title} footer={footer} wide>
      {call ? (
        <CallBody call={call} timeZone={timeZone} autoplay={autoplay} onPlayback={onPlayback} controls={controls} />
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

function CallBody({ call, timeZone, autoplay, onPlayback, controls }: { call: CallDetail } & Omit<CallSlideOverProps, "room" | "onClose">) {
  const toast = useToast();
  const url = call.recording_url;
  const rec = useRecording(url, { seed: call.room, duration: call.recording_duration_s, autoplay });

  const offsets = useMemo(() => (url ? turnOffsets(call.transcript, call.recording_started_at) : null), [url, call.transcript, call.recording_started_at]);
  const segments = useMemo(
    () => (offsets && rec.duration ? speakerSegments(call.transcript, offsets, rec.duration) : []),
    [offsets, rec.duration, call.transcript],
  );
  const active = offsets && rec.status === "ready" && (rec.playing || rec.time > 0) ? activeTurn(offsets, rec.time) : -1;

  // Tell the table what this call's player is doing, and let its play button reach the player.
  const state = url ? rec.state : null;
  useEffect(() => onPlayback?.(state), [state, onPlayback]);
  useEffect(() => () => onPlayback?.(null), [onPlayback]);
  const latest = useRef(rec);
  latest.current = rec;
  useEffect(() => {
    if (!controls) return;
    controls.current = { toggle: () => latest.current.toggle() };
    return () => {
      controls.current = null;
    };
  }, [controls]);

  function copyLink() {
    const link = `${window.location.origin}/calls?room=${encodeURIComponent(call.room)}`;
    Promise.resolve(navigator.clipboard?.writeText(link))
      .then(() => toast.show("Link to this call copied.", "ok"))
      .catch(() => toast.show("Could not copy the link.", "bad"));
  }

  const meta = [call.agent_name, formatWhen(call.started_at, timeZone).replace(/^Today/, "today").replace(/^Yesterday/, "yesterday")].filter(Boolean).join(", ");

  return (
    <>
      <p className={styles.headMeta}>{meta}</p>
      {url ? (
        <RecordingPlayer rec={rec} url={url} segments={segments} turns={call.transcript.length} onCopyLink={copyLink} />
      ) : (
        <RecordingNotice status={call.recording_status === "complete" ? "failed" : call.recording_status} notReached={call.outcome === "Not reached"} />
      )}
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
        <Transcript
          lines={call.transcript}
          label="Call transcript"
          empty="No transcript. Transcripts are kept for 90 days."
          className={styles.transcript}
          times={offsets ?? undefined}
          onSeek={
            offsets && rec.status === "ready"
              ? (i) => {
                  const at = offsets[i];
                  if (at == null) return;
                  if (i === active && rec.playing) rec.pause();
                  else rec.playFrom(at);
                }
              : undefined
          }
          activeIndex={active}
          playing={rec.playing}
        />
      </section>
    </>
  );
}
