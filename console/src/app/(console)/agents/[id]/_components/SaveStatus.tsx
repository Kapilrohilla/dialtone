import type { Autosave } from "@/lib/useAutosave";
import type { FieldSave } from "./useAgentSaves";

export type SaveStatusProps = { script: Autosave; field: FieldSave; signedOut: boolean };

/** Quiet top-bar text: "Saving…", "Saved", or why the last save failed. */
export function SaveStatus({ script, field, signedOut }: SaveStatusProps) {
  if (signedOut) return <span>Not saved</span>;
  if (script.status === "saving" || field.status === "saving") return <span>Saving…</span>;
  if (script.status === "error") return <span role="alert">{script.error?.detail ?? "Not saved"}</span>;
  if (field.status === "error") return <span role="alert">{field.inline ? "Not saved" : (field.error?.detail ?? "Not saved")}</span>;
  if (script.status === "saved" || field.status === "saved") return <span>Saved</span>;
  return null;
}
