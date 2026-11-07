"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Simulator } from "@/components/sim/Simulator";
import { TopBar } from "@/components/shell/TopBar";
import { Button, Dialog, StateBlock, Switch, useToast } from "@/components/ui";
import { Canvas } from "@/components/workflow/Canvas";
import { addPath, addStep, removePath, removeStep, retypeStep, updatePath, updateStep, withPathIds } from "@/components/workflow/graph";
import { layoutMissing } from "@/components/workflow/layout";
import { StepPanel } from "@/components/workflow/StepPanel";
import styles from "@/components/workflow/workflow.module.css";
import { ApiError } from "@/lib/api";
import { useExpressions, useKnowledgeList, useMe, useSaveWorkflow, useWorkflow } from "@/lib/queries";
import { canEdit } from "@/lib/roles";
import { useLeaveGuard } from "@/lib/useLeaveGuard";
import type { Graph, Step, Workflow } from "@/lib/types";
import { NameCrumb } from "../../agents/[id]/_components/NameCrumb";

export default function WorkflowBuilderPage() {
  const { id } = useParams<{ id: string }>();
  const { data: workflow, isError, error, refetch } = useWorkflow(Number(id));
  const me = useMe();

  if (isError || !workflow || me.isPending) {
    return (
      <>
        <TopBar breadcrumb={[{ label: "Workflows", href: "/workflows" }, { label: "Workflow" }]} />
        <div className={styles.page}>
          {isError ? (
            <StateBlock state="error" title="Could not load the workflow" body={error instanceof ApiError ? error.detail : undefined} onRetry={() => refetch()} />
          ) : (
            <StateBlock state="loading" title="Loading the workflow" />
          )}
        </div>
      </>
    );
  }
  return (
    <Builder
      key={workflow.id}
      workflow={workflow}
      editable={canEdit(me.data?.role)}
      accountCheckIns={me.data?.workspace.dead_air_enabled ?? true}
    />
  );
}

/** The graph being edited, the saved graph it is compared with (as JSON), and the revision it came from. */
type Draft = { rev: number; base: string; graph: Graph };

function seed(wf: Workflow): Draft {
  const graph = withPathIds(layoutMissing(wf.graph));
  return { rev: wf.current_revision, base: JSON.stringify(graph), graph };
}

/** The step an error message names in quotes, if any. */
function stepNamedIn(message: string, steps: Step[]) {
  for (const [, quoted] of message.matchAll(/"([^"]+)"/g)) {
    // The server names a step by its name as typed, or by its id when the name is blank (graph.py _label).
    const step = steps.find((s) => (s.name.trim() ? s.name : s.id) === quoted);
    if (step) return step;
  }
  return undefined;
}

/** The dead-air switch for the whole workflow. It saves on its own (no Save), and agents publish it like the graph. */
function WorkflowSettings({ workflow, editable, accountCheckIns }: { workflow: Workflow; editable: boolean; accountCheckIns: boolean }) {
  const save = useSaveWorkflow(workflow.id);
  const sending = save.isPending ? save.variables?.dead_air_enabled : undefined;
  return (
    <section className={styles.workflowSettings} aria-labelledby="workflow-settings-h">
      <h2 id="workflow-settings-h" className={styles.panelHeading}>Workflow settings</h2>
      <Switch
        label="Check in when the caller goes quiet"
        checked={sending ?? workflow.dead_air_enabled}
        disabled={!editable || save.isPending}
        onChange={(next) => save.mutate({ dead_air_enabled: next })}
      />
      <p className={styles.settingNote}>
        {accountCheckIns ? (
          "For agents using this workflow, once they are published. Each agent also has its own switch."
        ) : (
          <>
            Off for the whole account, so no call checks in. Turn it back on in <Link href="/settings/calls">Settings</Link>.
          </>
        )}
      </p>
    </section>
  );
}

function Builder({ workflow, editable, accountCheckIns }: { workflow: Workflow; editable: boolean; accountCheckIns: boolean }) {
  const toast = useToast();
  const [draft, setDraft] = useState(() => seed(workflow));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Step | null>(null);
  const [trying, setTrying] = useState(false);
  const save = useSaveWorkflow(workflow.id, (saved, sent) => {
    if (sent.graph) setDraft((d) => ({ ...d, rev: saved.current_revision, base: JSON.stringify(sent.graph) }));
  });
  const rename = useSaveWorkflow(workflow.id);
  const { data: knowledge } = useKnowledgeList();
  const { data: expressions } = useExpressions();

  const dirty = JSON.stringify(draft.graph) !== draft.base;
  // A newer saved revision (someone else saved) replaces an untouched draft; edits are kept and the person is told.
  let newerSaved = false;
  if (workflow.current_revision > draft.rev) {
    if (dirty) newerSaved = true;
    else setDraft(seed(workflow));
  }
  const guard = useLeaveGuard(dirty);

  const graph = draft.graph;
  const selected = graph.steps.find((s) => s.id === selectedId) ?? null;
  /** Applies an edit to the latest graph (several can land in one event). */
  const edit = (change: (g: Graph) => Graph) => setDraft((d) => ({ ...d, graph: change(d.graph) }));

  const saveGraph = () => save.mutateAsync({ graph });

  async function tryIt() {
    // "Try it" runs the saved revision: save first, and stop if that fails (the toast says why).
    if (dirty) {
      try {
        await saveGraph();
      } catch {
        return;
      }
    }
    setTrying(true);
  }

  function askDelete(id: string) {
    const step = graph.steps.find((s) => s.id === id);
    if (!step) return;
    if (removeStep(graph, id) === graph) toast.show("Every workflow needs its start step.", "bad");
    else setDeleting(step);
  }

  function addPathFrom(step: Step) {
    const linked = new Set(graph.paths.filter((p) => p.from === step.id).map((p) => p.to));
    const others = graph.steps.filter((s) => s.id !== step.id);
    const target = others.find((s) => !linked.has(s.id) && s.type !== "start") ?? others[0];
    if (target) edit((g) => addPath(g, step.id, target.id, "New path"));
  }

  return (
    <>
      <TopBar
        breadcrumb={[
          { label: "Workflows", href: "/workflows" },
          {
            label: workflow.name,
            node: <NameCrumb name={workflow.name} editable={editable} inputLabel="Workflow name" onSave={(name) => rename.mutate({ name })} />,
          },
        ]}
        secondary={editable ? <Button onClick={tryIt} disabled={save.isPending}>Try it</Button> : undefined}
        primary={
          editable ? (
            <Button variant="primary" disabled={!dirty} loading={save.isPending} onClick={() => saveGraph().catch(() => undefined)}>
              Save
            </Button>
          ) : undefined
        }
      />
      <div className={styles.layout}>
        <div className={styles.main}>
          {newerSaved && <p className={styles.notice}>Someone saved a newer version of this workflow. Saving will replace their changes.</p>}
          {workflow.errors.length > 0 && (
            <section className={styles.errors} aria-label="Problems with this workflow">
              <p className={styles.errorsTitle}>Fix these before an agent can use this workflow:</p>
              <ul>
                {workflow.errors.map((message, i) => {
                  const step = stepNamedIn(message, graph.steps);
                  return (
                    <li key={i}>
                      {step ? (
                        <button type="button" className={styles.errorLink} onClick={() => setSelectedId(step.id)}>
                          {message}
                        </button>
                      ) : (
                        message
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
          <Canvas
            graph={graph}
            selectedId={selectedId}
            readOnly={!editable}
            onSelect={setSelectedId}
            onMove={(id, position) => edit((g) => updateStep(g, id, { position }))}
            onConnect={(from, to) => {
              edit((g) => addPath(g, from, to, "New path"));
              setSelectedId(from);
            }}
            onAdd={(type) => {
              const added = addStep(graph, type, selected ?? undefined);
              edit(() => added.graph);
              setSelectedId(added.step.id);
            }}
            onDelete={askDelete}
          />
        </div>
        <StepPanel
          step={selected}
          graph={graph}
          readOnly={!editable}
          knowledge={knowledge}
          builtins={expressions?.filter((e) => e.builtin)}
          onChange={(patch) => selected && edit((g) => updateStep(g, selected.id, patch))}
          onTypeChange={(type) => selected && edit((g) => retypeStep(g, selected.id, type))}
          onAddPath={() => selected && addPathFrom(selected)}
          onPathChange={(id, patch) => edit((g) => updatePath(g, id, patch))}
          onPathRemove={(id) => edit((g) => removePath(g, id))}
          onDelete={() => selected && askDelete(selected.id)}
          workflowSettings={<WorkflowSettings workflow={workflow} editable={editable} accountCheckIns={accountCheckIns} />}
        />
      </div>
      <Dialog
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        title={`Delete ${deleting?.name.trim() || "this step"}?`}
        footer={
          <>
            <Button onClick={() => setDeleting(null)}>Keep it</Button>
            <Button
              variant="danger"
              onClick={() => {
                if (deleting) edit((g) => removeStep(g, deleting.id));
                setSelectedId(null);
                setDeleting(null);
              }}
            >
              Delete step
            </Button>
          </>
        }
      >
        <p className={styles.dialogText}>Its paths are removed too.</p>
      </Dialog>
      <Dialog
        open={guard.pending !== null}
        onClose={guard.stay}
        title={`Discard unsaved changes to ${workflow.name}?`}
        footer={
          <>
            <Button onClick={guard.stay}>Keep editing</Button>
            <Button variant="danger" onClick={guard.leave}>Discard</Button>
          </>
        }
      >
        <p className={styles.dialogText}>Your edits have not been saved.</p>
      </Dialog>
      {trying && <Simulator kind="workflow" id={workflow.id} onClose={() => setTrying(false)} />}
    </>
  );
}
