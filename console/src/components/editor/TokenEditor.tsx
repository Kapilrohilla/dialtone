"use client";

import { EditorContent, useEditor } from "@tiptap/react";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui";
import { cx } from "@/components/ui/util";
import type { Expression } from "@/lib/types";
import { MAX_PAUSE_S, MIN_PAUSE_S, formatSeconds } from "@/lib/tokens";
import { exprChipRefresh } from "./ExprChipNode";
import { editorExtensions, type TokenEditorMode } from "./extensions";
import { fromEditor, toEditorHtml } from "./markdown";
import { Toolbar } from "./Toolbar";
import styles from "./editor.module.css";

export type { TokenEditorMode } from "./extensions";

export type TokenEditorProps = {
  /** Stored token text (Markdown with `[[expr:…]]` and `{{lead.…}}`). */
  value: string;
  /** The serialized text after each edit. Not called on mount or when `value` changes from outside; debounce in the caller. */
  onChange: (value: string) => void;
  /** script: paragraphs, bold, italic, bullet lists. document: adds headings and tables. line: one paragraph. */
  mode: TokenEditorMode;
  /** The agent's custom expressions, name to hint. */
  customExpressions?: Record<string, string>;
  /** Adds "New expression…" to the Expression menu. The chip is inserted right after. */
  onCreateExpression?: (name: string, hint: string) => void;
  /** Built-ins from GET /api/expressions; the constant list is used until then. */
  builtins?: Expression[];
  readOnly?: boolean;
  "aria-label": string;
  className?: string;
};

type PauseEdit = { pos: number; seconds: string; top: number; left: number };

const NO_CUSTOM: Record<string, string> = {};

export function TokenEditor({
  value,
  onChange,
  mode,
  customExpressions = NO_CUSTOM,
  onCreateExpression,
  builtins,
  readOnly = false,
  "aria-label": ariaLabel,
  className,
}: TokenEditorProps) {
  const onChangeRef = useRef(onChange);
  const customRef = useRef(customExpressions);
  const lastValue = useRef(value);
  const wrapper = useRef<HTMLDivElement>(null);
  const [pause, setPause] = useState<PauseEdit | null>(null);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  const editor = useEditor(
    {
      immediatelyRender: false,
      editable: !readOnly,
      extensions: editorExtensions(mode, (name) => name in customRef.current),
      content: toEditorHtml(value),
      editorProps: {
        attributes: {
          role: "textbox",
          "aria-label": ariaLabel,
          "aria-multiline": mode === "line" ? "false" : "true",
          class: cx(styles.content, mode === "line" && styles.line),
        },
        handleDOMEvents: {
          click(view, event) {
            const chip = (event.target as HTMLElement).closest<HTMLElement>('[data-expr="pause"]');
            if (!chip || !view.editable || !wrapper.current) return false;
            const pos = view.posAtDOM(chip, 0);
            const node = view.state.doc.nodeAt(pos);
            if (node?.type.name !== "exprChip") return false;
            const box = wrapper.current.getBoundingClientRect();
            const at = chip.getBoundingClientRect();
            setPause({ pos, seconds: formatSeconds(node.attrs.seconds ?? 1), top: at.bottom - box.top + 4, left: at.left - box.left });
            return true;
          },
        },
      },
      onUpdate({ editor: e }) {
        // Schema housekeeping (the empty paragraph tiptap keeps after a closing table) changes the doc
        // without changing the text: that is not an edit.
        const next = fromEditor(e);
        if (next === lastValue.current) return;
        lastValue.current = next;
        onChangeRef.current(next);
      },
    },
    [mode],
  );

  // A new value from outside (another revision, a reset) replaces the content without reporting a change.
  useEffect(() => {
    if (!editor || editor.isDestroyed || value === lastValue.current) return;
    lastValue.current = value;
    editor.commands.setContent(toEditorHtml(value), { emitUpdate: false });
  }, [editor, value]);

  useEffect(() => {
    if (editor && !editor.isDestroyed && editor.isEditable === readOnly) editor.setEditable(!readOnly, false);
  }, [editor, readOnly]);

  // Re-mark custom and unknown chips when the agent's expressions change.
  useEffect(() => {
    customRef.current = customExpressions;
    if (editor && !editor.isDestroyed) editor.view.dispatch(editor.state.tr.setMeta(exprChipRefresh, true).setMeta("addToHistory", false));
  }, [editor, customExpressions]);

  return (
    <div ref={wrapper} className={cx(styles.editor, className)}>
      {editor && !readOnly && (
        <Toolbar
          editor={editor}
          mode={mode}
          builtins={builtins}
          customExpressions={customExpressions}
          onCreateExpression={onCreateExpression}
        />
      )}
      <EditorContent editor={editor} />
      {editor && pause && (
        <PausePopover
          edit={pause}
          onChange={(seconds) => setPause({ ...pause, seconds })}
          onClose={() => {
            setPause(null);
            editor.commands.focus();
          }}
          onApply={(seconds) => {
            const { pos } = pause;
            setPause(null);
            editor
              .chain()
              .focus()
              .command(({ tr }) => {
                tr.setNodeAttribute(pos, "seconds", seconds);
                return true;
              })
              .run();
          }}
        />
      )}
    </div>
  );
}

type PausePopoverProps = {
  edit: PauseEdit;
  onChange: (seconds: string) => void;
  onApply: (seconds: number) => void;
  onClose: () => void;
};

function PausePopover({ edit, onChange, onApply, onClose }: PausePopoverProps) {
  const [error, setError] = useState<string | null>(null);
  const id = useId();

  function submit(e: FormEvent) {
    e.preventDefault();
    const seconds = Math.round(Number(edit.seconds) * 10) / 10;
    if (edit.seconds.trim() === "" || !Number.isFinite(seconds) || seconds < MIN_PAUSE_S || seconds > MAX_PAUSE_S) {
      setError(`Use a pause from ${MIN_PAUSE_S} to ${MAX_PAUSE_S} seconds.`);
      return;
    }
    onApply(seconds);
  }

  return (
    <form
      className={styles.pausePopover}
      style={{ top: edit.top, left: edit.left }}
      aria-label="Pause length"
      onSubmit={submit}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
        }
      }}
      noValidate
    >
      <label htmlFor={id} className={styles.otherLabel}>Seconds</label>
      <div className={styles.otherRow}>
        <input
          id={id}
          type="number"
          min={MIN_PAUSE_S}
          max={MAX_PAUSE_S}
          step={0.1}
          className={cx(styles.otherInput, "mono")}
          value={edit.seconds}
          autoFocus
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          onChange={(e) => onChange(e.target.value)}
        />
        <Button size="sm" type="submit">Apply</Button>
        <Button size="sm" variant="text" onClick={onClose}>Cancel</Button>
      </div>
      {error && <p id={`${id}-error`} className={styles.error}>{error}</p>}
    </form>
  );
}
