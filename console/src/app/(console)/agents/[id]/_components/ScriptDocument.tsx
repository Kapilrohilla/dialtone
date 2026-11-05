"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import { Button, Dialog, StateBlock } from "@/components/ui";
import type { Expression, ScriptSection } from "@/lib/types";
import { SectionEditor } from "./SectionEditor";
import styles from "./editor.module.css";

export type ScriptDocumentProps = {
  sections: ScriptSection[];
  onChange: (sections: ScriptSection[]) => void;
  readOnly: boolean;
  customExpressions: Record<string, string>;
  onCreateExpression: (name: string, hint: string) => void;
  builtins?: Expression[];
};

/** The script as one document: sections separated by thin rules, then "Add section". */
export function ScriptDocument({ sections, onChange, readOnly, customExpressions, onCreateExpression, builtins }: ScriptDocumentProps) {
  const [deleting, setDeleting] = useState<ScriptSection | null>(null);

  const replace = (i: number, s: ScriptSection) => onChange(sections.map((x, j) => (j === i ? s : x)));
  const remove = (id: string) => onChange(sections.filter((s) => s.id !== id));

  function move(i: number, by: -1 | 1) {
    const j = i + by;
    if (j < 0 || j >= sections.length) return;
    const next = [...sections];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  }

  function add() {
    onChange([...sections, { id: crypto.randomUUID(), title: "New section", body: "" }]);
  }

  return (
    <div className={styles.document}>
      {sections.length === 0 && (
        <StateBlock state="empty" title="No sections yet." body={readOnly ? undefined : "Add a section to start the script."} />
      )}
      {sections.map((s, i) => (
        <SectionEditor
          key={s.id}
          section={s}
          index={i}
          count={sections.length}
          readOnly={readOnly}
          customExpressions={customExpressions}
          onCreateExpression={onCreateExpression}
          builtins={builtins}
          onChange={(next) => replace(i, next)}
          onMove={(by) => move(i, by)}
          onDelete={() => (s.body.trim() ? setDeleting(s) : remove(s.id))}
        />
      ))}
      {!readOnly && (
        <button type="button" className={styles.addSection} onClick={add}>
          <Plus size={18} strokeWidth={1.75} aria-hidden="true" />
          Add section
        </button>
      )}
      <Dialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        title={`Delete ${deleting?.title.trim() || "this section"}?`}
        footer={
          <>
            <Button onClick={() => setDeleting(null)}>Cancel</Button>
            <Button
              variant="danger"
              onClick={() => {
                if (deleting) remove(deleting.id);
                setDeleting(null);
              }}
            >
              Delete
            </Button>
          </>
        }
      >
        <p className={styles.dialogText}>Its text will be removed from the script.</p>
      </Dialog>
    </div>
  );
}
