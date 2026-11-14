import { ChevronDown, ChevronRight, Play } from "lucide-react";
import { useState } from "react";
import { AuditFixesPanel } from "@/components/audit-fixes/AuditFixesPanel";
import { Button, Chip, Spinner } from "@/components/ui";
import { cx } from "@/components/ui/util";
import { ApiError } from "@/lib/api";
import { EVENT_LABELS, scoreTone } from "@/lib/audit";
import { callFixesKey, useCallAudit, useCallFixes, useRunAudit, useSuggestCallFixes } from "@/lib/queries";
import { clock } from "@/lib/recording";
import type { AuditArea, AuditEvidence, AuditMoment } from "@/lib/types";
import styles from "../calls.module.css";

type Anchor = Pick<AuditEvidence, "at" | "at_s" | "speaker">;

export type AuditSectionProps = {
  room: string;
  /** Editors and up can run an audit. */
  canRun: boolean;
  /** Seconds into the recording for an item; null when there's no recording to seek. */
  offsetOf: (item: Anchor) => number | null;
  /** Jump to the item: seek the recording and highlight its transcript line. */
  onJump: (item: Anchor) => void;
};

/** The AI scorecard for the call: overall score, six rubric areas with evidence, and the moments to look at. */
export function AuditSection({ room, canRun, offsetOf, onJump }: AuditSectionProps) {
  const { data: audit, isError, error, refetch } = useCallAudit(room);
  const runAudit = useRunAudit(room);

  const runButton = (label: string) =>
    canRun ? (
      <Button size="sm" variant="outline" loading={runAudit.isPending} onClick={() => runAudit.mutate()}>{label}</Button>
    ) : null;

  let body;
  if (isError) {
    body = (
      <div className={styles.auditState}>
        <p className={styles.para}>{error instanceof ApiError && error.status !== 500 ? error.detail : "Could not load the audit."}</p>
        <Button size="sm" variant="text" onClick={() => refetch()}>Try again</Button>
      </div>
    );
  } else if (!audit) {
    body = <p className={styles.auditNote}>Loading audit…</p>;
  } else if (audit.status === "none") {
    body = (
      <div className={styles.auditState}>
        <p className={styles.para}>
          {audit.enabled ? "This call hasn't been audited." : "Call audits are off. Turn them on in Settings, Call handling."}
        </p>
        {runButton("Audit this call")}
      </div>
    );
  } else if (audit.status === "queued" || audit.status === "running") {
    body = (
      <p className={cx(styles.auditState, styles.para)} role="status">
        <Spinner size={14} /> Auditing this call…
      </p>
    );
  } else if (audit.status === "skipped") {
    body = (
      <div className={styles.auditState}>
        <p className={styles.para}>{audit.skipped_label || "This call wasn't audited."}</p>
        {runButton("Re-audit")}
      </div>
    );
  } else if (audit.status === "error") {
    body = (
      <div className={styles.auditState}>
        <p className={styles.para} role="alert">{audit.error || "Couldn't audit this call. Try again."}</p>
        {runButton("Try again")}
      </div>
    );
  } else {
    const good = audit.moments.filter((m) => m.kind === "good");
    const problems = audit.moments.filter((m) => m.kind === "problem");
    body = (
      <>
        <div className={styles.auditHead}>
          <Chip tone={scoreTone(audit.overall_score)}>
            <span aria-label={`Score ${audit.overall_score ?? "not available"} out of 100`}>Score {audit.overall_score ?? "—"}</span>
          </Chip>
          {runButton("Re-audit")}
        </div>
        {audit.summary && <p className={styles.para}>{audit.summary}</p>}
        <ul className={styles.areas} aria-label="Scores by area">
          {audit.areas.map((area) => (
            <AreaRow key={area.key} area={area} offsetOf={offsetOf} onJump={onJump} />
          ))}
        </ul>
        {(problems.length > 0 || good.length > 0) && (
          <div className={styles.moments}>
            {problems.length > 0 && <MomentList title="To fix" moments={problems} areas={audit.areas} offsetOf={offsetOf} onJump={onJump} />}
            {good.length > 0 && <MomentList title="Went well" moments={good} areas={audit.areas} offsetOf={offsetOf} onJump={onJump} />}
          </div>
        )}
        <p className={styles.auditNote}>
          Scored by AI{audit.automatic ? " after the call" : ""}. Only the agent&rsquo;s side is scored.
          {audit.quotes_purged && " Quotes were removed after 90 days; the scores stay."}
        </p>
        <CallFixes room={room} canRun={canRun} hasProblems={problems.length > 0} />
      </>
    );
  }

  return (
    <section aria-labelledby="call-audit">
      <h3 id="call-audit" className={styles.sectionTitle}>Audit</h3>
      {body}
    </section>
  );
}

/** "Suggest fixes" for this call's problem moments, and the last run's fixes to review. */
function CallFixes({ room, canRun, hasProblems }: { room: string; canRun: boolean; hasProblems: boolean }) {
  const { data: run, isError } = useCallFixes(room);
  const suggest = useSuggestCallFixes(room);
  const running = run?.status === "running";
  if (!hasProblems && !run) return null;
  const startError = suggest.error ? (suggest.error instanceof ApiError ? suggest.error.detail : "Could not suggest fixes.") : null;
  return (
    <section className={styles.fixes} aria-labelledby="call-fixes">
      <div className={styles.auditHead}>
        <h4 id="call-fixes" className={styles.momentTitle}>Fixes</h4>
        {canRun && hasProblems && !running && (
          <Button size="sm" variant="outline" loading={suggest.isPending} onClick={() => suggest.mutate()}>
            {run ? "Suggest again" : "Suggest fixes"}
          </Button>
        )}
      </div>
      {startError && <p className={styles.auditError} role="alert">{startError}</p>}
      {isError && <p className={styles.auditNote}>Could not load the fixes.</p>}
      {run ? (
        <AuditFixesPanel run={run} cacheKey={callFixesKey(room)} readOnly={!canRun} />
      ) : (
        run === null && canRun && <p className={styles.auditNote}>Get ready-to-apply changes to the workflow or agent for the problems above.</p>
      )}
    </section>
  );
}

/** 4–5 green, 3 amber, 1–2 red. */
const DOT_CLASS = (score: number) => (score >= 4 ? styles.dotOk : score === 3 ? styles.dotAmber : styles.dotBad);

function Dots({ score }: { score: number | null }) {
  return (
    <span className={styles.dots} role="img" aria-label={score == null ? "No score" : `${score} out of 5`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <span key={n} className={cx(styles.dot, score != null && n <= score && DOT_CLASS(score))} />
      ))}
    </span>
  );
}

function AreaRow({ area, offsetOf, onJump }: { area: AuditArea; offsetOf: AuditSectionProps["offsetOf"]; onJump: AuditSectionProps["onJump"] }) {
  const [open, setOpen] = useState(false);
  const Icon = open ? ChevronDown : ChevronRight;
  const id = `audit-area-${area.key}`;
  return (
    <li className={styles.area}>
      <button type="button" className={styles.areaToggle} aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        <Icon size={16} strokeWidth={1.75} aria-hidden="true" />
        <span className={styles.areaLabel}>{area.label}</span>
        <Dots score={area.score} />
        <span className={cx(styles.areaScore, "mono")}>{area.score == null ? "—" : `${area.score}/5`}</span>
      </button>
      {area.summary && <p className={styles.areaSummary}>{area.summary}</p>}
      {open && (
        <ul id={id} className={styles.evidence}>
          {area.evidence.length === 0 && <li className={styles.auditNote}>No evidence, so this area has no score.</li>}
          {area.evidence.map((e, i) => (
            <li key={i} className={styles.evidenceItem}>
              <TimeChip item={e} offsetOf={offsetOf} onJump={onJump} />
              <span>
                <span className={cx(styles.kind, e.kind === "good" ? styles.kindGood : styles.kindBad)}>{e.kind === "good" ? "Good" : "Problem"}</span>
                {e.quote ? <q className={styles.quote}>{e.quote}</q> : e.event ? <span className={styles.quote}>{EVENT_LABELS[e.event] ?? e.event}</span> : null}
                {e.note && <span className={styles.note}> {e.note}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function MomentList({ title, moments, areas, offsetOf, onJump }: {
  title: string;
  moments: AuditMoment[];
  areas: AuditArea[];
  offsetOf: AuditSectionProps["offsetOf"];
  onJump: AuditSectionProps["onJump"];
}) {
  const label = (key: string) => areas.find((a) => a.key === key)?.label ?? "";
  return (
    <div>
      <h4 className={styles.momentTitle}>{title}</h4>
      <ul className={styles.evidence}>
        {moments.map((m, i) => (
          <li key={i} className={styles.evidenceItem}>
            <TimeChip item={m} offsetOf={offsetOf} onJump={onJump} />
            <span>
              {m.note}
              {m.quote && (
                <>
                  {" "}
                  <q className={styles.quote}>{m.quote}</q>
                </>
              )}
              {(m.step_name || m.area) && (
                <span className={styles.momentMeta}> {[label(m.area), m.step_name].filter(Boolean).join(" · ")}</span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A moment's time; clicking it jumps the recording there and highlights the transcript line. */
function TimeChip({ item, offsetOf, onJump }: { item: Anchor; offsetOf: AuditSectionProps["offsetOf"]; onJump: AuditSectionProps["onJump"] }) {
  if (!item.at) return <span className={styles.timeChip} aria-hidden="true" />;
  const offset = offsetOf(item);
  const label = clock(offset ?? item.at_s);
  return (
    <button
      type="button"
      className={cx(styles.timeChip, styles.timeChipButton, "mono")}
      aria-label={offset != null ? `Play from ${label}` : `Show line at ${label} in the transcript`}
      onClick={() => onJump(item)}
    >
      {offset != null && <Play size={10} strokeWidth={2.25} aria-hidden="true" />}
      {label}
    </button>
  );
}
