import { Panel } from "@/components/ui";
import { formatDuration } from "@/lib/format";
import type { Dashboard } from "@/lib/types";
import styles from "./dashboard.module.css";

type Props = { data?: Dashboard };

export function Readings({ data }: Props) {
  const items = [
    { label: "Calls today", value: data ? String(data.calls_today) : null },
    { label: "Connected", value: data ? (data.connected_pct == null ? "—" : `${data.connected_pct}%`) : null },
    { label: "Interested", value: data ? String(data.interested) : null },
    { label: "Average call", value: data ? formatDuration(data.avg_duration_s) : null },
  ];
  return (
    <Panel padded={false} className={styles.readings} aria-label="Today in numbers">
      {items.map((r) => (
        <div key={r.label} className={styles.reading}>
          <span className={styles.label}>{r.label}</span>
          {r.value == null ? <span className={styles.skeleton} style={{ width: 72, height: 36 }} aria-hidden="true" /> : <span className={styles.number}>{r.value}</span>}
        </div>
      ))}
    </Panel>
  );
}
