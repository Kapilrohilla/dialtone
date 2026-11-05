"use client";

import { useId, useState } from "react";
import { Disclosure, Field } from "@/components/ui";
import { useVoices } from "@/lib/queries";
import type { AgentSettings } from "@/lib/types";
import { groupOf, TIMINGS_GROUP } from "./useAgentSaves";
import { pipelineLabel, type MarkInvalid, type PanelSectionProps } from "./VoiceSection";
import styles from "./editor.module.css";

type Timing = "nudge_s" | "second_nudge_s" | "hang_up_s";
const TIMINGS: { key: Timing; label: string }[] = [
  { key: "nudge_s", label: "First check-in after (s)" },
  { key: "second_nudge_s", label: "Second check-in after (s)" },
  { key: "hang_up_s", label: "Hang up after (s)" },
];

const asText = (d: AgentSettings["dead_air"]) => ({ nudge_s: String(d.nudge_s), second_nudge_s: String(d.second_nudge_s), hang_up_s: String(d.hang_up_s) });

export type AdvancedSectionProps = PanelSectionProps & {
  /** The timings' error (the server's, or "Use whole seconds."), shown under them. */
  timingsError?: string | null;
  markInvalid: MarkInvalid;
};

export function AdvancedSection({ agent, readOnly, save, timingsError, markInvalid }: AdvancedSectionProps) {
  const { data: voices } = useVoices();
  const [phone, setPhone] = useState(agent.phone_number);
  const [description, setDescription] = useState(agent.description);
  const [timings, setTimings] = useState(() => asText(agent.settings.dead_air));
  const errorId = useId();

  function commitTimings() {
    if (TIMINGS.some(({ key }) => !/^\d+$/.test(timings[key].trim()))) {
      markInvalid(TIMINGS_GROUP, "Use whole seconds.");
      return;
    }
    const saved = agent.settings.dead_air;
    const changed: Partial<Record<Timing, number>> = {};
    for (const { key } of TIMINGS) if (Number(timings[key]) !== saved[key]) changed[key] = Number(timings[key]);
    if (Object.keys(changed).length) void save({ settings: { dead_air: changed } }, TIMINGS_GROUP);
    else markInvalid(TIMINGS_GROUP, null);
  }

  const groupError = timingsError;

  return (
    <div className={styles.panelSection}>
      <Disclosure title="Advanced">
        <div className={styles.advanced}>
          <Field
            label="Phone number"
            className={styles.monoField}
            value={phone}
            maxLength={32}
            readOnly={readOnly}
            onChange={(e) => setPhone(e.target.value)}
            onBlur={() => {
              const next = phone.trim();
              // Back to the saved value: nothing to send, and an earlier failure no longer applies.
              if (next !== agent.phone_number) void save({ phone_number: next });
              else markInvalid(groupOf({ phone_number: next }), null);
            }}
          />
          <fieldset className={styles.timings} aria-describedby={groupError ? errorId : undefined}>
            <legend className={styles.legend}>Check-in timings</legend>
            {TIMINGS.map(({ key, label }) => (
              <Field
                key={key}
                label={label}
                type="number"
                min={1}
                step={1}
                inputMode="numeric"
                className={styles.monoField}
                value={timings[key]}
                readOnly={readOnly}
                onChange={(e) => setTimings({ ...timings, [key]: e.target.value })}
                onBlur={commitTimings}
              />
            ))}
            {groupError && <p id={errorId} role="alert" className={styles.fieldError}>{groupError}</p>}
          </fieldset>
          <div className={styles.readOnlyField}>
            <span className={styles.readOnlyLabel}>Pipeline</span>
            <span>{voices ? pipelineLabel(voices.pipeline) : "—"}</span>
          </div>
          <Field
            control="textarea"
            label="Description"
            value={description}
            maxLength={2000}
            readOnly={readOnly}
            onChange={(e) => setDescription(e.target.value)}
            onBlur={() => {
              if (description !== agent.description) void save({ description });
              else markInvalid(groupOf({ description }), null);
            }}
          />
        </div>
      </Disclosure>
    </div>
  );
}
