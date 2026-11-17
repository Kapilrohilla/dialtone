import { OUTCOME_GROUPS } from "@/lib/outcomes";
import type { DispositionField, DispositionFieldType, DispositionItem, DispositionListRow, DispositionSource, OutcomeGroup } from "@/lib/types";

// The limits the server checks (server/dispositions); mirrored here so mistakes show while typing.
export const MAX_LIST_NAME = 80;
export const MAX_ITEMS = 30;
export const MAX_ITEM_NAME = 60;
export const MAX_DESCRIPTION = 300;
export const MAX_FIELDS = 5;
export const MAX_FIELD_LABEL = 40;
export const CODE_RE = /^[A-Z][A-Z0-9_]{0,31}$/;
export const FIELD_KEY_RE = /^[a-z][a-z0-9_]{0,31}$/;

export const FIELD_TYPES: { value: DispositionFieldType; label: string }[] = [
  { value: "text", label: "Text" },
  { value: "datetime", label: "Date and time" },
  { value: "number", label: "Number" },
];

export const fieldTypeLabel = (type: string) => FIELD_TYPES.find((t) => t.value === type)?.label.toLowerCase() ?? type;

/** What a person types into a code box: upper case, spaces and dashes as underscores, nothing else. */
export const cleanCode = (value: string) => value.toUpperCase().replace(/[\s-]+/g, "_").replace(/[^A-Z0-9_]/g, "").slice(0, 32);

/** "Callback time" → "callback_time". A key must start with a letter; "1st call" → "f_1st_call". */
export function keyFromLabel(label: string): string {
  const key = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 32);
  if (!key) return "";
  return /^[a-z]/.test(key) ? key : `f_${key}`.slice(0, 32);
}

/** One item as the agent's instructions put it: `CODE: Name. Description Capture: Label (required).` */
export function aiLine(item: DispositionItem): string {
  const name = item.name.trim().replace(/\.$/, "");
  const parts = [`${item.code}: ${name}.`];
  if (item.description.trim()) parts.push(item.description.trim());
  if (item.fields.length) parts.push(`Capture: ${item.fields.map((f) => `${f.label.trim()}${f.required ? " (required)" : ""}`).join(", ")}.`);
  return parts.join(" ");
}

export type ListDraft = { name: string; items: DispositionItem[]; fallback_code: string };

/** Problems with a draft list, in plain words: `list` for the list as a whole, else keyed by item index. */
export type DraftErrors = { name?: string; list?: string; items: Record<number, string> };

function fieldError(f: DispositionField, i: number, fields: DispositionField[]): string | null {
  const label = f.label.trim();
  if (!label) return "Each field to capture needs a label.";
  if (label.length > MAX_FIELD_LABEL) return `Keep field labels to ${MAX_FIELD_LABEL} characters.`;
  if (!FIELD_KEY_RE.test(f.key)) return `The key for "${label}" must start with a letter and use only a–z, 0–9 and _.`;
  if (fields.findIndex((g) => g.key === f.key) !== i) return `Two fields use the key ${f.key}.`;
  return null;
}

function itemError(item: DispositionItem, i: number, items: DispositionItem[]): string | null {
  if (!item.code) return "Give it a code.";
  if (!CODE_RE.test(item.code)) return "A code starts with a letter and uses only A–Z, 0–9 and _ (up to 32).";
  if (items.findIndex((x) => x.code === item.code) !== i) return `The code ${item.code} is used twice.`;
  const name = item.name.trim();
  if (!name) return "Give it a name.";
  if (name.length > MAX_ITEM_NAME) return `Keep the name to ${MAX_ITEM_NAME} characters.`;
  if (item.description.length > MAX_DESCRIPTION) return `Keep the description to ${MAX_DESCRIPTION} characters.`;
  if (!OUTCOME_GROUPS.includes(item.group)) return "Choose a report group.";
  if (item.fields.length > MAX_FIELDS) return `Capture up to ${MAX_FIELDS} fields.`;
  for (const [j, f] of item.fields.entries()) {
    const e = fieldError(f, j, item.fields);
    if (e) return e;
  }
  return null;
}

export function draftErrors(d: ListDraft): DraftErrors {
  const out: DraftErrors = { items: {} };
  const name = d.name.trim();
  if (!name) out.name = "Give the list a name.";
  else if (name.length > MAX_LIST_NAME) out.name = `Keep the name to ${MAX_LIST_NAME} characters.`;
  if (d.items.length === 0) out.list = "A list needs at least one disposition.";
  else if (d.items.length > MAX_ITEMS) out.list = `A list can have up to ${MAX_ITEMS} dispositions.`;
  else if (!d.items.some((x) => x.code === d.fallback_code)) out.list = "Choose a fallback disposition.";
  d.items.forEach((item, i) => {
    const e = itemError(item, i, d.items);
    if (e) out.items[i] = e;
  });
  return out;
}

export const hasErrors = (e: DraftErrors) => Boolean(e.name || e.list || Object.keys(e.items).length);

export type OutcomeOption = { code: string; group: OutcomeGroup; label: string };

/** Every code across the lists, the first list (by name) naming it winning. */
export function codesOf(lists: DispositionListRow[]): OutcomeOption[] {
  const seen = new Map<string, OutcomeOption>();
  for (const list of lists) for (const item of list.items) if (!seen.has(item.code)) seen.set(item.code, { code: item.code, group: item.group, label: item.name });
  return [...seen.values()];
}

export const SOURCE_LABELS: Record<DispositionSource, string> = { ai: "AI", system: "System", user: "Someone" };

/** A captured value: ISO dates and times in the person's time zone ("5 Nov 2026, 18:00"), anything else as typed. */
export function formatCaptured(value: string, type: string, tz: string): string {
  if (type !== "datetime" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value)) return value;
  // Without an offset (a datetime-local value) it is already wall-clock time: show it as written.
  const zoned = /(Z|[+-]\d{2}:?\d{2})$/.test(value);
  const at = new Date(zoned ? value : `${value}Z`);
  if (Number.isNaN(at.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: zoned ? tz : "UTC",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(at);
}

/** "14:32" in `tz`. */
export function clockIn(iso: string, tz: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  return new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", hour12: false }).format(at);
}
