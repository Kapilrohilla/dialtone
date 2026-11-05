import { Button, Panel } from "@/components/ui";
import { formatPhone, formatWhen } from "@/lib/format";
import type { Dashboard } from "@/lib/types";
import styles from "./dashboard.module.css";

type Props = {
  rows?: Dashboard["needs_person"];
  canCallBack: boolean;
  timeZone: string;
  onCallBack: (room: string) => void;
};

export function NeedsPerson({ rows, canCallBack, timeZone, onCallBack }: Props) {
  return (
    <Panel aria-labelledby="needs-person-title">
      <h2 id="needs-person-title" className={styles.heading}>Needs a person</h2>
      {!rows ? (
        <div className={styles.skeletonRows} aria-hidden="true">
          {[0, 1, 2].map((i) => <span key={i} className={styles.skeleton} style={{ height: 40 }} />)}
        </div>
      ) : rows.length === 0 ? (
        <p className={styles.empty}>No one is waiting for a call back.</p>
      ) : (
        <ul className={styles.list}>
          {rows.map((n) => (
            <li key={n.room} className={styles.person}>
              <span className={styles.mono}>{formatPhone(n.caller)}</span>
              <span className={n.reason ? styles.reason : styles.reasonMuted}>{n.reason || "No reason given"}</span>
              <span className={styles.mono}>{formatWhen(n.at, timeZone)}</span>
              {canCallBack && (
                <Button variant="text" size="sm" className={styles.amberText} onClick={() => onCallBack(n.room)}>
                  Call back
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
