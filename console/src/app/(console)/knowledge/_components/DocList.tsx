import { Plus } from "lucide-react";
import { Button } from "@/components/ui";
import type { KnowledgeListItem } from "@/lib/types";
import styles from "../knowledge.module.css";

export const usedBy = (n: number) => (n === 0 ? "Not used by any agent" : `Used by ${n} agent${n === 1 ? "" : "s"}`);

type Props = { docs: KnowledgeListItem[]; selectedId: number | undefined; canEdit: boolean; creating: boolean; onSelect: (id: number) => void; onNew: () => void };

export function DocList({ docs, selectedId, canEdit, creating, onSelect, onNew }: Props) {
  return (
    <nav className={styles.list} aria-label="Documents">
      {canEdit && (
        <Button className={styles.newDoc} loading={creating} onClick={onNew}>
          <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
          New document
        </Button>
      )}
      {docs.map((d) => (
        <button key={d.id} type="button" className={styles.row} aria-current={d.id === selectedId} onClick={() => onSelect(d.id)}>
          <span className={styles.rowTitle}>{d.title}</span>
          <span className={styles.rowMeta}>{usedBy(d.used_by)}</span>
        </button>
      ))}
    </nav>
  );
}
