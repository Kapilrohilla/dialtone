import { useState } from "react";
import { Button, SlideOver, StateBlock } from "@/components/ui";
import { TokenEditor } from "@/components/editor/TokenEditor";
import { useRevision, useRevisions } from "@/lib/queries";
import { formatWhen } from "@/lib/format";
import styles from "../knowledge.module.css";

type Props = { docId: number; open: boolean; onClose: () => void; timeZone: string; canEdit: boolean; onRestore: (body: string) => void };

export function VersionHistory({ docId, open, onClose, timeZone, canEdit, onRestore }: Props) {
  const revisions = useRevisions(open ? docId : undefined);
  const [chosen, setChosen] = useState<number | null>(null);
  // Each opening of a document's history starts with nothing chosen.
  const scope = open ? docId : null;
  const [seen, setSeen] = useState(scope);
  if (seen !== scope) {
    setSeen(scope);
    setChosen(null);
  }
  const revision = useRevision(open ? docId : undefined, chosen);
  const body = revision.data?.body_md;

  return (
    <SlideOver
      open={open}
      onClose={onClose}
      title="Version history"
      footer={
        canEdit && (
          <Button
            variant="primary"
            disabled={body === undefined}
            onClick={() => {
              if (body === undefined) return;
              onRestore(body);
            }}
          >
            Restore this version
          </Button>
        )
      }
    >
      {revisions.isError ? (
        <StateBlock state="error" title="Could not load the versions" onRetry={() => revisions.refetch()} />
      ) : !revisions.data ? (
        <StateBlock state="loading" title="Loading versions" />
      ) : (
        <>
          <ul className={styles.versions}>
            {revisions.data.map((r) => (
              <li key={r.number}>
                <button type="button" className={styles.version} aria-current={r.number === chosen} onClick={() => setChosen(r.number)}>
                  <span>Version {r.number}</span>
                  <span className={styles.versionMeta}>
                    {r.edited_by ? `${r.edited_by}, ` : ""}
                    {formatWhen(r.created_at, timeZone)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className={styles.preview}>
            {chosen === null ? (
              <p className={styles.hint}>Choose a version to read it.</p>
            ) : revision.isError ? (
              <StateBlock state="error" title="Could not load this version" onRetry={() => revision.refetch()} />
            ) : body === undefined ? (
              <StateBlock state="loading" title="Loading version" />
            ) : (
              <TokenEditor key={chosen} mode="document" value={body} onChange={() => {}} readOnly aria-label={`Version ${chosen} text`} />
            )}
          </div>
        </>
      )}
    </SlideOver>
  );
}
