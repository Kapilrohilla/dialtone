import type { GapStats, ResponseGap } from "@/lib/types";
import styles from "../calls.module.css";

const secs = (ms: number | undefined) => (ms == null ? "—" : `${(ms / 1000).toFixed(1)} s`);
const stats = (s: GapStats) => `${secs(s.avg_ms)} avg · ${secs(s.p95_ms)} p95 · ${secs(s.max_ms)} worst`;

/** How long the caller waited for each reply: from when they stopped speaking until the agent was heard. */
export function ResponseTimeSection({ gap }: { gap: ResponseGap | null }) {
  if (!gap) return null;
  return (
    <section aria-labelledby="call-response">
      <h3 id="call-response" className={styles.sectionTitle}>Response time</h3>
      {gap.n === 0 ? (
        <p className={styles.para}>No replies to measure on this call.</p>
      ) : (
        <dl className={styles.answers}>
          <div className={styles.pair}>
            <dt title="From when the caller stopped speaking until the agent's reply was audible">Heard by caller</dt>
            <dd>{stats(gap.perceived)}</dd>
          </div>
          <div className={styles.pair}>
            <dt title="Until the agent's audio started; leaves out silence at the start of a line, such as a pause cue">
              Without opening pauses
            </dt>
            <dd>{stats(gap.system)}</dd>
          </div>
          <div className={styles.pair}>
            <dt>Slow replies</dt>
            <dd>
              {gap.slow_replies} of {gap.n} over {secs(gap.slow_threshold_ms)}
            </dd>
          </div>
          <div className={styles.pair}>
            <dt title="The agent started talking while the caller was still speaking">Agent cut in</dt>
            <dd>{gap.agent_cut_ins === 1 ? "1 time" : `${gap.agent_cut_ins} times`}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}
