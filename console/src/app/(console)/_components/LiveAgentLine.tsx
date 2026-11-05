import Link from "next/link";
import { Chip, Panel } from "@/components/ui";
import { formatPhone } from "@/lib/format";
import type { Dashboard } from "@/lib/types";
import styles from "./dashboard.module.css";

export function LiveAgentLine({ loading, agent }: { loading: boolean; agent?: Dashboard["live_agent"] }) {
  return (
    <Panel className={styles.agentLine} aria-label="Live agent">
      {loading ? (
        <span className={styles.skeleton} style={{ width: 280, height: 24 }} aria-hidden="true" />
      ) : agent ? (
        <>
          <span className={styles.agentName}>{agent.name}</span>
          <Chip tone="ok">Live</Chip>
          <span className={styles.mono}>{formatPhone(agent.phone_number)}</span>
          <Link href="/agents" className={styles.link}>Manage agents</Link>
        </>
      ) : (
        <>
          <span className={styles.reason}>No agent is answering calls.</span>
          <Link href="/agents" className={styles.link}>Publish an agent</Link>
        </>
      )}
    </Panel>
  );
}
