import { Button, Segmented } from "@/components/ui";
import { TokenEditor } from "@/components/editor/TokenEditor";
import { formatWhen } from "@/lib/format";
import type { Revision } from "@/lib/types";
import styles from "../knowledge.module.css";

export type EditorMode = "rich" | "markdown";

type Props = {
  title: string;
  body: string;
  mode: EditorMode;
  readOnly: boolean;
  newest: Revision | undefined;
  timeZone: string;
  onTitle: (title: string) => void;
  onBody: (body: string) => void;
  onMode: (mode: EditorMode) => void;
  onHistory: () => void;
  /** Absent for people who can't edit. */
  onDelete?: () => void;
  /** Set when a newer saved version exists and this draft has edits. */
  onLoadTheirs?: () => void;
};

export function DocEditor({ title, body, mode, readOnly, newest, timeZone, onTitle, onBody, onMode, onHistory, onDelete, onLoadTheirs }: Props) {
  return (
    <div className={styles.doc}>
      {onLoadTheirs && (
        <div className={styles.stale} role="status">
          <span>Someone saved a newer version of this document. Saving will replace their changes.</span>
          <Button variant="text" onClick={onLoadTheirs}>
            Load their version
          </Button>
        </div>
      )}
      <input className={styles.title} aria-label="Document title" value={title} readOnly={readOnly} maxLength={200} onChange={(e) => onTitle(e.target.value)} />
      <Segmented
        className={styles.toggle}
        label="Editor"
        options={[
          { value: "rich", label: "Rich text" },
          { value: "markdown", label: "Markdown" },
        ]}
        value={mode}
        onChange={onMode}
      />
      {mode === "rich" ? (
        <TokenEditor className={styles.editor} mode="document" value={body} onChange={onBody} readOnly={readOnly} aria-label="Document text" />
      ) : (
        <textarea className={styles.markdown} aria-label="Document Markdown" value={body} readOnly={readOnly} spellCheck={false} onChange={(e) => onBody(e.target.value)} />
      )}
      <p className={styles.note}>The agent only quotes what is written here.</p>
      <div className={styles.footer}>
        <span>
          {newest ? (
            <>
              Last edited{newest.edited_by ? " by " : ""}
              {newest.edited_by && <span className={styles.who}>{newest.edited_by}</span>}, {formatWhen(newest.created_at, timeZone)}
            </>
          ) : null}
        </span>
        <span className={styles.footerActions}>
          <Button variant="text" onClick={onHistory}>
            Version history
          </Button>
          {onDelete && (
            <Button variant="text" className={styles.delete} onClick={onDelete}>
              Delete
            </Button>
          )}
        </span>
      </div>
    </div>
  );
}
