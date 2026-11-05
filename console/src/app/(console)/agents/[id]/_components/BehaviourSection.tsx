"use client";

import { useState } from "react";
import { Switch } from "@/components/ui";
import type { PanelSectionProps } from "./VoiceSection";
import styles from "./editor.module.css";

export function BehaviourSection({ agent, readOnly, save }: PanelSectionProps) {
  const [mood, setMood] = useState(agent.settings.mood_adaptation);
  const [checkIn, setCheckIn] = useState(agent.settings.dead_air.enabled);
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
    </div>
  );
}
