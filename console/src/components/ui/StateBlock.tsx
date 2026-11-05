import type { ReactNode } from "react";
import { Button } from "./Button";
import { Spinner } from "./Spinner";
import styles from "./StateBlock.module.css";

export type StateBlockProps = {
  state: "loading" | "empty" | "error";
  title?: string;
  body?: ReactNode;
  /** Error state only: shows a "Try again" button. */
  onRetry?: () => void;
  /** Empty state: where the next step goes, e.g. an "Add agent" button. */
  action?: ReactNode;
};

export function StateBlock({ state, title, body, onRetry, action }: StateBlockProps) {
  if (state === "loading") {
    return (
      <div className={styles.block} role="status" aria-live="polite">
        <Spinner size={20} />
        <p className={styles.body}>{title ?? "Loading"}</p>
      </div>
    );
  }
  return (
    <div className={styles.block} role={state === "error" ? "alert" : undefined}>
      {title && <h3 className={styles.title}>{title}</h3>}
      {body && <p className={styles.body}>{body}</p>}
      {state === "error" && onRetry && <Button onClick={onRetry}>Try again</Button>}
      {state === "empty" && action}
    </div>
  );
}
