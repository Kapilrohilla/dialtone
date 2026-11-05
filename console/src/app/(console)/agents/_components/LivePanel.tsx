"use client";

import Link from "next/link";
import { Button, Chip, Panel } from "@/components/ui";
import { formatPhone } from "@/lib/format";
import type { AgentListItem } from "@/lib/types";
import styles from "./agents.module.css";

export type LivePanelProps = {
  loading: boolean;
  live: AgentListItem | undefined;
  callsToday: number | undefined;
  canEdit: boolean;
  onUnpublish: () => void;
};

export function LivePanel({ loading, live, callsToday, canEdit, onUnpublish }: LivePanelProps) {
  if (loading) {
    return (
      <Panel aria-label="Answering calls now" className={styles.live}>
        <span className={styles.skeleton} style={{ width: 320, height: 28 }} aria-hidden="true" />
      </Panel>
    );
  }
  if (!live) {
    return (
      <Panel aria-label="Answering calls now" className={styles.live}>
        <span className={styles.muted}>No agent is answering calls. Callers hear the built-in script.</span>
      </Panel>
    );
  }
  return (
    <Panel aria-label="Answering calls now" className={styles.live}>
      <div className={styles.liveHead}>
        <span className={styles.liveLabel}>Answering calls now</span>
        <div className={styles.liveMain}>
          <span className={styles.liveName}>{live.name}</span>
          <Chip tone="ok">Live</Chip>
          <span className={styles.mono}>{formatPhone(live.phone_number)}</span>
        </div>
      </div>
      <div className={styles.liveStat}>
        <span className={styles.muted}>Calls today</span>
        <span className={styles.liveNumber}>{callsToday ?? "—"}</span>
      </div>
      <div className={styles.liveActions}>
        {canEdit && <Button onClick={onUnpublish}>Unpublish</Button>}
        <Link href={`/agents/${live.id}`} className={styles.link}>Open</Link>
      </div>
    </Panel>
  );
}
