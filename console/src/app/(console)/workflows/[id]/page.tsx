"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { Simulator } from "@/components/sim/Simulator";
import { TopBar } from "@/components/shell/TopBar";
import { Button, Dialog, StateBlock, Switch, useToast } from "@/components/ui";
import { Canvas } from "@/components/workflow/Canvas";
import {
  addPath,
  addStep,
  applySuggestion,
  removePath,
  removeStep,
  retypeStep,
  undoSuggestion,
  updatePath,
  updateStep,
  withPathIds,
  type Applied,
} from "@/components/workflow/graph";
import { layoutMissing } from "@/components/workflow/layout";
import { StepPanel } from "@/components/workflow/StepPanel";
import { SuggestDialog, SuggestionBanner } from "@/components/workflow/SuggestStart";
import { SuggestionsPanel, type StartError } from "@/components/workflow/SuggestionsPanel";
import styles from "@/components/workflow/workflow.module.css";
import { ApiError } from "@/lib/api";
import {
  useCloseSuggestions,
  useCurrentSuggestions,
  useExpressions,
  useKnowledgeList,
  useMe,
  usePatchSuggestion,
  useSaveWorkflow,
  useStartSuggestions,
  useWorkflow,
  type StartSuggestions,
} from "@/lib/queries";
import { canEdit } from "@/lib/roles";
import { useLeaveGuard } from "@/lib/useLeaveGuard";
import type { AnswerSuggestion, Graph, Step, SuggestScope, Suggestion, Workflow } from "@/lib/types";
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
      meId={me.data?.id}
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

type BuilderProps = { workflow: Workflow; editable: boolean; meId?: number; accountCheckIns: boolean };

function Builder({ workflow, editable, meId, accountCheckIns }: BuilderProps) {
  const toast = useToast();
  const [draft, setDraft] = useState(() => seed(workflow));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<Step | null>(null);
  const [trying, setTrying] = useState(false);
  // "Suggest with AI": the review panel, the start dialog, and the accepts not saved yet (newest last, for Undo).
  const [reviewing, setReviewing] = useState(false);
  const [asking, setAsking] = useState<{ scope: SuggestScope; stepId: string | null } | null>(null);
  const [accepted, setAccepted] = useState<Applied[]>([]);
  const [startError, setStartError] = useState<StartError | null>(null);
  const [lastAsk, setLastAsk] = useState<StartSuggestions | null>(null);
  const [confirmSave, setConfirmSave] = useState(false);
  const save = useSaveWorkflow(workflow.id, (saved, sent) => {
    if (sent.graph) setDraft((d) => ({ ...d, rev: saved.current_revision, base: JSON.stringify(sent.graph) }));
    if (sent.accepted_suggestions?.length) {
      const sentIds = new Set(sent.accepted_suggestions);
      setAccepted((list) => list.filter((a) => !sentIds.has(a.itemId)));
    }
  });
  const suggestions = useCurrentSuggestions(workflow.id);
  const startSuggestions = useStartSuggestions(workflow.id);
  const patchSuggestion = usePatchSuggestion(workflow.id);
  const closeSuggestions = useCloseSuggestions(workflow.id);
  const set = suggestions.data;
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

  const acceptedIds = useMemo(() => new Set(accepted.map((a) => a.itemId)), [accepted]);
  const open = set && set.status !== "closed" ? set : null;
  const pending = useMemo(() => open?.items.filter((i) => i.status === "pending" && !acceptedIds.has(i.id)) ?? [], [open, acceptedIds]);
  const drafts = useMemo(
    () => (reviewing ? pending.filter((i): i is AnswerSuggestion => i.kind === "answer") : []),
    [reviewing, pending],
  );

  const saveGraph = () =>
    save.mutateAsync({ graph, ...(accepted.length ? { accepted_suggestions: accepted.map((a) => a.itemId) } : {}) });

  function onSave() {
    // Accepted suggestions with others still waiting: say what the save keeps, and that calls change on republish.
    if (accepted.length > 0 && pending.length > 0) setConfirmSave(true);
    else saveGraph().catch(() => undefined);
  }

  async function suggest(request: StartSuggestions, saveFirst: boolean) {
    if (saveFirst) {
      try {
        await saveGraph();
      } catch {
        return;
      }
    }
    setAsking(null);
    setLastAsk(request);
    setStartError(null);
    setAccepted([]);
    setReviewing(true);
    try {
      await startSuggestions.mutateAsync(request);
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) setStartError({ message: "Daily limit reached. Try again tomorrow.", retry: false });
      else setStartError({ message: e instanceof ApiError ? e.detail : "Your workflow hasn't changed.", retry: true });
    }
  }

  /** "Suggest again" / "Try again": the same request as last time (or as the open draft's run). */
  function suggestAgain() {
    const again: StartSuggestions | null =
      lastAsk ??
      (open && (open.scope === "workflow" || open.step_ids[0])
        ? { scope: open.scope, kinds: open.kinds, ...(open.scope === "step" ? { step_id: open.step_ids[0] } : {}) }
        : null);
    if (again) void suggest(again, false);
    else setAsking({ scope: "workflow", stepId: null });
  }

  function accept(item: Suggestion): string | null {
    const result = applySuggestion(graph, item, pending);
    if (result.error || !result.applied) return result.error ?? "This suggestion can't be accepted.";
    const applied = result.applied;
    edit(() => result.graph);
    setAccepted((list) => [...list, applied]);
    return null;
  }

  function acceptAll(items: Suggestion[]) {
    let g = graph;
    const done: Applied[] = [];
    for (const item of items) {
      const rest = pending.filter((p) => !done.some((d) => d.itemId === p.id));
      const result = applySuggestion(g, item, rest);
      if (result.error || !result.applied) {
        toast.show(`Stopped at “${item.kind === "answer" ? item.payload.label : "expressions"}”: ${result.error}`, "bad");
        break;
      }
      g = result.graph;
      done.push(result.applied);
    }
    if (done.length) {
      edit(() => g);
      setAccepted((list) => [...list, ...done]);
    }
  }

  function undo() {
    const last = accepted[accepted.length - 1];
    if (!last) return;
    edit((g) => undoSuggestion(g, last));
    setAccepted((list) => list.slice(0, -1));
  }

  function dismiss(item: Suggestion) {
    patchSuggestion.mutate(
      { id: item.id, status: "dismissed" },
      { onError: (e) => toast.show(e instanceof ApiError ? e.detail : "Could not dismiss the suggestion.", "bad") },
    );
  }

  async function saveDraft(item: Suggestion, payload: Suggestion["payload"]): Promise<string | null> {
    try {
      await patchSuggestion.mutateAsync({ id: item.id, edited_payload: payload });
      return null;
    } catch (e) {
      return e instanceof ApiError ? e.detail : "Could not save the edit.";
    }
  }

  function discard() {
    if (!open) return;
    closeSuggestions.mutate(open.id, { onSuccess: () => setReviewing(false) });
  }

  async function testChat() {
    // "Test chat" runs the saved revision: save first, and stop if that fails (the toast says why).
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
        secondary={
          editable ? (
            <>
              <Button onClick={testChat} disabled={save.isPending}>Test chat</Button>
              <Button onClick={() => setAsking({ scope: selected ? "step" : "workflow", stepId: selected?.id ?? null })}>
                <Sparkles size={16} strokeWidth={1.75} aria-hidden="true" />
                Suggest with AI
              </Button>
            </>
          ) : undefined
        }
        primary={
          editable ? (
            <Button variant="primary" disabled={!dirty} loading={save.isPending} onClick={onSave}>
              Save
            </Button>
          ) : undefined
        }
      />
      <div className={styles.layout}>
        <div className={styles.main}>
          {!reviewing && open && (open.status === "running" ? open.created_by?.id === meId : pending.length > 0) && (
            <SuggestionBanner set={open} pending={pending.length} readOnly={!editable} onReview={() => setReviewing(true)} onDiscard={discard} />
          )}
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
            drafts={drafts}
          />
        </div>
        {reviewing ? (
          <SuggestionsPanel
            set={startSuggestions.isPending ? undefined : startError ? null : set}
            graph={graph}
            readOnly={!editable}
            builtins={expressions?.filter((e) => e.builtin)}
            acceptedIds={acceptedIds}
            canUndo={accepted.length > 0}
            startError={startError}
            starting={startSuggestions.isPending}
            onClose={() => {
              setReviewing(false);
              setStartError(null);
            }}
            onAccept={accept}
            onAcceptAll={acceptAll}
            onUndo={undo}
            onDismiss={dismiss}
            onSaveDraft={saveDraft}
            onDiscardAll={discard}
            onSuggestAgain={suggestAgain}
          />
        ) : (
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
            onSuggest={editable && selected ? () => setAsking({ scope: "step", stepId: selected.id }) : undefined}
            workflowSettings={<WorkflowSettings workflow={workflow} editable={editable} accountCheckIns={accountCheckIns} />}
          />
        )}
      </div>
      <SuggestDialog
        open={asking !== null}
        step={(() => {
          const s = graph.steps.find((x) => x.id === asking?.stepId);
          return s ? { id: s.id, name: s.name } : null;
        })()}
        initialScope={asking?.scope ?? "workflow"}
        dirty={dirty}
        current={open}
        meId={meId}
        saving={save.isPending}
        onClose={() => setAsking(null)}
        onSuggest={(request, saveFirst) => void suggest(request, saveFirst)}
      />
      <Dialog
        open={confirmSave}
        onClose={() => setConfirmSave(false)}
        title="Save accepted suggestions?"
        footer={
          <>
            <Button onClick={() => setConfirmSave(false)}>Keep reviewing</Button>
            <Button
              variant="primary"
              loading={save.isPending}
              onClick={() => {
                setConfirmSave(false);
                saveGraph().catch(() => undefined);
              }}
            >
              Save
            </Button>
          </>
        }
      >
        <dl className={styles.saveCounts}>
          <dt>Accepted</dt>
          <dd>{accepted.length}</dd>
          <dt>Still a draft</dt>
          <dd>{pending.length}</dd>
        </dl>
        <p className={styles.dialogText}>Suggestions still in the draft stay there for later. Calls change only when you republish the agent.</p>
      </Dialog>
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
