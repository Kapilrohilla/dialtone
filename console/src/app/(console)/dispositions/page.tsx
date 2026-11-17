"use client";

import { Info } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { TopBar } from "@/components/shell/TopBar";
import { Button, Chip, Menu, StateBlock, Table, Td, Th } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { NEW_DISPOSITION_LIST, useAgents, useCreateDispositionList, useDeleteDispositionList, useDispositionLists, useDuplicateDispositionList, useMe } from "@/lib/queries";
import { canEdit } from "@/lib/roles";
import type { DispositionListRow } from "@/lib/types";
import { DeleteListDialog } from "./_components/DeleteListDialog";
import styles from "./dispositions.module.css";

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export default function DispositionsPage() {
  const router = useRouter();
  const lists = useDispositionLists();
  const { data: agents } = useAgents();
  const { data: me } = useMe();
  const create = useCreateDispositionList();
  const duplicate = useDuplicateDispositionList();
  const remove = useDeleteDispositionList();
  const [deleting, setDeleting] = useState<DispositionListRow | null>(null);
  const editable = canEdit(me?.role);
  const timeZone = me?.preferences.time_zone ?? "Asia/Kolkata";

  const newList = () => create.mutate(NEW_DISPOSITION_LIST, { onSuccess: (list) => router.push(`/dispositions/${list.id}`) });
  // `disposition_list === null` only: an older server that doesn't send it can't say which agents have none.
  const without = (agents ?? []).filter((a) => a.status !== "archived" && a.disposition_list === null);

  let body;
  if (lists.isError) {
    body = <StateBlock state="error" title="Could not load disposition lists" body={lists.error instanceof ApiError ? lists.error.detail : undefined} onRetry={() => lists.refetch()} />;
  } else if (!lists.data) {
    body = <StateBlock state="loading" title="Loading disposition lists" />;
  } else if (lists.data.length === 0) {
    body = (
      <StateBlock
        state="empty"
        title="No disposition lists yet"
        body="Make a list of the outcomes your calls can have, then attach it to an agent."
        action={editable ? <Button variant="primary" loading={create.isPending} onClick={newList}>New list</Button> : undefined}
      />
    );
  } else {
    body = (
      <Table aria-label="Disposition lists">
        <thead>
          <tr>
            <Th>Name</Th>
            <Th>Dispositions</Th>
            <Th>Used by</Th>
            <Th>Last edited</Th>
            <Th><span className={styles.srOnly}>Actions</span></Th>
          </tr>
        </thead>
        <tbody>
          {lists.data.map((list) => (
            <tr key={list.id}>
              <Td><Link href={`/dispositions/${list.id}`} className={styles.name}>{list.name}</Link></Td>
              <Td>{plural(list.items.length, "disposition")}</Td>
              <Td>{list.used_by.length ? list.used_by.map((a) => a.name).join(", ") : <Chip tone="muted">Not used</Chip>}</Td>
              <Td className="mono">{timeAgo(list.updated_at, new Date(), timeZone)}</Td>
              <Td className={styles.right}>
                {editable && (
                  <Menu
                    label={`More actions for ${list.name}`}
                    items={[
                      { label: "Duplicate", onSelect: () => duplicate.mutate(list.id) },
                      { label: "Delete", danger: true, onSelect: () => setDeleting(list) },
                    ]}
                  />
                )}
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
    );
  }

  return (
    <>
      <TopBar title="Dispositions" primary={editable ? <Button variant="primary" loading={create.isPending} onClick={newList}>New list</Button> : undefined} />
      <div className={styles.page}>
        <p className={styles.intro}>
          A disposition list is the set of outcomes the AI can choose from at the end of a call. Attach one list to each agent. Agents with no list
          don&rsquo;t record a disposition.
        </p>
        {body}
        {without.length > 0 && (
          <aside className={styles.callout} aria-label="Agents without a list">
            <Info size={18} strokeWidth={1.75} aria-hidden="true" className={styles.calloutIcon} />
            <div className={styles.calloutText}>
              <p className={styles.calloutTitle}>Agents without a list</p>
              <p>
                {plural(without.length, "agent")} {without.length === 1 ? "doesn't" : "don't"} record dispositions:{" "}
                <span className={styles.ink}>{without.map((a) => a.name).join(", ")}</span>.
              </p>
            </div>
            <Link href="/agents" className={styles.calloutLink}>Attach a list →</Link>
          </aside>
        )}
      </div>
      <DeleteListDialog
        list={deleting}
        pending={remove.isPending}
        onClose={() => setDeleting(null)}
        onDelete={(id) => remove.mutate(id, { onSettled: () => setDeleting(null) })}
      />
    </>
  );
}
