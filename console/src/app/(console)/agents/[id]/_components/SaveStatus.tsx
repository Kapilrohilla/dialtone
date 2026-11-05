import type { Autosave } from "@/lib/useAutosave";
import { TIMINGS_GROUP, type FieldSave } from "./useAgentSaves";

export type SaveStatusProps = { script: Autosave; field: FieldSave; signedOut: boolean };

/** Quiet top-bar text: "Saving…", "Saved", or why a save failed (while any group is failing). */
export function SaveStatus({ script, field, signedOut }: SaveStatusProps) {
  if (signedOut) return <span>Not saved</span>;
  if (script.status === "saving" || field.saving) return <span>Saving…</span>;
  if (script.status === "error") return <span role="alert">{script.error?.detail ?? "Not saved"}</span>;
  const failed = Object.entries(field.errors)[0];
  // The timings error is shown under the timings; the top bar only says it wasn't saved.
  if (failed) return <span role="alert">{failed[0] === TIMINGS_GROUP ? "Not saved" : failed[1].detail}</span>;
  if (script.status === "saved" || field.saved) return <span>Saved</span>;
  return null;
}
