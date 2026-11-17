import { Button, Dialog } from "@/components/ui";
import type { DispositionListRow } from "@/lib/types";
import styles from "../dispositions.module.css";

/** Confirms deleting a list. A list attached to an agent can't be deleted; the server says which agent. */
export function DeleteListDialog({
  list,
  pending,
  onClose,
  onDelete,
}: {
  list: Pick<DispositionListRow, "id" | "name" | "used_by"> | null;
  pending: boolean;
  onClose: () => void;
  onDelete: (id: number) => void;
}) {
  return (
    <Dialog
      open={list !== null}
      onClose={onClose}
      title={list ? `Delete ${list.name}?` : "Delete list"}
      footer={
        <>
          <Button onClick={onClose}>Keep it</Button>
          <Button variant="danger" loading={pending} onClick={() => list && onDelete(list.id)}>Delete list</Button>
        </>
      }
    >
      <p className={styles.dialogText}>
        {list && list.used_by.length > 0
          ? `${list.used_by.map((a) => a.name).join(", ")} ${list.used_by.length === 1 ? "uses" : "use"} this list. Attach another list to ${list.used_by.length === 1 ? "it" : "them"} first.`
          : "No agent uses it. Past calls keep the dispositions they were given."}
      </p>
    </Dialog>
  );
}
