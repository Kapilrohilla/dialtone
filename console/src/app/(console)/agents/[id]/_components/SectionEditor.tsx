"use client";

import { TokenEditor } from "@/components/editor/TokenEditor";
import { Menu } from "@/components/ui";
import type { Expression, ScriptSection } from "@/lib/types";
import styles from "./editor.module.css";

export type SectionEditorProps = {
  section: ScriptSection;
  index: number;
  count: number;
  readOnly: boolean;
  customExpressions: Record<string, string>;
  onCreateExpression: (name: string, hint: string) => void;
  builtins?: Expression[];
  onChange: (section: ScriptSection) => void;
  onMove: (by: -1 | 1) => void;
  onDelete: () => void;
};

/** One script section: a plain heading and its text with expression and variable chips. */
export function SectionEditor({ section, index, count, readOnly, customExpressions, onCreateExpression, builtins, onChange, onMove, onDelete }: SectionEditorProps) {
  const name = section.title.trim() || "Untitled section";
  return (
    <section aria-label={name} className={styles.section}>
      <div className={styles.sectionHead}>
        {readOnly ? (
          <h2 className={styles.heading}>{name}</h2>
        ) : (
          <>
            <input
              className={styles.headingInput}
              aria-label={`Heading of section ${index + 1}`}
              value={section.title}
              maxLength={200}
              placeholder="Untitled section"
              onChange={(e) => onChange({ ...section, title: e.target.value })}
            />
            <Menu
              label="Section actions"
              items={[
                { label: "Move up", onSelect: () => onMove(-1), disabled: index === 0 },
                { label: "Move down", onSelect: () => onMove(1), disabled: index === count - 1 },
                { label: "Delete", onSelect: onDelete, danger: true },
              ]}
            />
          </>
        )}
      </div>
      <TokenEditor
        mode="script"
        value={section.body}
        onChange={(body) => onChange({ ...section, body })}
        aria-label={name}
        readOnly={readOnly}
        customExpressions={customExpressions}
        onCreateExpression={onCreateExpression}
        builtins={builtins}
        className={styles.body}
      />
    </section>
  );
}
