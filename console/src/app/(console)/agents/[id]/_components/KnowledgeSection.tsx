"use client";

import { Plus, X } from "lucide-react";
import { useState } from "react";
import { useKnowledgeList } from "@/lib/queries";
import { AttachKnowledgeDialog } from "./AttachKnowledgeDialog";
import type { PanelSectionProps } from "./VoiceSection";
import styles from "./editor.module.css";

export function KnowledgeSection({ agent, readOnly, save }: PanelSectionProps) {
  const { data: docs } = useKnowledgeList();
  const [ids, setIds] = useState(agent.knowledge);
  const [attaching, setAttaching] = useState(false);
  const titleOf = (id: number) => docs?.find((d) => d.id === id)?.title;

  function commit(next: number[]) {
    setIds(next);
    void save({ knowledge: next });
  }

  return (
    <div className={styles.panelSection}>
      <div className={styles.panelHead}>
        <h2 className={styles.panelTitle}>Knowledge</h2>
        {!readOnly && (
          <button type="button" className={styles.textButton} onClick={() => setAttaching(true)}>
            <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
            Attach
          </button>
        )}
      </div>
      {ids.length === 0 ? (
        <p className={styles.panelNote}>No documents linked.</p>
      ) : !docs ? (
        <p className={styles.panelNote}>Loading documents…</p>
      ) : (
        <ul aria-label="Linked documents" className={styles.docList}>
          {ids.map((id) => {
            const title = titleOf(id) ?? "A document you can't see";
            return (
              <li key={id} className={styles.docRow}>
                <span className={styles.docTitle}>{title}</span>
                {!readOnly && (
                  <button type="button" className={styles.iconButton} aria-label={`Remove ${title}`} onClick={() => commit(ids.filter((x) => x !== id))}>
                    <X size={16} strokeWidth={1.75} aria-hidden="true" />
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <p className={styles.panelNote}>The agent only quotes what is written in these documents.</p>
      <AttachKnowledgeDialog
        open={attaching}
        selected={ids}
        onClose={() => setAttaching(false)}
        onSave={(next) => {
          setAttaching(false);
          commit(next);
        }}
      />
    </div>
  );
}
