"use client";

import { Play } from "lucide-react";
import { useRef, useState } from "react";
import { Button, Field } from "@/components/ui";
import { useVoices, type AgentUpdate } from "@/lib/queries";
import type { Agent, AgentTextSetting } from "@/lib/types";
import { groupOf } from "./useAgentSaves";
import styles from "./editor.module.css";

const PIPELINES: Record<string, string> = { "gemini-live": "Gemini Live", sarvam: "Sarvam", elevenlabs: "ElevenLabs" };

export const pipelineLabel = (pipeline: string) => PIPELINES[pipeline] ?? pipeline;

export type PanelSectionProps = {
  agent: Agent;
  readOnly: boolean;
  /** PATCHes `body`; `group` names what a failure belongs to (defaults to the fields sent). */
  save: (body: AgentUpdate, group?: string) => Promise<boolean>;
};

/** Clears (null) or sets a group's error without sending anything. */
export type MarkInvalid = (group: string, message: string | null) => void;

export function VoiceSection({ agent, readOnly, save, markInvalid }: PanelSectionProps & { markInvalid: MarkInvalid }) {
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
        hint="Optional. Leave blank and the agent won't give a name."
        readOnly={readOnly}
        onChange={(e) => setPersona(e.target.value)}
        onBlur={() => {
          const next = persona.trim();
          // Back to the saved value: nothing to send, and an earlier failure no longer applies.
          if (next !== agent.persona_name) void save({ persona_name: next });
          else markInvalid(groupOf({ persona_name: next }), null);
        }}
      />
      <TextSetting agent={agent} readOnly={readOnly} save={save} markInvalid={markInvalid} setting="name_pronunciation" label="How to say the agent's name" hint="Spelled as it sounds. Leave blank to use the name as written." />
      <TextSetting agent={agent} readOnly={readOnly} save={save} markInvalid={markInvalid} setting="company_name" label="Company name" hint="The company the agent says it calls from." />
      <TextSetting agent={agent} readOnly={readOnly} save={save} markInvalid={markInvalid} setting="consent_line" label="Consent line" control="textarea" hint="Said at the start of every call. Leave blank for none." />
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

/** One optional free-text setting, saved on its own when the field loses focus. Blank unsets it. */
function TextSetting({
  agent,
  readOnly,
  save,
  markInvalid,
  setting,
  label,
  hint,
  control,
}: PanelSectionProps & { markInvalid: MarkInvalid; setting: AgentTextSetting; label: string; hint: string; control?: "textarea" }) {
  const saved = agent.settings[setting] ?? "";
  const [value, setValue] = useState(saved);
  const onBlur = () => {
    const next = value.trim();
    // Back to the saved value: nothing to send, and an earlier failure no longer applies.
    if (next !== saved) void save({ settings: { [setting]: next } }, setting);
    else markInvalid(setting, null);
  };
  const common = { label, hint, value, readOnly, onBlur };
  return control === "textarea" ? (
    <Field {...common} control="textarea" rows={2} onChange={(e) => setValue(e.target.value)} />
  ) : (
    <Field {...common} onChange={(e) => setValue(e.target.value)} />
  );
}
