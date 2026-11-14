import { useState } from "react";
import { Button } from "@/components/ui";
import { RateCall } from "@/components/feedback/RateCall";
import { AREA_LABELS } from "@/lib/audit";
import { useCallFeedback } from "@/lib/queries";
import type { CallFeedback } from "@/lib/types";
import styles from "../calls.module.css";

function scoresText(f: CallFeedback): string {
  const parts = AREA_LABELS.filter(([key]) => f.ratings[key] != null).map(([key, label]) => `${label} ${f.ratings[key]}`);
  return parts.join(" · ");
}

/** People's own ratings of the call (usually from a voice test), and yours to add or change. */
export function FeedbackSection({ room }: { room: string }) {
  const { data: all } = useCallFeedback(room);
  const [rating, setRating] = useState(false);
  const rows = all ?? [];
  const mine = rows.some((f) => f.mine);
  return (
    <section aria-labelledby="call-feedback">
      <h3 id="call-feedback" className={styles.sectionTitle}>Tester ratings</h3>
      {rows.length === 0 && !rating && <p className={styles.para}>No one has rated this call yet.</p>}
      {rows.length > 0 && (
        <ul className={styles.feedbackList}>
          {rows.map((f) => (
            <li key={f.id} className={styles.feedbackItem}>
              <p className={styles.feedbackHead}>
                <strong>{f.mine ? "You" : f.author ?? "Someone"}</strong>
                {f.overall != null && <span> · overall {f.overall}/5</span>}
              </p>
              {scoresText(f) && <p className={styles.feedbackScores}>{scoresText(f)}</p>}
              {f.remarks && <p className={styles.para}>{f.remarks}</p>}
            </li>
          ))}
        </ul>
      )}
      {rating ? (
        <RateCall room={room} onSaved={() => setRating(false)} />
      ) : (
        <Button size="sm" onClick={() => setRating(true)}>{mine ? "Change your rating" : "Rate this call"}</Button>
      )}
    </section>
  );
}
