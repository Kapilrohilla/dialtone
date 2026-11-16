import { Plus, Trash2, X } from "lucide-react";
import { Button, Field, Switch } from "@/components/ui";
import { cleanCode, FIELD_TYPES, keyFromLabel, MAX_DESCRIPTION, MAX_FIELD_LABEL, MAX_FIELDS, MAX_ITEM_NAME } from "@/lib/dispositions";
import { OUTCOME_GROUPS } from "@/lib/outcomes";
import type { DispositionField, DispositionFieldType, DispositionItem, OutcomeGroup } from "@/lib/types";
import styles from "../dispositions.module.css";

export type ItemEditorProps = {
  item: DispositionItem;
  isFallback: boolean;
  error?: string;
  onChange: (next: DispositionItem) => void;
  onRemove: () => void;
  onDone: () => void;
};

/** The inline editor under a disposition's row. */
export function ItemEditor({ item, isFallback, error, onChange, onRemove, onDone }: ItemEditorProps) {
  const set = (patch: Partial<DispositionItem>) => onChange({ ...item, ...patch });
  const setField = (i: number, patch: Partial<DispositionField>) => set({ fields: item.fields.map((f, j) => (j === i ? { ...f, ...patch } : f)) });

  function setLabel(i: number, label: string) {
    const f = item.fields[i];
    // The key follows the label until someone types their own.
    const follows = f.key === "" || f.key === keyFromLabel(f.label);
    setField(i, follows ? { label, key: keyFromLabel(label) } : { label });
  }

  return (
    <div className={styles.itemEditor} role="group" aria-label={`Edit ${item.code || "new disposition"}`}>
      <p className={styles.editingHead}>
        Editing <span className="mono">{item.code || "new disposition"}</span>
      </p>
      <div className={styles.grid2}>
        <Field label="Code" className={styles.monoField} value={item.code} maxLength={32} autoFocus={!item.code} onChange={(e) => set({ code: cleanCode(e.target.value) })} hint="Capital letters, digits and _." />
        <Field label="Name" value={item.name} maxLength={MAX_ITEM_NAME} onChange={(e) => set({ name: e.target.value })} />
      </div>
      <Field
        control="textarea"
        label="Description"
        rows={3}
        value={item.description}
        maxLength={MAX_DESCRIPTION}
        hint="Written for the AI and for telecallers. Say exactly when to use it."
        onChange={(e) => set({ description: e.target.value })}
      />
      <div className={styles.grid2}>
        <Field control="select" label="Report group" value={item.group} onChange={(e) => set({ group: e.target.value as OutcomeGroup })}>
          {OUTCOME_GROUPS.map((g) => (
            <option key={g} value={g}>{g}</option>
          ))}
        </Field>
        <fieldset className={styles.capture}>
          <legend className={styles.captureLegend}>Capture with this disposition</legend>
          {item.fields.length === 0 && <p className={styles.mutedSmall}>Nothing extra is captured.</p>}
          {item.fields.map((f, i) => (
            <div key={i} className={styles.fieldRow}>
              <Field label="Label" value={f.label} maxLength={MAX_FIELD_LABEL} onChange={(e) => setLabel(i, e.target.value)} />
              <Field label="Key" className={styles.monoField} value={f.key} maxLength={32} onChange={(e) => setField(i, { key: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "") })} />
              <Field control="select" label="Type" value={f.type} onChange={(e) => setField(i, { type: e.target.value as DispositionFieldType })}>
                {FIELD_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </Field>
              <div className={styles.fieldRowEnd}>
                <Switch label="Required" checked={f.required} onChange={(required) => setField(i, { required })} />
                <button
                  type="button"
                  className={styles.iconButton}
                  aria-label={`Remove field ${f.label || i + 1}`}
                  onClick={() => set({ fields: item.fields.filter((_, j) => j !== i) })}
                >
                  <X size={16} strokeWidth={1.75} aria-hidden="true" />
                </button>
              </div>
            </div>
          ))}
          {item.fields.length < MAX_FIELDS && (
            <button
              type="button"
              className={styles.textButton}
              onClick={() => set({ fields: [...item.fields, { key: "", label: "", type: "text", required: false }] })}
            >
              <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
              Add field to capture
            </button>
          )}
        </fieldset>
      </div>
      {error && <p role="alert" className={styles.error}>{error}</p>}
      <div className={styles.editorFooter}>
        <Button variant="text" className={styles.danger} disabled={isFallback} title={isFallback ? "Set another disposition as the fallback first." : undefined} onClick={onRemove}>
          <Trash2 size={16} strokeWidth={1.75} aria-hidden="true" />
          Remove
        </Button>
        <Button onClick={onDone}>Done</Button>
      </div>
    </div>
  );
}
