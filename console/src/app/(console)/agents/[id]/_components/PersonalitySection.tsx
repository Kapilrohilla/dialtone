"use client";

import { Play, Sparkles } from "lucide-react";
import { useRef, useState } from "react";
import { Button, Chip, Disclosure, Field, Segmented, Switch } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { usePersonalityPresets, useSimulate, useVoices, type AgentUpdate } from "@/lib/queries";
import type { AddressStyle, AgentPersonality, Backchannels, PersonalityPreset, SelfGender, Verbosity } from "@/lib/types";
import {
  CUSTOM,
  MAX_AVOID_PHRASES,
  MAX_DESCRIPTION_CHARS,
  MAX_PACE,
  MAX_PHRASE_CHARS,
  MAX_SIGNATURE_PHRASES,
  MIN_PACE,
  TRAITS,
  applyChange,
  choosePreset,
  closestPreset,
  genderMismatch,
  parsePhrases,
  spokenVoice,
} from "./personality";
import type { PanelSectionProps } from "./VoiceSection";
import styles from "./editor.module.css";

/** All personality saves share one group, so they land in the order made. */
export const PERSONALITY_GROUP = "personality";

const ADDRESS: { value: AddressStyle; label: string }[] = [
  { value: "sir_maam", label: "Sir/Ma'am" },
  { value: "ji", label: "Ji" },
  { value: "first_name", label: "Name" },
  { value: "none", label: "None" },
];
const BACKCHANNELS: { value: Backchannels; label: string }[] = [
  { value: "minimal", label: "Few" },
  { value: "natural", label: "Natural" },
  { value: "expressive", label: "Lots" },
];
const VERBOSITY: { value: Verbosity; label: string }[] = [
  { value: "brief", label: "Brief" },
  { value: "normal", label: "Normal" },
  { value: "explanatory", label: "Explains" },
];
const GENDER_WORD = { female: "Female", male: "Male", neutral: "Neutral" } as const;

/** The caller turn "Try a line" answers, after the agent's opening. */
export const SAMPLE_CALLER_TURN = "Haan ji, bataiye. Deposit kitna lagta hai? Thoda doubt hai mujhe.";

const roundPace = (n: number) => Math.round(n * 100) / 100;

export function PersonalitySection({ agent, readOnly, save }: PanelSectionProps) {
  const { data: presets } = usePersonalityPresets();
  const { data: voices } = useVoices();
  const [p, setP] = useState<AgentPersonality>(agent.personality);
  const [signature, setSignature] = useState(agent.personality.signature_phrases.join("\n"));
  const [avoid, setAvoid] = useState(agent.personality.avoid_phrases.join("\n"));
  const [description, setDescription] = useState(agent.personality.description);
  const voice = spokenVoice(agent, voices?.voices);
  const autoGender = voice?.gender ?? agent.personality.resolved_gender ?? "female";
  const mismatch = genderMismatch(p.self_gender, voice);
  const base = presets ? closestPreset(p, presets) : undefined;

  function commit(change: Partial<AgentPersonality>, body: AgentUpdate["personality"] = change) {
    setP((current) => applyChange(current, change, presets ?? []));
    void save({ personality: body }, PERSONALITY_GROUP);
  }

  function pick(preset: PersonalityPreset) {
    const next = choosePreset(p, preset);
    setP(next);
    setSignature(next.signature_phrases.join("\n"));
    void save({ personality: { preset: preset.id } }, PERSONALITY_GROUP);
  }

  function savePhrases(key: "signature_phrases" | "avoid_phrases", text: string) {
    const phrases = parsePhrases(text);
    if (JSON.stringify(phrases) === JSON.stringify(p[key])) return;
    commit(key === "signature_phrases" ? { signature_phrases: phrases } : { avoid_phrases: phrases });
  }

  return (
    <div className={styles.panelSection}>
      <div className={styles.panelHead}>
        <h2 className={styles.panelTitle}>Personality</h2>
        {p.preset === CUSTOM && <Chip tone="blue">Custom</Chip>}
      </div>
      <fieldset className={styles.personality} disabled={readOnly}>
        <legend className={styles.srOnly}>Personality</legend>
        <div role="radiogroup" aria-label="Personality preset" className={styles.presets}>
          {presets?.map((preset) => (
            <button
              key={preset.id}
              type="button"
              role="radio"
              aria-checked={p.preset === preset.id}
              className={styles.presetCard}
              onClick={() => pick(preset)}
            >
              <span className={styles.presetName}>{preset.name}</span>
              <span className={styles.presetSummary}>{preset.summary}</span>
              <span className={styles.presetSample}>&ldquo;{preset.sample}&rdquo;</span>
            </button>
          ))}
        </div>
        {p.preset === CUSTOM && base && (
          <Button size="sm" variant="text" className={styles.preview} onClick={() => pick(base)}>
            Reset to {base.name}
          </Button>
        )}

        <Field
          control="select"
          label="Speaks as"
          value={p.self_gender}
          error={mismatch}
          hint={p.self_gender === "auto" ? "Follows the voice: the agent talks about itself to match it." : undefined}
          onChange={(e) => commit({ self_gender: e.target.value as SelfGender })}
        >
          <option value="auto">{`Auto (${GENDER_WORD[autoGender]}${voice ? `, from voice ${voice.name}` : ""})`}</option>
          <option value="female">Female</option>
          <option value="male">Male</option>
          <option value="neutral">Neutral (no gendered words)</option>
        </Field>

        <Disclosure title="Fine-tune">
          <div className={styles.advanced}>
            {TRAITS.map((t) => (
              <label key={t.key} className={styles.trait} title={t.help}>
                <span className={styles.readOnlyLabel}>{t.label}</span>
                <input
                  type="range"
                  min={1}
                  max={5}
                  step={1}
                  value={p.traits[t.key]}
                  aria-valuetext={`${p.traits[t.key]} of 5`}
                  onChange={(e) => commit({ traits: { ...p.traits, [t.key]: Number(e.target.value) } }, { traits: { [t.key]: Number(e.target.value) } })}
                />
                <span className={styles.traitEnds} aria-hidden="true">
                  <span>{t.low}</span>
                  <span>{t.high}</span>
                </span>
              </label>
            ))}

            <div className={styles.readOnlyField}>
              <span className={styles.readOnlyLabel}>Calls the driver</span>
              <Segmented label="Calls the driver" options={ADDRESS} value={p.address_style} onChange={(v) => !readOnly && commit({ address_style: v })} />
              {p.address_style === "first_name" && <p className={styles.panelNote}>Uses the lead&apos;s name, or &quot;ji&quot; when there is none.</p>}
            </div>
            <div className={styles.readOnlyField}>
              <span className={styles.readOnlyLabel}>Reactions (&quot;achha&quot;, &quot;haan ji&quot;)</span>
              <Segmented label="Reactions" options={BACKCHANNELS} value={p.backchannels} onChange={(v) => !readOnly && commit({ backchannels: v })} />
            </div>
            <div className={styles.readOnlyField}>
              <span className={styles.readOnlyLabel}>Reply length</span>
              <Segmented label="Reply length" options={VERBOSITY} value={p.verbosity} onChange={(v) => !readOnly && commit({ verbosity: v })} />
            </div>
            <Switch
              label={'Thinking sounds ("hmm", "ek second")'}
              checked={p.disfluencies}
              disabled={readOnly}
              onChange={(next) => commit({ disfluencies: next })}
            />
            <Field
              control="textarea"
              rows={3}
              label="Favourite phrases"
              hint={`One per line, up to ${MAX_SIGNATURE_PHRASES}, ${MAX_PHRASE_CHARS} characters each. Used now and then.`}
              value={signature}
              onChange={(e) => setSignature(e.target.value)}
              onBlur={() => savePhrases("signature_phrases", signature)}
            />
            <Field
              control="textarea"
              rows={3}
              label="Never say"
              hint={`One per line, up to ${MAX_AVOID_PHRASES}.`}
              value={avoid}
              onChange={(e) => setAvoid(e.target.value)}
              onBlur={() => savePhrases("avoid_phrases", avoid)}
            />
            <Field
              control="textarea"
              rows={3}
              label="Character"
              maxLength={MAX_DESCRIPTION_CHARS}
              hint={`${description.length}/${MAX_DESCRIPTION_CHARS}. E.g. "Ex-driver, talks like a friendly bhaiya from Delhi." Never overrides the call rules.`}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              onBlur={() => {
                const next = description.trim();
                if (next !== p.description) commit({ description: next });
              }}
            />
            <PaceControl pace={p.pace} sample={voice?.sample ?? null} pipeline={voices?.pipeline} onChange={(pace) => commit({ pace })} />
          </div>
        </Disclosure>
      </fieldset>
      <TryALine agentId={agent.id} />
    </div>
  );
}

function PaceControl({ pace, sample, pipeline, onChange }: { pace: number; sample: string | null; pipeline?: string; onChange: (pace: number) => void }) {
  const audio = useRef<HTMLAudioElement>(null);
  function play() {
    const el = audio.current;
    if (!el) return;
    el.currentTime = 0;
    el.playbackRate = pace;
    el.play().catch(() => {
      // The browser refused to play: nothing to show.
    });
  }
  return (
    <div className={styles.readOnlyField}>
      <label className={styles.trait}>
        <span className={styles.readOnlyLabel}>Speaking pace ({pace.toFixed(2)}×)</span>
        <input type="range" min={MIN_PACE} max={MAX_PACE} step={0.05} value={pace} onChange={(e) => onChange(roundPace(Number(e.target.value)))} />
        <span className={styles.traitEnds} aria-hidden="true">
          <span>Relaxed</span>
          <span>Brisk</span>
        </span>
      </label>
      {pipeline === "gemini-live" && <p className={styles.panelNote}>Gemini Live sets its own speed; the agent is told the pace instead.</p>}
      {sample && (
        <>
          <Button size="sm" onClick={play} className={styles.preview}>
            <Play size={16} strokeWidth={1.75} aria-hidden="true" />
            Play sample
          </Button>
          <audio ref={audio} src={sample} preload="none" />
        </>
      )}
    </div>
  );
}

/** Two sample replies from the draft in the text simulator: the opening, then an answer to a sample question. */
function TryALine({ agentId }: { agentId: number }) {
  const sim = useSimulate("agent", agentId);
  const [lines, setLines] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setError(null);
    setLines([]);
    try {
      const first = await sim.mutateAsync({ messages: [], state: null });
      setLines([first.reply]);
      const second = await sim.mutateAsync({
        messages: [
          { role: "agent", text: first.reply },
          { role: "caller", text: SAMPLE_CALLER_TURN },
        ],
        state: first.state,
      });
      setLines([first.reply, second.reply]);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Couldn't try a line. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.readOnlyField}>
      <Button size="sm" className={styles.preview} loading={busy} onClick={() => void run()}>
        <Sparkles size={16} strokeWidth={1.75} aria-hidden="true" />
        Try a line
      </Button>
      {lines.length > 0 && (
        <ol className={styles.tryLines} aria-label="Sample replies">
          <li><span className={styles.tryWho}>Agent</span> {lines[0]}</li>
          {lines.length > 1 && (
            <>
              <li><span className={styles.tryWho}>Caller</span> {SAMPLE_CALLER_TURN}</li>
              <li><span className={styles.tryWho}>Agent</span> {lines[1]}</li>
            </>
          )}
        </ol>
      )}
      {error && <p role="alert" className={styles.fieldError}>{error}</p>}
      <p className={styles.panelNote}>Uses the saved draft. For the full experience, run a voice test.</p>
    </div>
  );
}
