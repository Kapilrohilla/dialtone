"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Simulator } from "@/components/sim/Simulator";
import { TopBar, type Crumb } from "@/components/shell/TopBar";
import { Button, Chip, StateBlock } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAgent, useAgents, useExpressions, useMe } from "@/lib/queries";
import { canEdit } from "@/lib/roles";
import type { Agent } from "@/lib/types";
import { PublishDialog } from "../_components/PublishDialog";
import { NameCrumb } from "./_components/NameCrumb";
import { SaveStatus } from "./_components/SaveStatus";
import { ScriptDocument } from "./_components/ScriptDocument";
import { SidePanel } from "./_components/SidePanel";
import { useAgentSaves } from "./_components/useAgentSaves";
import styles from "./_components/editor.module.css";

export default function AgentEditorPage() {
  const { id } = useParams<{ id: string }>();
  const agentId = Number(id);
  const { data: agent, isError, error, refetch } = useAgent(agentId);
  const me = useMe();

  if (isError || !agent || me.isPending) {
    return (
      <>
        <TopBar breadcrumb={[{ label: "Agents", href: "/agents" }, { label: "Script" }]} />
        <div className={styles.page}>
          {isError ? (
            <StateBlock state="error" title="Could not load the agent" body={error instanceof ApiError ? error.detail : undefined} onRetry={() => refetch()} />
          ) : (
            <StateBlock state="loading" title="Loading the script" />
          )}
        </div>
      </>
    );
  }
  return <AgentEditor key={agent.id} agent={agent} editable={canEdit(me.data?.role)} />;
}

function StatusChip({ status }: { status: Agent["status"] }) {
  if (status === "published") return <Chip tone="ok">Live</Chip>;
  if (status === "archived") return <Chip tone="muted">Archived</Chip>;
  return <Chip>Draft</Chip>;
}

function AgentEditor({ agent, editable }: { agent: Agent; editable: boolean }) {
  const saves = useAgentSaves(agent);
  const { data: expressions } = useExpressions();
  const { data: agents } = useAgents();
  const [publishing, setPublishing] = useState(false);
  const [testing, setTesting] = useState(false);
  const live = agents?.find((a) => a.status === "published") ?? null;
  const isLive = agent.status === "published";
  const upToDate = isLive && !agent.is_outdated;

  async function publish() {
    try {
      await saves.flushAll();
      setPublishing(true);
    } catch {
      // The top bar says why the script wasn't saved; publishing now would ship the old text.
    }
  }

  async function testCall() {
    // The simulator runs the saved draft: save first, but a failed save still lets you try the last one.
    await saves.flushAll().catch(() => undefined);
    setTesting(true);
  }

  const breadcrumb: Crumb[] = [
    { label: "Agents", href: "/agents" },
    { label: agent.name, node: <NameCrumb name={agent.name} editable={editable} onSave={(name) => void saves.saveFields({ name })} /> },
    { label: "Script" },
  ];

  return (
    <>
      <TopBar
        breadcrumb={breadcrumb}
        chip={<StatusChip status={agent.status} />}
        status={editable ? <SaveStatus script={saves.autosave} field={saves.field} signedOut={saves.signedOut} /> : undefined}
        secondary={editable ? <Button onClick={testCall}>Test call</Button> : undefined}
        primary={
          editable ? (
            <Button variant="primary" disabled={upToDate} title={upToDate ? "Up to date" : undefined} onClick={publish}>
              {isLive && agent.is_outdated ? "Republish" : "Publish"}
            </Button>
          ) : undefined
        }
      />
      {saves.signedOut && (
        <div role="alert" className={styles.banner}>
          <span>You were signed out. Sign in again to keep your changes.</span>
          <Link href={`/sign-in?next=/agents/${agent.id}`} className={styles.link}>Sign in again</Link>
        </div>
      )}
      {saves.restorable && editable && (
        <div className={styles.banner}>
          <span>This script has changes from earlier that were not saved.</span>
          <Button size="sm" onClick={saves.restore}>Restore unsaved changes</Button>
          <Button size="sm" variant="text" onClick={saves.discard}>Discard them</Button>
        </div>
      )}
      {isLive && agent.is_outdated && (
        <p className={styles.banner}>Uses an older version. Callers hear the last published version until you republish.</p>
      )}
      <div className={styles.layout}>
        <div className={styles.main}>
          <ScriptDocument
            sections={saves.sections}
            onChange={saves.setSections}
            readOnly={!editable}
            customExpressions={saves.custom}
            onCreateExpression={saves.createExpression}
            builtins={expressions?.filter((e) => e.builtin)}
          />
        </div>
        <SidePanel
          agent={agent}
          readOnly={!editable}
          save={saves.saveFields}
          timingsError={saves.field.inline ? saves.field.error?.detail : null}
        />
      </div>
      {editable && (
        <PublishDialog agent={publishing ? agent : null} liveAgent={live} onClose={() => setPublishing(false)} />
      )}
      {testing && <Simulator kind="agent" id={agent.id} customExpressions={saves.custom} onClose={() => setTesting(false)} />}
    </>
  );
}
