"use client";

import Link from "next/link";
import { useState } from "react";
import { Button, Dialog, StateBlock } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useKnowledgeList } from "@/lib/queries";
import styles from "./editor.module.css";

export type AttachKnowledgeDialogProps = {
  open: boolean;
  /** The ids linked now; they start checked. */
  selected: number[];
  onClose: () => void;
  onSave: (ids: number[]) => void;
};

export function AttachKnowledgeDialog({ open, ...rest }: AttachKnowledgeDialogProps) {
  return open ? <AttachForm {...rest} /> : null;
}

function AttachForm({ selected, onClose, onSave }: Omit<AttachKnowledgeDialogProps, "open">) {
  const { data: docs, isError, error, refetch } = useKnowledgeList();
  const [checked, setChecked] = useState(() => new Set(selected));

  function toggle(id: number) {
    const next = new Set(checked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChecked(next);
  }

  function save() {
    // Linked documents keep their order; newly checked ones follow in list order.
    const kept = selected.filter((id) => checked.has(id));
    const added = (docs ?? []).map((d) => d.id).filter((id) => checked.has(id) && !selected.includes(id));
    onSave([...kept, ...added]);
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="Attach knowledge"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={save} disabled={!docs}>Save</Button>
        </>
      }
    >
      {isError ? (
        <StateBlock state="error" title="Could not load documents" body={error instanceof ApiError ? error.detail : undefined} onRetry={() => refetch()} />
      ) : !docs ? (
        <StateBlock state="loading" title="Loading documents" />
      ) : docs.length === 0 ? (
        <StateBlock state="empty" title="No knowledge documents yet." action={<Link href="/knowledge" className={styles.link}>Open knowledge base</Link>} />
      ) : (
        <ul className={styles.checkList}>
          {docs.map((d) => (
            <li key={d.id}>
              <label className={styles.check}>
                <input type="checkbox" checked={checked.has(d.id)} onChange={() => toggle(d.id)} />
                {d.title}
              </label>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  );
}
