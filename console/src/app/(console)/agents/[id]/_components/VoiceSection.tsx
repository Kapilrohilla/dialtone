"use client";

import { Play } from "lucide-react";
import { useRef, useState } from "react";
import { Button, Field } from "@/components/ui";
import { useVoices, type AgentUpdate } from "@/lib/queries";
import type { Agent } from "@/lib/types";
import styles from "./editor.module.css";

const PIPELINES: Record<string, string> = { "gemini-live": "Gemini Live", sarvam: "Sarvam", elevenlabs: "ElevenLabs" };

export const pipelineLabel = (pipeline: string) => PIPELINES[pipeline] ?? pipeline;

export type PanelSectionProps = {
  agent: Agent;
  readOnly: boolean;
  /** PATCHes `body`; `group` names what a failure belongs to (defaults to the fields sent). */
  save: (body: AgentUpdate, group?: string) => Promise<boolean>;
};

export function VoiceSection({ agent, readOnly, save }: PanelSectionProps) {
  const { data } = useVoices();
  const [persona, setPersona] = useState(agent.persona_name);
  const [voice, setVoice] = useState(agent.voice_id);
  const audio = useRef<HTMLAudioElement>(null);
  const sample = data?.voices.find((v) => v.id === voice)?.sample ?? null;

  function preview() {
    const el = audio.current;
    if (!el) return;
    el.currentTime = 0;
    el.play().catch(() => {
      // The browser refused to play (autoplay rules, missing file): nothing to show.
    });
  }

  return (
    <div className={styles.panelSection}>
      <h2 className={styles.panelTitle}>Voice</h2>
      <Field
        label="Agent's name"
        value={persona}
        maxLength={60}
        readOnly={readOnly}
        onChange={(e) => setPersona(e.target.value)}
        onBlur={() => {
          const next = persona.trim();
          if (next !== agent.persona_name) void save({ persona_name: next });
        }}
      />
      <Field
        control="select"
        label="Voice"
        value={voice}
        disabled={readOnly}
        onChange={(e) => {
          setVoice(e.target.value);
          void save({ voice_id: e.target.value });
        }}
      >
        <option value="">Default for this line</option>
        {data?.voices.map((v) => (
          <option key={v.id} value={v.id}>{`${v.name}, ${v.description}`}</option>
        ))}
      </Field>
      {sample && (
        <>
          <Button onClick={preview} className={styles.preview}>
            <Play size={16} strokeWidth={1.75} aria-hidden="true" />
            Preview
          </Button>
          <audio ref={audio} src={sample} preload="none" />
        </>
      )}
      {data && <p className={styles.panelNote}>Voices for {pipelineLabel(data.pipeline)}.</p>}
    </div>
  );
}
