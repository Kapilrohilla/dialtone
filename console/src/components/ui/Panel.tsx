import type { HTMLAttributes } from "react";
import { cx } from "./util";
import styles from "./Panel.module.css";

export type PanelProps = HTMLAttributes<HTMLElement> & { padded?: boolean };

/** A bordered surface. Never nest one Panel inside another. */
export function Panel({ padded = true, className, ...rest }: PanelProps) {
  return <section className={cx(styles.panel, padded && styles.padded, className)} {...rest} />;
}
