"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Simulator } from "@/components/sim/Simulator";
import { VoiceTest } from "@/components/sim/VoiceTest";
import { TopBar, type Crumb } from "@/components/shell/TopBar";
import { Button, Chip, StateBlock, useToast } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAgent, useAgents, useExpressions, useMe } from "@/lib/queries";
import { canEdit } from "@/lib/roles";
import type { Agent } from "@/lib/types";
import { PublishDialog } from "../_components/PublishDialog";
import { NameCrumb } from "./_components/NameCrumb";
import { SaveStatus } from "./_components/SaveStatus";
import { ScriptDocument } from "./_components/ScriptDocument";
import { SidePanel } from "./_components/SidePanel";
import { groupOf, TIMINGS_GROUP, useAgentSaves } from "./_components/useAgentSaves";
import styles from "./_components/editor.module.css";

export default function AgentEditorPage() {
  const { id } = useParams<{ id: string }>();
  const agentId = Number(id);
  const { data: agent, isError, error, refetch } = useAgent(agentId);
  const me = useMe();
  // Bumped when an accepted audit fix changed the saved agent: the editor starts again from the fresh agent, so
  // its local copies (script, fields) can't save the old values over the fix.
  const [generation, setGeneration] = useState(0);

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
  return (
    <AgentEditor
      key={`${agent.id}-${generation}`}
      agent={agent}
      editable={canEdit(me.data?.role)}
      onReload={async () => {
        await refetch();
        setGeneration((g) => g + 1);
      }}
    />
  );
}

function StatusChip({ status }: { status: Agent["status"] }) {
  if (status === "published") return <Chip tone="ok">Live</Chip>;
  if (status === "archived") return <Chip tone="muted">Archived</Chip>;
  return <Chip>Draft</Chip>;
}

function AgentEditor({ agent, editable, onReload }: { agent: Agent; editable: boolean; onReload: () => Promise<void> }) {
  const saves = useAgentSaves(agent);
  const { data: expressions } = useExpressions();
  const { data: agents } = useAgents();
  const toast = useToast();
  const [publishing, setPublishing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [voiceTesting, setVoiceTesting] = useState(false);
  const live = agents?.find((a) => a.status === "published") ?? null;
  const isLive = agent.status === "published";
  const upToDate = isLive && !agent.is_outdated;

  async function publish() {
    try {
      await saves.flushAll();
      setPublishing(true);
    } catch {
      // Publishing now would ship the old text. The top bar (and the timings) say what failed.
      toast.show("Fix the errors before publishing.", "bad");
    }
  }

  /** An agent fix is accepted from the saved agent: save what's unsaved first, or say why not. */
  async function beforeAcceptFix(): Promise<string | null> {
    try {
      await saves.flushAll();
      return null;
    } catch {
      return "Fix the errors on this page before accepting.";
    }
  }

  async function testChat() {
    // The simulator runs the saved draft: save first, but a failed save still lets you try the last one.
    await saves.flushAll().catch(() => undefined);
    setTesting(true);
  }

  async function voiceTest() {
    // The voice agent fetches the saved draft when it joins: save first, like Test chat.
    await saves.flushAll().catch(() => undefined);
    setVoiceTesting(true);
  }

  const breadcrumb: Crumb[] = [
    { label: "Agents", href: "/agents" },
    {
      label: agent.name,
      node: (
        <NameCrumb
          name={agent.name}
          editable={editable}
          onSave={(name) => void saves.saveFields({ name })}
          onUnchanged={() => saves.markInvalid(groupOf({ name: agent.name }), null)}
        />
      ),
    },
    { label: "Script" },
  ];

  return (
    <>
      <TopBar
        breadcrumb={breadcrumb}
        chip={<StatusChip status={agent.status} />}
        status={editable ? <SaveStatus script={saves.autosave} field={saves.field} signedOut={saves.signedOut} /> : undefined}
        secondary={
          editable ? (
            <>
              <Button onClick={testChat}>Test chat</Button>
              <Button onClick={voiceTest} title="Talk to the draft through your microphone; no phone call">
                Voice test
              </Button>
            </>
          ) : undefined
        }
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
          timingsError={saves.field.errors[TIMINGS_GROUP]?.detail}
          markInvalid={saves.markInvalid}
          beforeAccept={beforeAcceptFix}
          onAgentChanged={() => void onReload()}
        />
      </div>
      {editable && (
        <PublishDialog agent={publishing ? agent : null} liveAgent={live} onClose={() => setPublishing(false)} />
      )}
      {testing && <Simulator kind="agent" id={agent.id} customExpressions={saves.custom} onClose={() => setTesting(false)} />}
      {voiceTesting && <VoiceTest agentId={agent.id} onClose={() => setVoiceTesting(false)} />}
    </>
  );
}
