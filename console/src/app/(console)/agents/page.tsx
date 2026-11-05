"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Dialog, StateBlock, Tabs } from "@/components/ui";
import { TopBar } from "@/components/shell/TopBar";
import { ApiError } from "@/lib/api";
import { useAgents, useArchive, useCreateAgent, useDashboard, useDuplicate, useMe, useRestore, useUnpublish } from "@/lib/queries";
import { canEdit } from "@/lib/roles";
import type { AgentListItem } from "@/lib/types";
import { AgentsTable } from "./_components/AgentsTable";
import { LivePanel } from "./_components/LivePanel";
import { PublishDialog } from "./_components/PublishDialog";
import styles from "./_components/agents.module.css";

type Tab = "all" | "live" | "drafts" | "archived";
const TABS: { id: Tab; label: string }[] = [
  { id: "all", label: "All" },
  { id: "live", label: "Live" },
  { id: "drafts", label: "Drafts" },
  { id: "archived", label: "Archived" },
];
const EMPTY: Record<Tab, string> = { all: "No agents yet.", live: "No agent is live.", drafts: "No drafts.", archived: "Nothing archived." };

function inTab(a: AgentListItem, tab: Tab) {
  if (tab === "all") return a.status !== "archived";
  if (tab === "live") return a.status === "published";
  if (tab === "drafts") return a.status === "draft";
  return a.status === "archived";
}

export default function AgentsPage() {
  const router = useRouter();
  const { data: agents, isError, error, refetch } = useAgents();
  const { data: dashboard } = useDashboard();
  const { data: me } = useMe();
  const create = useCreateAgent();
  const unpublish = useUnpublish();
  const duplicate = useDuplicate();
  const archive = useArchive();
  const restore = useRestore();
  const [tab, setTab] = useState<Tab>("all");
  const [publishing, setPublishing] = useState<AgentListItem | null>(null);
  const [unpublishing, setUnpublishing] = useState<AgentListItem | null>(null);

  const editable = canEdit(me?.role);
  const live = agents?.find((a) => a.status === "published");
  const rows = agents?.filter((a) => inTab(a, tab)) ?? [];
  const open = (a: AgentListItem) => router.push(`/agents/${a.id}`);

  function newAgent() {
    create.mutate({ name: "Untitled agent" }, { onSuccess: (a) => router.push(`/agents/${a.id}`) });
  }

  return (
    <>
      <TopBar
        title="Agents"
        primary={editable ? <Button variant="primary" loading={create.isPending} onClick={newAgent}>New agent</Button> : undefined}
      />
      <div className={styles.page}>
        {isError ? (
          <StateBlock state="error" title="Could not load agents" body={error instanceof ApiError ? error.detail : undefined} onRetry={() => refetch()} />
        ) : (
          <>
            <LivePanel loading={!agents} live={live} callsToday={dashboard?.calls_today} canEdit={editable} onUnpublish={() => live && setUnpublishing(live)} />
            <Tabs label="Agent status" tabs={TABS} value={tab} onChange={setTab}>
              {!agents ? (
                <div className={styles.skeletonRows} aria-label="Loading agents">
                  {[0, 1, 2].map((i) => (
                    <span key={i} className={styles.skeleton} style={{ height: 56 }} aria-hidden="true" />
                  ))}
                </div>
              ) : rows.length === 0 ? (
                <StateBlock state="empty" title={EMPTY[tab]} />
              ) : (
                <AgentsTable
                  agents={rows}
                  canEdit={editable}
                  timeZone={me?.preferences.time_zone ?? "Asia/Kolkata"}
                  onPublish={setPublishing}
                  onUnpublish={setUnpublishing}
                  onDuplicate={(a) => duplicate.mutate(a.id)}
                  onArchive={(a) => archive.mutate(a.id)}
                  onRestore={(a) => restore.mutate(a.id)}
                  onOpen={open}
                />
              )}
            </Tabs>
          </>
        )}
      </div>
      <PublishDialog agent={publishing} liveAgent={live} onClose={() => setPublishing(null)} />
      <Dialog
        open={unpublishing !== null}
        onClose={() => setUnpublishing(null)}
        title={unpublishing ? `Unpublish ${unpublishing.name}?` : "Unpublish"}
        footer={
          <>
            <Button onClick={() => setUnpublishing(null)}>Cancel</Button>
            <Button
              variant="danger"
              loading={unpublish.isPending}
              onClick={() => unpublishing && unpublish.mutate(unpublishing.id, { onSettled: () => setUnpublishing(null) })}
            >
              Unpublish
            </Button>
          </>
        }
      >
        <p className={styles.dialogText}>
          Stop {unpublishing?.name} answering calls? Callers will hear the built-in script until you publish an agent.
        </p>
      </Dialog>
    </>
  );
}
