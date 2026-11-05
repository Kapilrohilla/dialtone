import type { CreateExpression } from "./ExpressionMenu";
import type { Editor } from "@tiptap/core";
import { useEditorState } from "@tiptap/react";
import { Bold, Heading2, Italic, List, Table, type LucideIcon } from "lucide-react";
import type { Expression } from "@/lib/types";
import { cx } from "@/components/ui/util";
import { ExpressionMenu } from "./ExpressionMenu";
import { VariableMenu } from "./VariableMenu";
import type { TokenEditorMode } from "./extensions";
import styles from "./editor.module.css";

export type ToolbarProps = {
  editor: Editor;
  mode: TokenEditorMode;
  builtins?: Expression[];
  customExpressions: Record<string, string>;
  onCreateExpression?: CreateExpression;
};

/** Heading cycles paragraph → H2 → H3 → paragraph. */
function cycleHeading(editor: Editor) {
  const chain = editor.chain().focus();
  if (editor.isActive("heading", { level: 2 })) chain.setHeading({ level: 3 }).run();
  else if (editor.isActive("heading", { level: 3 })) chain.setParagraph().run();
  else chain.setHeading({ level: 2 }).run();
}

export function Toolbar({ editor, mode, builtins, customExpressions, onCreateExpression }: ToolbarProps) {
  const active = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      bold: e.isActive("bold"),
      italic: e.isActive("italic"),
      list: e.isActive("bulletList"),
      heading: e.isActive("heading"),
      table: e.isActive("table"),
    }),
  });

  // Script and line modes are plain text with chips; only documents have Markdown formatting.
  const formatting: { label: string; icon: LucideIcon; pressed: boolean; run: () => void }[] =
    mode === "document"
      ? [
          { label: "Bold", icon: Bold, pressed: active.bold, run: () => editor.chain().focus().toggleBold().run() },
          { label: "Italic", icon: Italic, pressed: active.italic, run: () => editor.chain().focus().toggleItalic().run() },
          { label: "List", icon: List, pressed: active.list, run: () => editor.chain().focus().toggleBulletList().run() },
          { label: "Heading", icon: Heading2, pressed: active.heading, run: () => cycleHeading(editor) },
          {
            label: "Table",
            icon: Table,
            pressed: active.table,
            run: () => editor.chain().focus().insertTable({ rows: 3, cols: 2, withHeaderRow: true }).run(),
          },
        ]
      : [];

  return (
    <div role="toolbar" aria-label="Formatting" className={styles.toolbar}>
      {formatting.length > 0 && (
        <div className={styles.group}>
          {formatting.map(({ label, icon: Icon, pressed, run }) => (
            <button
              key={label}
              type="button"
              aria-label={label}
              title={label}
              aria-pressed={label === "Table" ? undefined : pressed}
              className={cx(styles.iconButton, pressed && styles.pressed)}
              onClick={run}
            >
              <Icon size={18} strokeWidth={1.75} aria-hidden="true" />
            </button>
          ))}
        </div>
      )}
      <VariableMenu onInsert={(path) => editor.chain().focus().insertContent({ type: "varChip", attrs: { path } }).run()} />
      <ExpressionMenu
        builtins={builtins}
        customExpressions={customExpressions}
        onCreateExpression={onCreateExpression}
        onInsert={(name) =>
          !editor.isDestroyed &&
          editor
            .chain()
            .focus()
            .insertContent({ type: "exprChip", attrs: { name, seconds: name === "pause" ? 1 : null } })
            .run()
        }
      />
    </div>
  );
}
