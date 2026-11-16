import { useState } from "react";
import { Button, Chip, Dialog, Disclosure, Field, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { clockIn, formatCaptured, SOURCE_LABELS } from "@/lib/dispositions";
import { formatWhen } from "@/lib/format";
import { OUTCOME_GROUPS } from "@/lib/outcomes";
import { useChangeCallDisposition } from "@/lib/queries";
import type { CallDetail, DispositionChange, DispositionItem } from "@/lib/types";
import styles from "../calls.module.css";

/** The call's disposition: what was set, by whom, what was captured, every change, and (for editors) Change. */
export function DispositionSection({ call, canChange, timeZone }: { call: CallDetail; canChange: boolean; timeZone: string }) {
  const [changing, setChanging] = useState(false);
  const d = call.disposition ?? null;
  const options = call.disposition_options ?? null;
  const history = call.disposition_history ?? [];
  const changeButton =
    canChange && options ? (
      <Button size="sm" onClick={() => setChanging(true)}>Change</Button>
    ) : null;

  return (
    <section aria-labelledby="call-disposition">
      <h3 id="call-disposition" className={styles.sectionTitle}>Disposition</h3>
      <div className={styles.dispositionCard}>
        {d ? (
          <>
            <div className={styles.dispositionHead}>
              <span className={styles.dispositionName}>{d.name}</span>
              <Chip tone="blue" className="mono">{d.code}</Chip>
              <span className={styles.dispositionAction}>{changeButton}</span>
            </div>
            <p className={styles.dispositionMeta}>
              {`Set by ${d.source === "user" ? (d.set_by ?? "someone") : SOURCE_LABELS[d.source]}`}
              {d.set_at ? ` at ${clockIn(d.set_at, timeZone)}` : ""}
            </p>
            {d.reason && <p className={styles.para}>Reason: {d.reason}</p>}
            {d.fields.length > 0 && (
              <dl className={styles.answers}>
                {d.fields.map((f) => (
                  <div key={f.key} className={styles.pair}>
                    <dt>{f.label}</dt>
                    <dd className={f.type === "datetime" ? "mono" : undefined}>{f.value ? formatCaptured(f.value, f.type, timeZone) : "—"}</dd>
                  </div>
                ))}
              </dl>
            )}
          </>
        ) : (
          <div className={styles.dispositionHead}>
            <span className={styles.noDisposition}>
              {options ? "No disposition yet." : "No disposition — this agent has no disposition list."}
            </span>
            <span className={styles.dispositionAction}>{changeButton}</span>
          </div>
        )}
        {history.length > 0 && (
          <Disclosure title="History">
            <ol className={styles.history} aria-label="Disposition history">
              {history.map((h, i) => (
                <li key={i}>
                  <span>{historyText(h)}</span>
                  <span className={`${styles.historyAt} mono`}>{formatWhen(h.at, timeZone)}</span>
                </li>
              ))}
            </ol>
          </Disclosure>
        )}
      </div>
      {changing && options && (
        <ChangeDialog call={call} items={options.items} listName={options.list_name} onClose={() => setChanging(false)} />
      )}
    </section>
  );
}

export function historyText(h: DispositionChange): string {
  if (h.source === "ai") return `AI set ${h.code}`;
  if (h.source === "system") return `System set ${h.code}`;
  return `${h.by ?? "Someone"} changed to ${h.code}${h.note ? `: “${h.note}”` : ""}`;
}

/** A datetime-local input takes "YYYY-MM-DDTHH:MM". */
const toInput = (value: string, type: string) => (type === "datetime" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value) ? value.slice(0, 16) : value);

function ChangeDialog({ call, items, listName, onClose }: { call: CallDetail; items: DispositionItem[]; listName: string; onClose: () => void }) {
  const toast = useToast();
  const change = useChangeCallDisposition(call.room);
  const current = call.disposition ?? null;
  const [code, setCode] = useState(current && items.some((i) => i.code === current.code) ? current.code : (items[0]?.code ?? ""));
  const [note, setNote] = useState("");
  const [values, setValues] = useState<Record<string, string>>(() => seedValues(code));
  const [missing, setMissing] = useState<string[]>([]);
  const [serverErrors, setServerErrors] = useState<Record<string, string[]>>({});
  const item = items.find((i) => i.code === code);

  function seedValues(c: string): Record<string, string> {
    const it = items.find((i) => i.code === c);
    const out: Record<string, string> = {};
    for (const f of it?.fields ?? []) {
      const had = current?.code === c ? current.fields.find((x) => x.key === f.key)?.value : undefined;
      out[f.key] = had ? toInput(had, f.type) : "";
    }
    return out;
  }

  function pick(next: string) {
    setCode(next);
    setValues(seedValues(next));
    setMissing([]);
    setServerErrors({});
  }

  function submit() {
    if (!item) return;
    const empty = item.fields.filter((f) => f.required && !(values[f.key] ?? "").trim()).map((f) => f.key);
    setMissing(empty);
    if (empty.length) return;
    const fields = Object.fromEntries(item.fields.map((f) => [f.key, (values[f.key] ?? "").trim()]).filter(([, v]) => v !== ""));
    change.mutate(
      { code, note: note.trim(), fields },
      {
        onSuccess: () => {
          toast.show(`Disposition changed to ${item.name}.`, "ok");
          onClose();
        },
        onError: (e) => {
          if (e instanceof ApiError) setServerErrors(e.fields);
          else toast.show("Could not change the disposition.", "bad");
        },
      },
    );
  }

  const codeError = serverErrors.code?.[0];
  const otherErrors = Object.entries(serverErrors)
    .filter(([k]) => k !== "code")
    .flatMap(([, v]) => v);
  const detail = change.error instanceof ApiError && Object.keys(change.error.fields).length === 0 ? change.error.detail : null;

  return (
    <Dialog
      open
      onClose={onClose}
      title="Change disposition"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={change.isPending} disabled={!item} onClick={submit}>Save</Button>
        </>
      }
    >
      <div className={styles.changeForm}>
        <Field control="select" label="Disposition" value={code} error={codeError} hint={`From the list ${listName}.`} onChange={(e) => pick(e.target.value)}>
          {OUTCOME_GROUPS.map((group) => {
            const inGroup = items.filter((i) => i.group === group);
            return inGroup.length ? (
              <optgroup key={group} label={group}>
                {inGroup.map((i) => (
                  <option key={i.code} value={i.code}>{`${i.name} (${i.code})`}</option>
                ))}
              </optgroup>
            ) : null;
          })}
        </Field>
        {item?.description && <p className={styles.changeHint}>{item.description}</p>}
        {item?.fields.map((f) => (
          <Field
            key={`${code}-${f.key}`}
            label={f.required ? `${f.label} (required)` : f.label}
            type={f.type === "datetime" ? "datetime-local" : f.type === "number" ? "number" : "text"}
            required={f.required}
            value={values[f.key] ?? ""}
            error={missing.includes(f.key) ? "Required." : null}
            onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
          />
        ))}
        <Field control="textarea" label="Note" rows={3} maxLength={500} hint="Optional. Why you changed it." value={note} onChange={(e) => setNote(e.target.value)} />
        {(otherErrors.length > 0 || detail) && (
          <div role="alert" className={styles.changeError}>
            {[...otherErrors, ...(detail ? [detail] : [])].map((m) => (
              <p key={m}>{m}</p>
            ))}
          </div>
        )}
      </div>
    </Dialog>
  );
}
