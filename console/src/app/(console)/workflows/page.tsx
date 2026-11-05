"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { TopBar } from "@/components/shell/TopBar";
import { Button, Menu, StateBlock, Table, Td, Th } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useAgents, useCreateWorkflow, useMe, useWorkflows } from "@/lib/queries";
import { canEdit } from "@/lib/roles";
import type { AgentListItem } from "@/lib/types";
import styles from "@/components/workflow/workflow.module.css";

function usedBy(agents: AgentListItem[] | undefined, id: number) {
  if (!agents) return "—";
  const names = agents.filter((a) => a.workflow === id && a.status !== "archived").map((a) => a.name);
  return names.length ? names.join(", ") : "Not used";
}

export default function WorkflowsPage() {
  const router = useRouter();
  const { data: workflows, isError, error, refetch } = useWorkflows();
  const { data: agents } = useAgents();
  const { data: me } = useMe();
  const create = useCreateWorkflow();
  const editable = canEdit(me?.role);
  const timeZone = me?.preferences.time_zone ?? "Asia/Kolkata";

  const newWorkflow = () => create.mutate({ name: "Untitled workflow" }, { onSuccess: (wf) => router.push(`/workflows/${wf.id}`) });

  return (
    <>
      <TopBar
        title="Workflows"
        primary={editable ? <Button variant="primary" loading={create.isPending} onClick={newWorkflow}>New workflow</Button> : undefined}
      />
      <div className={styles.page}>
        {isError ? (
          <StateBlock state="error" title="Could not load workflows" body={error instanceof ApiError ? error.detail : undefined} onRetry={() => refetch()} />
        ) : !workflows ? (
          <StateBlock state="loading" title="Loading workflows" />
        ) : workflows.length === 0 ? (
          <StateBlock state="empty" title="No workflows yet. A workflow splits a call into steps, each with its own prompt." />
        ) : (
          <Table aria-label="Workflows">
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Last edited</Th>
                <Th>Used by</Th>
                <Th><span className={styles.srOnly}>Actions</span></Th>
              </tr>
            </thead>
            <tbody>
              {workflows.map((wf) => (
                <tr key={wf.id}>
                  <Td><Link href={`/workflows/${wf.id}`} className={styles.rowName}>{wf.name}</Link></Td>
                  <Td>{timeAgo(wf.updated_at, new Date(), timeZone)}</Td>
                  <Td className={styles.usedBy}>{usedBy(agents, wf.id)}</Td>
                  <Td className={styles.rowActions}>
                    <Menu label={`More actions for ${wf.name}`} items={[{ label: "Open", onSelect: () => router.push(`/workflows/${wf.id}`) }]} />
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </div>
    </>
  );
}
