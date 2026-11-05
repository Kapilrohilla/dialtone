import { Check } from "lucide-react";
import styles from "../live.module.css";

/** The steps this call has passed through, ending with the current one. The future path isn't known yet. */
export function StepLine({ steps }: { steps: string[] }) {
  if (steps.length === 0) return null;
  return (
    <ol className={styles.steps} aria-label="Steps so far">
      {steps.map((name, i) => {
        const current = i === steps.length - 1;
        return (
          <li key={`${name}-${i}`} className={current ? styles.current : styles.step} aria-current={current ? "step" : undefined}>
            {!current && <Check size={16} strokeWidth={1.75} aria-hidden="true" className={styles.mark} />}
            {name}
          </li>
        );
      })}
    </ol>
  );
}
