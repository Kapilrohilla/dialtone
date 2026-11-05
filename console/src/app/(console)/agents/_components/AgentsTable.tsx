"use client";

import Link from "next/link";
import { Button, Chip, Menu, Table, Td, Th, type MenuItem } from "@/components/ui";
import { timeAgo } from "@/lib/format";
import type { AgentListItem } from "@/lib/types";
import styles from "./agents.module.css";

export type AgentsTableProps = {
  agents: AgentListItem[];
  canEdit: boolean;
  timeZone: string;
  onPublish: (a: AgentListItem) => void;
  onUnpublish: (a: AgentListItem) => void;
  onDuplicate: (a: AgentListItem) => void;
  onArchive: (a: AgentListItem) => void;
  onRestore: (a: AgentListItem) => void;
  onOpen: (a: AgentListItem) => void;
};

export function AgentsTable({ agents, canEdit, timeZone, onPublish, onUnpublish, onDuplicate, onArchive, onRestore, onOpen }: AgentsTableProps) {
  function menu(a: AgentListItem): MenuItem[] {
    const items: MenuItem[] = [{ label: "Open", onSelect: () => onOpen(a) }, { label: "Duplicate", onSelect: () => onDuplicate(a) }];
    if (a.status === "published") items.push({ label: "Unpublish", onSelect: () => onUnpublish(a) });
    else if (a.status === "archived") items.push({ label: "Restore", onSelect: () => onRestore(a) });
    else items.push({ label: "Archive", onSelect: () => onArchive(a) });
    return items;
  }

  return (
    <Table aria-label="Agents">
      <thead>
        <tr>
          <Th>Agent</Th>
          <Th>Status</Th>
          <Th>Last edited</Th>
          <Th className={styles.right}>Calls this week</Th>
          <Th><span className={styles.srOnly}>Actions</span></Th>
        </tr>
      </thead>
      <tbody>
        {agents.map((a) => (
          <tr key={a.id}>
            <Td className={styles.agentCell}>
              <Link href={`/agents/${a.id}`} className={styles.agentName}>{a.name}</Link>
              {a.description && <span className={styles.description}>{a.description}</span>}
            </Td>
            <Td>
              <span className={styles.chips}>
                {a.status === "published" ? <Chip tone="ok">Live</Chip> : a.status === "archived" ? <Chip tone="muted">Archived</Chip> : <Chip>Draft</Chip>}
                {a.is_outdated && <Chip tone="amber">Older version</Chip>}
              </span>
            </Td>
            <Td>
              <span>{timeAgo(a.updated_at, new Date(), timeZone)}</span>
              {a.updated_by_name && <span className={styles.editor}> {a.updated_by_name}</span>}
            </Td>
            <Td className={styles.right}><span className={styles.mono}>{a.calls_this_week}</span></Td>
            <Td>
              {canEdit && (
                <span className={styles.actions}>
                  {a.status === "draft" && <Button size="sm" onClick={() => onPublish(a)}>Publish</Button>}
                  {a.status === "published" && a.is_outdated && <Button size="sm" onClick={() => onPublish(a)}>Republish</Button>}
                  <Menu label={`More actions for ${a.name}`} items={menu(a)} />
                </span>
              )}
            </Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
