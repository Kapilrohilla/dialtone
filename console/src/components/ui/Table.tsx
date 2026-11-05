import type { CSSProperties, HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { cx } from "./util";
import styles from "./Table.module.css";

/** Horizontal rules only, no outer card. Keep to six columns or fewer. `rowHeight` is in px. */
export function Table({ rowHeight = 56, children, className, ...rest }: { rowHeight?: number; children: ReactNode } & HTMLAttributes<HTMLTableElement>) {
  return (
    <table className={cx(styles.table, className)} style={{ "--row-h": `${rowHeight}px` } as CSSProperties} {...rest}>
      {children}
    </table>
  );
}

export function Th({ className, scope = "col", ...rest }: ThHTMLAttributes<HTMLTableCellElement>) {
  return <th scope={scope} className={cx(styles.th, className)} {...rest} />;
}

export function Td({ className, ...rest }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cx(styles.td, className)} {...rest} />;
}
