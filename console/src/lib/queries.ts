"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import { useToast } from "@/components/ui";
import { ApiError, apiFetch, isSignedOut } from "@/lib/api";
import type {
  Agent,
  AgentListItem,
  AgentTextSetting,
  CallAudit,
  CallDetail,
  CallPage,
  Dashboard,
  Expression,
  Instance,
  KnowledgeDoc,
  KnowledgeListItem,
  LiveCall,
  Me,
  Preferences,
  PhoneNumber,
  Revision,
  Role,
  SimResponse,
  WebCallResponse,
  TeamMember,
  VoicesResponse,
  Graph,
  SuggestionSet,
  SuggestKind,
  SuggestScope,
  Workflow,
  WorkflowListItem,
  Workspace,
} from "@/lib/types";

// Query keys and hooks live here, one commented section per area. Later tasks add their own sections below.

// ---- me ----

export const meKey = ["me"] as const;

export function useMe() {
  return useQuery({ queryKey: meKey, queryFn: () => apiFetch<Me>("/api/me"), staleTime: 60_000 });
}

export type MeUpdate = { name?: string; phone?: string; preferences?: Partial<Preferences> };

export function useUpdateMe() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: MeUpdate) => apiFetch<Me>("/api/me", { method: "PATCH", json: body }),
    onSuccess: (me) => qc.setQueryData(meKey, me),
  });
}

/** Account-wide switches (owners and admins). The saved workspace replaces the one inside `me`. */
export function useUpdateWorkspace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (
      body: Partial<
        Pick<Workspace, "dead_air_enabled" | "recording_enabled" | "audit_enabled" | "audit_sample_pct" | "audit_weights" | "audit_instructions">
      >,
    ) => apiFetch<Workspace>("/api/workspace", { method: "PATCH", json: body }),
    onSuccess: (workspace) => qc.setQueryData<Me>(meKey, (me) => (me ? { ...me, workspace } : me)),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  const router = useRouter();
  const toast = useToast();
  return useMutation({
    mutationFn: () => apiFetch<void>("/api/auth/logout", { method: "POST" }),
    onSuccess: () => {
      qc.clear();
      router.replace("/sign-in");
    },
    onError: (e) => toast.show(e instanceof ApiError ? e.detail : "Could not sign out. Check your connection and try again.", "bad"),
  });
}

// ---- instance ----

/** What the console calls itself when the server can't say. */
export const DEFAULT_PROJECT_NAME = "Dialtone";

export const instanceKey = ["instance"] as const;

/** This install's name. Public: the sign-in and set-password screens read it too, so a failure never redirects. */
export function useInstance() {
  return useQuery({
    queryKey: instanceKey,
    queryFn: () => apiFetch<Instance>("/api/instance/", { signInRedirect: false }),
    staleTime: 5 * 60_000,
  });
}

/** The project name to show: the saved one, or "Dialtone" while loading or when the server can't be reached. */
export function useProjectName(): string {
  return useInstance().data?.project_name || DEFAULT_PROJECT_NAME;
}

/** The tab title with `from` swapped for `to`: "Agents - Old" → "Agents - New", "Old" → "New". Any other title becomes `to`. */
export function retitle(title: string, from: string, to: string): string {
  if (title === from) return to;
  const suffix = ` - ${from}`;
  return title.endsWith(suffix) ? title.slice(0, -suffix.length) + ` - ${to}` : to;
}

/** Renames the install (superusers only). The sidebar and the open tab's title change at once; field errors stay on the error. */
export function useUpdateInstance() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Instance) => apiFetch<Instance>("/api/instance/", { method: "PATCH", json: body }),
    onSuccess: (saved) => {
      const before = qc.getQueryData<Instance>(instanceKey)?.project_name || DEFAULT_PROJECT_NAME;
      qc.setQueryData(instanceKey, saved);
      document.title = retitle(document.title, before, saved.project_name);
    },
  });
}

// ---- live ----

export const liveKey = ["live"] as const;

/** Calls in progress. Pass the poll interval in ms (0 reads the cache without polling). The sidebar polls at 10000
 *  and goes quiet on the Live calls screen, which polls at 2000 on the same key. The sidebar passes
 *  `signInRedirect: false`: its background poll must never navigate away from unsaved edits (the next thing
 *  the user does still goes to sign-in). */
export function useLiveCalls(refetchMs: number, { signInRedirect = true }: { signInRedirect?: boolean } = {}) {
  return useQuery({
    queryKey: liveKey,
    queryFn: () => apiFetch<LiveCall[]>("/api/live", { signInRedirect }),
    refetchInterval: refetchMs || false,
  });
}

type LiveAnswer = { detail: string };

function useLiveAction(action: "transfer" | "end") {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (room: string) => apiFetch<LiveAnswer>(`/api/live/${encodeURIComponent(room)}/${action}`, { method: "POST" }),
    onSuccess: (answer) => {
      toast.show(answer.detail, "ok");
      return qc.invalidateQueries({ queryKey: liveKey });
    },
    onError: (e) => toast.show(e instanceof ApiError ? e.detail : "Couldn't reach the call server.", "bad"),
  });
}

/** Hands the caller to the telecalling team. The toast carries the API's words (e.g. "Live transfer isn't set up."). */
export const useTransfer = () => useLiveAction("transfer");

/** Disconnects the caller. */
export const useEndCall = () => useLiveAction("end");

// ---- calls ----

export type CallFilters = {
  q?: string;
  outcome?: string;
  agent?: string;
  mood?: string;
  city?: string;
  from?: string;
  to?: string;
  /** Audit score range, 0–100. */
  score_min?: string;
  score_max?: string;
  page?: number;
};

const FILTER_ORDER = ["q", "outcome", "agent", "mood", "city", "from", "to", "score_min", "score_max", "page"] as const;

/** The filters as a query string (no leading "?"), empty ones left out. Shared by the list, the CSV link and the page URL. */
export function callsQuery(filters: CallFilters): string {
  const params = new URLSearchParams();
  for (const key of FILTER_ORDER) {
    const value = filters[key];
    if (value !== undefined && value !== "" && !(key === "page" && value === 1)) params.set(key, String(value));
  }
  return params.toString();
}

export const callsKey = (filters: CallFilters) => ["calls", callsQuery(filters)] as const;

/** One page of call history. The previous page stays on screen while the next loads. */
export function useCalls(filters: CallFilters, { enabled = true }: { enabled?: boolean } = {}) {
  const query = callsQuery(filters);
  return useQuery({
    queryKey: callsKey(filters),
    queryFn: () => apiFetch<CallPage>(`/api/calls${query ? `?${query}` : ""}`),
    placeholderData: keepPreviousData,
    enabled,
  });
}

const RECORDING_POLL_MS = 5_000;
const RECORDING_POLL_FOR_MS = 120_000;

/** One call. While its recording is still processing it polls every 5 s, for up to 2 minutes after opening. */
export function useCall(room: string | null) {
  const qc = useQueryClient();
  const opened = useRef(Date.now());
  const lastStatus = useRef<string | undefined>(undefined);
  const query = useQuery({
    queryKey: ["call", room],
    queryFn: () => apiFetch<CallDetail>(`/api/calls/${encodeURIComponent(room ?? "")}`),
    enabled: room !== null,
    refetchInterval: (q) =>
      q.state.data?.recording_status === "processing" && Date.now() - opened.current < RECORDING_POLL_FOR_MS ? RECORDING_POLL_MS : false,
  });
  // When processing finishes, the list rows need the new state too.
  const status = query.data?.recording_status;
  useEffect(() => {
    if (lastStatus.current === "processing" && status !== "processing") qc.invalidateQueries({ queryKey: ["calls"] });
    lastStatus.current = status;
  }, [status, qc]);
  return query;
}

const AUDIT_POLL_MS = 3_000;

export const callAuditKey = (room: string | null) => ["call-audit", room] as const;

/** A call's current audit. Polls every 3 s while it is queued or running. */
export function useCallAudit(room: string | null) {
  const qc = useQueryClient();
  const lastStatus = useRef<string | undefined>(undefined);
  const query = useQuery({
    queryKey: callAuditKey(room),
    queryFn: () => apiFetch<CallAudit>(`/api/calls/${encodeURIComponent(room ?? "")}/audit`),
    enabled: room !== null,
    refetchInterval: (q) => (q.state.data?.status === "queued" || q.state.data?.status === "running" ? AUDIT_POLL_MS : false),
  });
  // A finished audit changes the list's Score column.
  const status = query.data?.status;
  useEffect(() => {
    if ((lastStatus.current === "queued" || lastStatus.current === "running") && status !== lastStatus.current) {
      qc.invalidateQueries({ queryKey: ["calls"] });
    }
    lastStatus.current = status;
  }, [status, qc]);
  return query;
}

/** Audit a call now, or re-audit it (editors). */
export function useRunAudit(room: string) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: () => apiFetch<CallAudit>(`/api/calls/${encodeURIComponent(room)}/audit`, { method: "POST" }),
    onSuccess: (audit) => qc.setQueryData(callAuditKey(room), audit),
    onError: (e) => {
      toast.show(e instanceof ApiError ? e.detail : "Could not start the audit.", "bad");
      qc.invalidateQueries({ queryKey: callAuditKey(room) });
    },
  });
}

/** Marks a call for a call back; it then shows on the dashboard under "Needs a person". Marking twice is harmless. */
export function useMarkNeedsPerson() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (room: string) => apiFetch<unknown>(`/api/calls/${encodeURIComponent(room)}/needs-person`, { method: "POST", json: { needs_person: true } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: dashboardKey }),
    onError: (e) => toast.show(e instanceof ApiError ? e.detail : "Could not mark this call.", "bad"),
  });
}

// ---- dashboard ----

export const dashboardKey = ["dashboard"] as const;

export function useDashboard() {
  return useQuery({ queryKey: dashboardKey, queryFn: () => apiFetch<Dashboard>("/api/dashboard") });
}

/** Marks a call back request handled (or, with `handled: false`, puts it back). The row leaves the list at once. */
export function useMarkHandled() {
  const qc = useQueryClient();
  const toast = useToast();
  const mutation = useMutation({
    mutationFn: ({ room, handled }: { room: string; handled: boolean }) =>
      apiFetch<unknown>(`/api/calls/${encodeURIComponent(room)}/needs-person`, { method: "POST", json: { handled } }),
    onMutate: async ({ room, handled }) => {
      if (!handled) return {};
      await qc.cancelQueries({ queryKey: dashboardKey });
      const previous = qc.getQueryData<Dashboard>(dashboardKey);
      if (previous) qc.setQueryData<Dashboard>(dashboardKey, { ...previous, needs_person: previous.needs_person.filter((n) => n.room !== room) });
      return { previous };
    },
    onSuccess: (_d, { room, handled }) => {
      if (handled) toast.show("Marked as handled.", "ok", { label: "Undo", onClick: () => mutation.mutate({ room, handled: false }) });
    },
    onError: (e, { handled }, ctx) => {
      if (ctx?.previous) qc.setQueryData(dashboardKey, ctx.previous);
      toast.show(e instanceof ApiError ? e.detail : handled ? "Could not mark as handled." : "Could not undo.", "bad");
    },
    onSettled: () => qc.invalidateQueries({ queryKey: dashboardKey }),
  });
  return mutation;
}

// ---- agents ----

export const agentsKey = ["agents"] as const;
export const agentKey = (id: number) => ["agent", id] as const;
export const expressionsKey = ["expressions"] as const;
export const voicesKey = ["voices"] as const;

/** Every agent in the workspace, archived ones included. Screens filter on `status`. */
export function useAgents() {
  return useQuery({ queryKey: agentsKey, queryFn: () => apiFetch<AgentListItem[]>("/api/agents") });
}

export function useAgent(id: number) {
  return useQuery({ queryKey: agentKey(id), queryFn: () => apiFetch<Agent>(`/api/agents/${id}`) });
}

/** Every agent's "older version" flag (list and each open agent), after a change to something agents use. */
function invalidateOutdatedFlags(qc: ReturnType<typeof useQueryClient>) {
  return Promise.all([qc.invalidateQueries({ queryKey: agentsKey }), qc.invalidateQueries({ queryKey: ["agent"] })]);
}

function useInvalidateAgents() {
  const qc = useQueryClient();
  return (id?: number) =>
    Promise.all([
      qc.invalidateQueries({ queryKey: agentsKey }),
      id === undefined ? undefined : qc.invalidateQueries({ queryKey: agentKey(id) }),
      qc.invalidateQueries({ queryKey: dashboardKey }),
    ]);
}

export function useCreateAgent() {
  const invalidate = useInvalidateAgents();
  const toast = useToast();
  return useMutation({
    mutationFn: (body: { name: string }) => apiFetch<Agent>("/api/agents", { method: "POST", json: body }),
    onSuccess: (agent) => invalidate(agent.id),
    onError: (e) => toast.show(e instanceof ApiError ? e.detail : "Could not create the agent.", "bad"),
  });
}

export type AgentUpdate = Partial<
  Pick<Agent, "name" | "description" | "language" | "persona_name" | "voice_id" | "script" | "custom_expressions" | "knowledge" | "workflow" | "phone_number">
> & {
  /** Deep-merged over the saved settings by the server, so send only what changed. */
  settings?: { mood_adaptation?: boolean; dead_air?: Partial<Agent["settings"]["dead_air"]> } & Partial<Pick<Agent["settings"], AgentTextSetting>>;
};

/** PATCH only the fields that changed. `signInRedirect: false` leaves a signed-out error to the screen
 *  (the script editor keeps the unsaved text on the page). */
export function useUpdateAgent(id: number, { signInRedirect = true }: { signInRedirect?: boolean } = {}) {
  const qc = useQueryClient();
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: (body: AgentUpdate) => apiFetch<Agent>(`/api/agents/${id}`, { method: "PATCH", json: body, signInRedirect }),
    onSuccess: (agent) => {
      qc.setQueryData(agentKey(id), agent);
      return invalidate(id);
    },
  });
}

/** Publish errors arrive as `{"errors": [...]}`; read them from `error.fields.errors`. */
export function usePublish() {
  const invalidate = useInvalidateAgents();
  const toast = useToast();
  return useMutation({
    mutationFn: (id: number) => apiFetch<{ version: number }>(`/api/agents/${id}/publish`, { method: "POST" }),
    onSuccess: (_d, id) => {
      toast.show("Published. It will answer the next call.", "ok");
      return invalidate(id);
    },
  });
}

function useAgentAction(action: "unpublish" | "archive" | "restore", done: string, failed: string) {
  const invalidate = useInvalidateAgents();
  const toast = useToast();
  return useMutation({
    mutationFn: (id: number) => apiFetch<Agent>(`/api/agents/${id}/${action}`, { method: "POST" }),
    onSuccess: (_d, id) => {
      toast.show(done, "ok");
      return invalidate(id);
    },
    onError: (e) => toast.show(e instanceof ApiError ? e.detail : failed, "bad"),
  });
}

export const useUnpublish = () => useAgentAction("unpublish", "Unpublished. Callers hear the built-in script.", "Could not unpublish.");
export const useArchive = () => useAgentAction("archive", "Archived.", "Could not archive.");
export const useRestore = () => useAgentAction("restore", "Restored as a draft.", "Could not restore.");

export function useDuplicate() {
  const invalidate = useInvalidateAgents();
  const toast = useToast();
  return useMutation({
    mutationFn: (id: number) => apiFetch<Agent>(`/api/agents/${id}/duplicate`, { method: "POST" }),
    onSuccess: (copy) => {
      toast.show(`Duplicated as ${copy.name}.`, "ok");
      return invalidate(copy.id);
    },
    onError: (e) => toast.show(e instanceof ApiError ? e.detail : "Could not duplicate.", "bad"),
  });
}

export function useExpressions() {
  return useQuery({ queryKey: expressionsKey, queryFn: () => apiFetch<Expression[]>("/api/expressions"), staleTime: 300_000 });
}

export function useVoices() {
  return useQuery({ queryKey: voicesKey, queryFn: () => apiFetch<VoicesResponse>("/api/voices"), staleTime: 300_000 });
}

// ---- knowledge ----

export const knowledgeListKey = ["knowledge"] as const;

export function useKnowledgeList() {
  return useQuery({ queryKey: knowledgeListKey, queryFn: () => apiFetch<KnowledgeListItem[]>("/api/knowledge") });
}

export const knowledgeDocKey = (id: number) => ["knowledge", "doc", id] as const;
const revisionsKey = (id: number) => ["knowledge", "doc", id, "revisions"] as const;

export function useKnowledgeDoc(id: number | undefined) {
  return useQuery({
    queryKey: knowledgeDocKey(id ?? 0),
    queryFn: () => apiFetch<KnowledgeDoc>(`/api/knowledge/${id}`),
    enabled: id !== undefined,
  });
}

/** A document the server just returned: cached, and added to the list so it can be selected before the list refetches. */
function useRememberDoc() {
  const qc = useQueryClient();
  return (doc: KnowledgeDoc) => {
    qc.setQueryData(knowledgeDocKey(doc.id), doc);
    const item: KnowledgeListItem = { id: doc.id, title: doc.title, updated_at: doc.updated_at, current_revision: doc.current_revision, used_by: doc.used_by };
    qc.setQueryData<KnowledgeListItem[]>(knowledgeListKey, (list) =>
      list ? (list.some((d) => d.id === doc.id) ? list.map((d) => (d.id === doc.id ? item : d)) : [...list, item]) : list,
    );
    return qc.invalidateQueries({ queryKey: knowledgeListKey, exact: true });
  };
}

export function useCreateDoc() {
  const remember = useRememberDoc();
  const toast = useToast();
  return useMutation({
    mutationFn: (body: { title: string; body_md: string }) => apiFetch<KnowledgeDoc>("/api/knowledge", { method: "POST", json: body }),
    onSuccess: remember,
    onError: (e) => toast.show(e instanceof ApiError ? e.detail : "Could not create the document.", "bad"),
  });
}

/** Multipart upload of one .md file (field `file`); the API's file errors (wrong type, too large, not UTF-8) are toasted. */
export function useUploadDoc() {
  const remember = useRememberDoc();
  const toast = useToast();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return apiFetch<KnowledgeDoc>("/api/knowledge/upload", { method: "POST", body: form });
    },
    onSuccess: remember,
    onError: (e) => toast.show(e instanceof ApiError ? e.detail : "Could not upload the file.", "bad"),
  });
}

export type DocUpdate = { title?: string; body_md?: string };

/** PATCH only what changed. Saving is deliberate on this screen, so the toast says what happens next. */
/** `onSaved` runs with the saved document in the same tick the cache is updated. */
export function useSaveDoc(id: number, onSaved?: (doc: KnowledgeDoc, sent: DocUpdate) => void) {
  const qc = useQueryClient();
  const remember = useRememberDoc();
  const toast = useToast();
  return useMutation({
    mutationFn: (body: DocUpdate) => apiFetch<KnowledgeDoc>(`/api/knowledge/${id}`, { method: "PATCH", json: body, signInRedirect: false }),
    onSuccess: (doc, sent) => {
      toast.show(doc.used_by > 0 ? "Saved. Agents using this document need republishing before callers hear the change." : "Saved.", "ok");
      onSaved?.(doc, sent);
      qc.invalidateQueries({ queryKey: revisionsKey(id) });
      void invalidateOutdatedFlags(qc);
      return remember(doc);
    },
    onError: (e) =>
      toast.show(isSignedOut(e) ? "You were signed out. Sign in again in another tab, then save." : e instanceof ApiError ? e.detail : "Could not save.", "bad"),
  });
}

/** DELETE a document. It leaves every agent that linked it (published ones keep quoting it until they are
 *  published again); the server refuses while a workflow step answers from it, and that reason is toasted. */
export function useDeleteDoc() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/api/knowledge/${id}`, { method: "DELETE" }),
    onSuccess: (_, id) => {
      qc.setQueryData<KnowledgeListItem[]>(knowledgeListKey, (list) => list?.filter((d) => d.id !== id));
      qc.removeQueries({ queryKey: knowledgeDocKey(id) });
      toast.show("Deleted.", "ok");
      void invalidateOutdatedFlags(qc);
      return qc.invalidateQueries({ queryKey: knowledgeListKey, exact: true });
    },
    onError: (e) => toast.show(e instanceof ApiError ? e.detail : "Could not delete the document.", "bad"),
  });
}

/** Newest first. */
export function useRevisions(id: number | undefined) {
  return useQuery({
    queryKey: revisionsKey(id ?? 0),
    queryFn: async () => (await apiFetch<Revision[]>(`/api/knowledge/${id}/revisions`)).sort((a, b) => b.number - a.number),
    enabled: id !== undefined,
  });
}

export function useRevision(id: number | undefined, n: number | null) {
  return useQuery({
    queryKey: [...revisionsKey(id ?? 0), n],
    queryFn: () => apiFetch<Revision>(`/api/knowledge/${id}/revisions/${n}`),
    enabled: id !== undefined && n !== null,
  });
}

// ---- workflows ----

export const workflowsKey = ["workflows"] as const;

export function useWorkflows() {
  return useQuery({ queryKey: workflowsKey, queryFn: () => apiFetch<WorkflowListItem[]>("/api/workflows") });
}

export const workflowKey = (id: number) => ["workflow", id] as const;

export function useWorkflow(id: number) {
  return useQuery({ queryKey: workflowKey(id), queryFn: () => apiFetch<Workflow>(`/api/workflows/${id}`) });
}

/** The graph a new workflow starts with: one start step. */
export const NEW_WORKFLOW_GRAPH: Graph = {
  steps: [{ id: "start", type: "start", name: "Greeting", prompt: "", position: { x: 0, y: 0 } }],
  paths: [],
};

/** POST creates an empty workflow, then its first revision is saved with the start step. */
export function useCreateWorkflow() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: async (body: { name: string }) => {
      const created = await apiFetch<Workflow>("/api/workflows", { method: "POST", json: body });
      try {
        return await apiFetch<Workflow>(`/api/workflows/${created.id}`, { method: "PATCH", json: { graph: NEW_WORKFLOW_GRAPH } });
      } catch {
        // The workflow exists without its start step: open it anyway (Add step works there) rather than hide it.
        toast.show("Created, but the start step could not be added. Add a step to begin.", "bad");
        return created;
      }
    },
    onSuccess: (wf) => {
      qc.setQueryData(workflowKey(wf.id), wf);
      return qc.invalidateQueries({ queryKey: workflowsKey });
    },
    onError: (e) => toast.show(e instanceof ApiError ? e.detail : "Could not create the workflow.", "bad"),
  });
}

export type WorkflowUpdate = {
  name?: string;
  graph?: Graph;
  dead_air_enabled?: boolean;
  /** "Suggest with AI" items accepted into this graph; they are marked accepted with the save. */
  accepted_suggestions?: number[];
};

/** PATCH the name or the whole graph. A saved graph is toasted with what happens next; `errors` in the answer
 *  are the server's checks of the saved graph. Signed out keeps the draft on the page. `onSaved` runs with the
 *  saved workflow in the same tick the cache is updated. */
export function useSaveWorkflow(id: number, onSaved?: (wf: Workflow, sent: WorkflowUpdate) => void) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (body: WorkflowUpdate) =>
      apiFetch<Workflow>(`/api/workflows/${id}`, { method: "PATCH", json: body, signInRedirect: false }),
    onSuccess: async (wf, sent) => {
      onSaved?.(wf, sent);
      qc.setQueryData(workflowKey(id), wf);
      // Saved graphs re-check the draft suggestions (accepted, out of date).
      if (sent.graph) qc.invalidateQueries({ queryKey: suggestionsKey(id) });
      qc.invalidateQueries({ queryKey: workflowsKey });
      // A rename changes nothing callers hear; the graph and the dead-air switch are published with agents.
      if (!sent.graph && sent.dead_air_enabled === undefined) return;
      // Agents using it are now outdated; read the fresh list below to word the toast.
      await invalidateOutdatedFlags(qc);
      const agents = await qc
        .ensureQueryData({ queryKey: agentsKey, queryFn: () => apiFetch<AgentListItem[]>("/api/agents") })
        .catch(() => undefined);
      const used = agents?.some((a) => a.workflow === id && a.status !== "archived");
      toast.show(used ? "Saved. Agents using this workflow need republishing before callers hear the change." : "Saved.", "ok");
    },
    onError: (e) =>
      toast.show(isSignedOut(e) ? "You were signed out. Sign in again in another tab, then save." : e instanceof ApiError ? e.detail : "Could not save.", "bad"),
  });
}

// ---- suggest with AI ----

export const suggestionsKey = (workflowId: number) => ["workflow", workflowId, "suggestions"] as const;

/** Checked again every 1.5 s while a run is going. */
export const SUGGEST_POLL_MS = 1500;

/** The workflow's open "Suggest with AI" draft, or null when there is none. Polls while the run is going. */
export function useCurrentSuggestions(workflowId: number) {
  return useQuery({
    queryKey: suggestionsKey(workflowId),
    queryFn: async () => (await apiFetch<SuggestionSet | undefined>(`/api/workflows/${workflowId}/suggestions/current`)) ?? null,
    refetchInterval: (q) => (q.state.data?.status === "running" ? SUGGEST_POLL_MS : false),
  });
}

export type StartSuggestions = { scope: SuggestScope; step_id?: string; kinds: SuggestKind[] };

/** Starts a run. A 429 ("Daily limit reached") comes back as the ApiError; the caller shows it in the panel. */
export function useStartSuggestions(workflowId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: StartSuggestions) =>
      apiFetch<SuggestionSet>(`/api/workflows/${workflowId}/suggestions`, { method: "POST", json: body }),
    onSuccess: (set) => qc.setQueryData(suggestionsKey(workflowId), set),
  });
}

export type SuggestionPatch = { id: number; edited_payload?: unknown; status?: "pending" | "dismissed" };

/** Saves an edit to the draft, or dismisses / restores an item. Field errors come back as the ApiError's fields. */
export function usePatchSuggestion(workflowId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: SuggestionPatch) =>
      apiFetch<SuggestionSet>(`/api/workflows/${workflowId}/suggestions/${id}`, { method: "PATCH", json: body }),
    onSuccess: (set) => qc.setQueryData(suggestionsKey(workflowId), set),
  });
}

/** "Discard all" / "Discard draft": dismisses every pending item and closes the draft. */
export function useCloseSuggestions(workflowId: number) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (setId: number) => apiFetch<void>(`/api/workflows/${workflowId}/suggestions/${setId}/close`, { method: "POST" }),
    onSuccess: () => qc.setQueryData(suggestionsKey(workflowId), null),
    onError: (e) => toast.show(e instanceof ApiError ? e.detail : "Could not discard the suggestions.", "bad"),
  });
}

// ---- sim ----

export type SimMessage = { role: "caller" | "agent"; text: string };
export type SimRequest = { messages: SimMessage[]; state: Record<string, unknown> | null };

/** One turn of the text simulator ("Test chat", for an agent's draft or a workflow). Nothing is saved. */
export function useSimulate(kind: "agent" | "workflow", id: number) {
  const path = `/api/${kind === "agent" ? "agents" : "workflows"}/${id}/simulate`;
  return useMutation({ mutationFn: (body: SimRequest) => apiFetch<SimResponse>(path, { method: "POST", json: body }) });
}

/** A LiveKit token for a voice test of the agent's draft in the browser (no phone call). */
export function useWebCall(agentId: number) {
  return useMutation({
    mutationFn: () => apiFetch<WebCallResponse>(`/api/agents/${agentId}/web-call`, { method: "POST" }),
  });
}

// ---- team ----

export const teamKey = ["team"] as const;

export function useTeam() {
  return useQuery({ queryKey: teamKey, queryFn: () => apiFetch<TeamMember[]>("/api/team") });
}

export type Invite = { email: string; name: string; role: Role };

/** Adds a member and returns their one-time set-password link as a path. Field errors (e.g. email) stay on the error for the dialog. */
export function useInvite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Invite) => apiFetch<{ set_password_url: string }>("/api/team", { method: "POST", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: teamKey }),
  });
}

/** Changes a member's role. The toast carries the API's words (e.g. "Only an owner can do that."). */
export function useSetRole() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: ({ id, role }: { id: number; role: Role }) => apiFetch<TeamMember>(`/api/team/${id}`, { method: "PATCH", json: { role } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: teamKey }),
    onError: (e) => toast.show(e instanceof ApiError ? e.detail : "Could not change the role.", "bad"),
  });
}

// ---- numbers ----

export function usePhoneNumbers() {
  return useQuery({ queryKey: ["phone-numbers"], queryFn: () => apiFetch<PhoneNumber[]>("/api/phone-numbers") });
}

// ---- integrations ----

/** Tells us which tool a workspace wants next. Any member may ask. */
export function useRequestIntegration() {
  return useMutation({ mutationFn: (body: { tool: string; note: string }) => apiFetch<unknown>("/api/integrations/requests", { method: "POST", json: body }) });
}

// ---- password ----

/** Field errors arrive on current_password and new_password. */
export function useChangePassword() {
  return useMutation({ mutationFn: (body: { current_password: string; new_password: string }) => apiFetch<void>("/api/me/password", { method: "POST", json: body }) });
}
