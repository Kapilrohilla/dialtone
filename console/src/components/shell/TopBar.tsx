import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import styles from "./TopBar.module.css";

export type Crumb = { label: string; href?: string };

export type TopBarProps = {
  /** A plain page title. Use `breadcrumb` instead on detail pages; the last crumb becomes the heading. */
  title?: string;
  breadcrumb?: Crumb[];
  /** Next to the heading, e.g. a Chip. */
  chip?: ReactNode;
  /** Quiet text before the actions, e.g. "Saved 14:32". */
  status?: ReactNode;
  secondary?: ReactNode;
  /** The screen's one amber button. */
  primary?: ReactNode;
};

/** First thing in every console page. */
export function TopBar({ title, breadcrumb, chip, status, secondary, primary }: TopBarProps) {
  const trail = breadcrumb ?? [];
  const heading = title ?? trail[trail.length - 1]?.label ?? "";
  const parents = title ? trail : trail.slice(0, -1);
  return (
    <header className={styles.bar}>
      <div className={styles.left}>
        {parents.length > 0 && (
          <nav aria-label="Breadcrumb" className={styles.crumbs}>
            {parents.map((c) => (
              <span key={c.label} className={styles.crumb}>
                {c.href ? <Link href={c.href}>{c.label}</Link> : c.label}
                <ChevronRight size={16} strokeWidth={1.75} aria-hidden="true" />
              </span>
            ))}
          </nav>
        )}
        <h1 className={styles.title}>{heading}</h1>
        {chip}
      </div>
      <div className={styles.right}>
        {status && <span className={styles.status}>{status}</span>}
        {secondary}
        {primary}
      </div>
    </header>
  );
}
