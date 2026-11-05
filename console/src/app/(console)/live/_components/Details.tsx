import { Disclosure } from "@/components/ui";
import { answerLabel } from "@/lib/answers";
import styles from "../live.module.css";

/** What the agent has captured so far, in plain-word labels. */
export function Details({ captured }: { captured: Record<string, string> }) {
  const entries = Object.entries(captured);
  return (
    <Disclosure title="Details" defaultOpen>
      {entries.length === 0 ? (
        <p className={styles.none}>Nothing captured yet.</p>
      ) : (
        <dl className={styles.details}>
          {entries.map(([key, value]) => (
            <div key={key} className={styles.pair}>
              <dt>{answerLabel(key)}</dt>
              <dd>{String(value)}</dd>
            </div>
          ))}
        </dl>
      )}
    </Disclosure>
  );
}
