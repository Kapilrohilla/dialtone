import type { Agent, AgentPersonality, PersonalityPreset, PersonalityPresetValues, PersonalityTrait, Voice } from "@/lib/types";

/** Mirrors server/voiceagents/personality.py (KAP-41). */
export const CUSTOM = "custom";
export const MAX_SIGNATURE_PHRASES = 5;
export const MAX_AVOID_PHRASES = 10;
export const MAX_PHRASE_CHARS = 60;
export const MAX_DESCRIPTION_CHARS = 600;
export const MIN_PACE = 0.85;
export const MAX_PACE = 1.15;

/** Each trait with its plain-words ends (1 … 5) and a tooltip. */
export const TRAITS: { key: PersonalityTrait; label: string; low: string; high: string; help: string }[] = [
  { key: "warmth", label: "Warmth", low: "Reserved", high: "Warm", help: "How friendly and caring the agent sounds." },
  { key: "energy", label: "Energy", low: "Calm", high: "Energetic", help: "How lively and enthusiastic the agent sounds." },
  { key: "formality", label: "Formality", low: "Casual", high: "Formal", help: "Casual everyday Hinglish, or polite and formal." },
  { key: "humour", label: "Humour", low: "Serious", high: "Playful", help: "Whether the agent makes light jokes. Always dropped for upset callers." },
  { key: "directness", label: "Directness", low: "Gentle", high: "Direct", help: "Softens questions, or gets straight to the point." },
  { key: "empathy", label: "Empathy", low: "Matter-of-fact", high: "Empathetic", help: "How much the agent acknowledges the caller's situation." },
];

const PRESET_FIELDS = ["traits", "address_style", "backchannels", "disfluencies", "verbosity", "pace", "signature_phrases"] as const;

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** True when the personality's preset values are exactly `preset`'s. */
export function matchesPreset(p: PersonalityPresetValues, preset: PersonalityPreset): boolean {
  return PRESET_FIELDS.every((f) => (f === "traits" ? traitsMatch(p, preset) : same(p[f], preset.values[f])));
}

function traitsMatch(p: PersonalityPresetValues, preset: PersonalityPreset) {
  return TRAITS.every(({ key }) => p.traits[key] === preset.values.traits[key]);
}

/** The preset a custom personality is closest to: the one sharing the most values (the first on a tie). */
export function closestPreset(p: AgentPersonality, presets: PersonalityPreset[]): PersonalityPreset | undefined {
  if (p.preset !== CUSTOM) return presets.find((x) => x.id === p.preset);
  let best: PersonalityPreset | undefined;
  let bestScore = -1;
  for (const preset of presets) {
    const traitScore = TRAITS.filter(({ key }) => p.traits[key] === preset.values.traits[key]).length;
    const fieldScore = PRESET_FIELDS.filter((f) => f !== "traits" && same(p[f], preset.values[f])).length;
    if (traitScore + fieldScore > bestScore) {
      best = preset;
      bestScore = traitScore + fieldScore;
    }
  }
  return best;
}

/** `p` with `change` applied, and the preset label the server would give it ("custom" once it differs). */
export function applyChange(p: AgentPersonality, change: Partial<AgentPersonality>, presets: PersonalityPreset[]): AgentPersonality {
  const next = { ...p, ...change, traits: { ...p.traits, ...change.traits } };
  if (next.preset !== CUSTOM) {
    const preset = presets.find((x) => x.id === next.preset);
    if (!preset || !matchesPreset(next, preset)) next.preset = CUSTOM;
  }
  return next;
}

/** `p` with a preset's values chosen; the agent's own values (gender, avoided phrases, description) stay. */
export function choosePreset(p: AgentPersonality, preset: PersonalityPreset): AgentPersonality {
  return { ...p, ...structuredClone(preset.values), preset: preset.id };
}

/** The voice a call speaks with: the chosen one, else the line's default (the first of the catalog). */
export function spokenVoice(agent: Pick<Agent, "voice_id">, voices: Voice[] | undefined): Voice | undefined {
  return voices?.find((v) => v.id === agent.voice_id) ?? voices?.[0];
}

/** A warning when the gender the agent speaks as conflicts with its voice; null when they agree. */
export function genderMismatch(selfGender: AgentPersonality["self_gender"], voice: Voice | undefined): string | null {
  if (!voice?.gender || (selfGender !== "female" && selfGender !== "male") || selfGender === voice.gender) return null;
  return `The voice ${voice.name} is ${voice.gender}, but the agent speaks as ${selfGender === "male" ? "a man" : "a woman"}. Callers will notice.`;
}

/** Phrases from a "one per line" text box: trimmed, no blanks or repeats. */
export function parsePhrases(text: string): string[] {
  return [...new Set(text.split("\n").map((s) => s.trim().replace(/^"|"$/g, "").trim()).filter(Boolean))];
}
