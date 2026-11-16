"use client";

import { Info } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Field } from "@/components/ui";
import { useDispositionLists } from "@/lib/queries";
import type { PanelSectionProps } from "./VoiceSection";
import styles from "./editor.module.css";

/** The disposition list the AI picks the call's outcome from. No list: the agent records no disposition. */
export function DispositionSection({ agent, readOnly, save }: PanelSectionProps) {
  const { data: lists } = useDispositionLists();
  const [listId, setListId] = useState<number | null>(agent.disposition_list ?? null);
  const attached = lists?.find((l) => l.id === listId);

  return (
    <div className={styles.panelSection}>
      <h2 className={styles.panelTitle}>Disposition list</h2>
      <Field
        control="select"
        label="Disposition list"
        value={listId === null ? "" : String(listId)}
        disabled={readOnly}
        onChange={(e) => {
          const next = e.target.value ? Number(e.target.value) : null;
          setListId(next);
          void save({ disposition_list: next });
        }}
      >
        <option value="">No list</option>
        {listId !== null && lists && !attached && <option value={String(listId)}>A list you can&rsquo;t see</option>}
        {lists?.map((l) => (
          <option key={l.id} value={l.id}>{l.name}</option>
        ))}
      </Field>
      {listId !== null ? (
        <div className={styles.panelHead}>
          <p className={styles.panelNote}>
            The AI picks one of these at the end of each call.
            {attached ? ` ${attached.items.length} disposition${attached.items.length === 1 ? "" : "s"}.` : ""}
          </p>
          <Link href={`/dispositions/${listId}`} className={styles.link}>Edit list</Link>
        </div>
      ) : (
        <div className={styles.dispositionCallout} role="note">
          <Info size={16} strokeWidth={1.75} aria-hidden="true" />
          <p>
            This agent doesn&rsquo;t record dispositions. Attach a list to capture the outcome of each call.{" "}
            <Link href="/dispositions" className={styles.link}>Create a list</Link>
          </p>
        </div>
      )}
    </div>
  );
}
