"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/ui";
import { ApiError, apiFetch } from "@/lib/api";
import type { Agent, AgentListItem, Dashboard, Expression, LiveCall, Me, Preferences, VoicesResponse } from "@/lib/types";

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

/** PATCH only the fields that changed. */
export function useUpdateAgent(id: number) {
  const qc = useQueryClient();
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: (body: Partial<Pick<Agent, "name" | "description" | "language" | "persona_name" | "voice_id" | "settings" | "script" | "custom_expressions" | "knowledge" | "workflow" | "phone_number">>) =>
      apiFetch<Agent>(`/api/agents/${id}`, { method: "PATCH", json: body }),
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
