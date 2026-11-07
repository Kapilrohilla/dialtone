"use client";

import Link from "next/link";
import { useState } from "react";
import { Switch } from "@/components/ui";
import { useMe, useWorkflows } from "@/lib/queries";
import type { PanelSectionProps } from "./VoiceSection";
import styles from "./editor.module.css";

export function BehaviourSection({ agent, readOnly, save }: PanelSectionProps) {
  const [mood, setMood] = useState(agent.settings.mood_adaptation);
  const [checkIn, setCheckIn] = useState(agent.settings.dead_air.enabled);
  const { data: me } = useMe();
  const { data: workflows } = useWorkflows();
  // Check-ins need the account, the workflow and this agent all on: say which one keeps them off.
  const accountOff = me?.workspace.dead_air_enabled === false;
  const workflow = workflows?.find((w) => w.id === agent.workflow);
  const workflowOff = workflow?.dead_air_enabled === false;
  return (
    <div className={styles.panelSection}>
      <h2 className={styles.panelTitle}>Behaviour</h2>
      <Switch
        label="Adjust to caller's mood"
        checked={mood}
        disabled={readOnly}
        onChange={(next) => {
          setMood(next);
          void save({ settings: { mood_adaptation: next } }, "mood");
        }}
      />
      <Switch
        label="Check in when the caller goes quiet"
        checked={checkIn}
        disabled={readOnly}
        onChange={(next) => {
          setCheckIn(next);
          void save({ settings: { dead_air: { enabled: next } } }, "check-in");
        }}
      />
      {checkIn && accountOff ? (
        <p className={styles.panelNote}>
          Off for the whole account, so this agent won&apos;t check in. Change it in <Link href="/settings/calls">Settings</Link>.
        </p>
      ) : checkIn && workflow && workflowOff ? (
        <p className={styles.panelNote}>Off in the workflow &quot;{workflow.name}&quot;, so this agent won&apos;t check in.</p>
      ) : null}
    </div>
  );
}
