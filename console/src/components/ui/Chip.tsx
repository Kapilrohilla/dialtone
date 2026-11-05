import type { ReactNode } from "react";
import { cx } from "./util";
import styles from "./Chip.module.css";

export type ChipTone = "ok" | "amber" | "blue" | "bad" | "neutral" | "muted";

export function Chip({ tone = "neutral", children, className }: { tone?: ChipTone; children: ReactNode; className?: string }) {
  return <span className={cx(styles.chip, styles[tone], className)}>{children}</span>;
}
