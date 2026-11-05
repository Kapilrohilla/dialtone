import { Panel } from "@/components/ui";
import type { Dashboard } from "@/lib/types";
import styles from "./dashboard.module.css";

export function OutcomesWeek({ rows }: { rows?: Dashboard["outcomes_week"] }) {
  const max = rows ? Math.max(0, ...rows.map((r) => r.count)) : 0;
  return (
    <Panel aria-labelledby="outcomes-title">
      <h2 id="outcomes-title" className={styles.heading}>Outcomes this week</h2>
      {!rows ? (
        <div className={styles.skeletonRows} aria-hidden="true">
          {[0, 1, 2, 3, 4].map((i) => <span key={i} className={styles.skeleton} style={{ height: 24 }} />)}
        </div>
      ) : max === 0 ? (
        <p className={styles.empty}>No calls this week yet.</p>
      ) : (
        <ul className={styles.list}>
          {rows.map((r) => (
            <li key={r.outcome} className={styles.bar}>
              <span className={styles.barLabel}>{r.outcome}</span>
              <span className={styles.track}>
                <span
                  className={styles.fill}
                  data-outcome={r.outcome}
                  style={{ minWidth: r.count === 0 ? 0 : undefined, width: `${(r.count / max) * 100}%`, background: r.outcome === "Interested" ? "var(--blue)" : "var(--rule-strong)" }}
                />
              </span>
              <span className={styles.mono}>{r.count}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
