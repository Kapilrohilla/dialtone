import { useState } from "react";
import { Segmented } from "@/components/ui";
import { shiftDay } from "@/lib/format";
import styles from "../calls.module.css";

type Preset = "today" | "7d" | "30d" | "custom";

const OPTIONS: { value: Preset; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "custom", label: "Custom" },
];

const DAYS: Record<Exclude<Preset, "custom">, number> = { today: 0, "7d": 6, "30d": 29 };

export type DateRangeProps = { from: string; to: string; today: string; onChange: (from: string, to: string) => void };

/** The range as quick choices plus two date inputs for a custom one. `today` is the user's today (their time zone). */
export function DateRange({ from, to, today, onChange }: DateRangeProps) {
  const [custom, setCustom] = useState(false);
  const matched = (Object.keys(DAYS) as (keyof typeof DAYS)[]).find((p) => to === today && from === shiftDay(today, -DAYS[p]));
  const value: Preset = custom || !matched ? "custom" : matched;

  function pick(next: Preset) {
    if (next === "custom") return setCustom(true);
    setCustom(false);
    onChange(shiftDay(today, -DAYS[next]), today);
  }

  return (
    <div className={styles.range}>
      <Segmented label="Date range" options={OPTIONS} value={value} onChange={pick} />
      {value === "custom" && (
        <div className={styles.dates}>
          <input type="date" aria-label="From date" className={styles.date} value={from} max={to || undefined} onChange={(e) => e.target.value && onChange(e.target.value, to)} />
          <span aria-hidden="true">–</span>
          <input type="date" aria-label="To date" className={styles.date} value={to} min={from || undefined} onChange={(e) => e.target.value && onChange(from, e.target.value)} />
        </div>
      )}
    </div>
  );
}
