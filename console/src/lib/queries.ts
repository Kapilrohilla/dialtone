"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/ui";
import { ApiError, apiFetch, isSignedOut } from "@/lib/api";
import type {
  Agent,
  AgentListItem,
  Dashboard,
  Expression,
  KnowledgeDoc,
  KnowledgeListItem,
  LiveCall,
  Me,
  Preferences,
  Revision,
  SimResponse,
  VoicesResponse,
  Graph,
  Workflow,
  WorkflowListItem,
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

export function useLogout() {
  const qc = useQueryClient();
  const router = useRouter();
  return useMutation({
    mutationFn: () => apiFetch<void>("/api/auth/logout", { method: "POST" }),
    onSuccess: () => {
      qc.clear();
      router.replace("/sign-in");
    },
  });
}

// ---- live ----

export const liveKey = ["live"] as const;

/** Calls in progress. Pass the poll interval in ms; the sidebar uses 10000. */
export function useLiveCalls(refetchMs: number) {
  return useQuery({ queryKey: liveKey, queryFn: () => apiFetch<LiveCall[]>("/api/live"), refetchInterval: refetchMs });
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
  settings?: { mood_adaptation?: boolean; dead_air?: Partial<Agent["settings"]["dead_air"]> };
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
      return remember(doc);
    },
    onError: (e) =>
      toast.show(isSignedOut(e) ? "You were signed out. Sign in again in another tab, then save." : e instanceof ApiError ? e.detail : "Could not save.", "bad"),
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
      return apiFetch<Workflow>(`/api/workflows/${created.id}`, { method: "PATCH", json: { graph: NEW_WORKFLOW_GRAPH } });
    },
    onSuccess: (wf) => {
      qc.setQueryData(workflowKey(wf.id), wf);
      return qc.invalidateQueries({ queryKey: workflowsKey });
    },
    onError: (e) => toast.show(e instanceof ApiError ? e.detail : "Could not create the workflow.", "bad"),
  });
}

export type WorkflowUpdate = { name?: string; graph?: Graph };

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
      qc.invalidateQueries({ queryKey: workflowsKey });
      if (!sent.graph) return;
      const agents = await qc
        .ensureQueryData({ queryKey: agentsKey, queryFn: () => apiFetch<AgentListItem[]>("/api/agents") })
        .catch(() => undefined);
      const used = agents?.some((a) => a.workflow === id && a.status !== "archived");
      toast.show(used ? "Saved. Agents using this workflow need republishing before callers hear the change." : "Saved.", "ok");
      // Their "older version" flags change with the workflow.
      if (used) qc.invalidateQueries({ queryKey: agentsKey });
    },
    onError: (e) =>
      toast.show(isSignedOut(e) ? "You were signed out. Sign in again in another tab, then save." : e instanceof ApiError ? e.detail : "Could not save.", "bad"),
  });
}

// ---- sim ----

export type SimMessage = { role: "caller" | "agent"; text: string };
export type SimRequest = { messages: SimMessage[]; state: Record<string, unknown> | null };

/** One turn of the text simulator ("Test call" for an agent's draft, "Try it" for a workflow). Nothing is saved. */
export function useSimulate(kind: "agent" | "workflow", id: number) {
  const path = `/api/${kind === "agent" ? "agents" : "workflows"}/${id}/simulate`;
  return useMutation({ mutationFn: (body: SimRequest) => apiFetch<SimResponse>(path, { method: "POST", json: body }) });
}
