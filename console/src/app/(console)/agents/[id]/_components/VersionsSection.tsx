"use client";

import { Chip } from "@/components/ui";
import { AREA_LABELS, signed } from "@/lib/audit";
import { formatWhen } from "@/lib/format";
import { useAgentVersions, useMe } from "@/lib/queries";
import type { AgentVersion } from "@/lib/types";
import styles from "./editor.module.css";

/** Published versions, newest first: the audit fixes each brought and how its calls scored against the one before. */
export function VersionsSection({ agentId }: { agentId: number }) {
  const { data: versions, isError } = useAgentVersions(agentId);
  const timeZone = useMe().data?.preferences.time_zone;
  return (
    <div className={styles.panelSection}>
      <h2 className={styles.panelTitle}>Versions</h2>
      {isError ? (
        <p className={styles.panelNote}>Could not load the versions.</p>
      ) : !versions ? (
        <p className={styles.panelNote}>Loading versions…</p>
      ) : versions.length === 0 ? (
        <p className={styles.panelNote}>Not published yet.</p>
      ) : (
        <ul className={styles.versionList} aria-label="Versions">
          {versions.map((v) => (
            <li key={v.number} className={styles.version}>
              <VersionRow version={v} timeZone={timeZone} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function VersionRow({ version: v, timeZone }: { version: AgentVersion; timeZone?: string }) {
  const scores = v.audit_scores;
  const cmp = v.compared_to;
  return (
    <article aria-label={`Version ${v.number}`}>
      <p className={styles.versionHead}>
        <strong>v{v.number}</strong>
        <span className={styles.panelNote}>
          {formatWhen(v.published_at, timeZone)}
          {v.published_by_name ? ` · ${v.published_by_name}` : ""}
        </span>
      </p>
      {v.audit_fixes.length > 0 && (
        <ul className={styles.versionFixes} aria-label={`Audit fixes in v${v.number}`}>
          {v.audit_fixes.map((f) => (
            <li key={`${f.target}-${f.id}`}>
              {f.title || "Audit fix"}
              {f.auto_applied && (
                <>
                  {" "}
                  <Chip tone="muted">Auto-applied</Chip>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className={styles.panelNote}>
        {scores.calls > 0 && scores.overall != null
          ? `Average score ${scores.overall} from ${scores.calls} audited ${scores.calls === 1 ? "call" : "calls"}`
          : "No audited calls yet"}
      </p>
      {cmp &&
        (!cmp.enough || !cmp.change ? (
          <p className={styles.panelNote}>Not enough calls yet (need {v.min_calls} per version).</p>
        ) : (
          <div className={styles.versionChange}>
            <p className={styles.versionDelta}>
              {signed(cmp.change.overall)} vs v{cmp.version}
            </p>
            <ul className={styles.versionAreas} aria-label={`Score change by area in v${v.number}`}>
              {AREA_LABELS.map(([key, label]) => (
                <li key={key}>
                  <span>{label}</span>
                  <span className="mono">{signed(cmp.change?.areas[key])}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
    </article>
  );
}
