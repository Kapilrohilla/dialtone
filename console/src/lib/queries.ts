"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import type { Dashboard, LiveCall, Me, Preferences } from "@/lib/types";

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
  return useMutation({
    mutationFn: ({ room, handled }: { room: string; handled: boolean }) =>
      apiFetch<unknown>(`/api/calls/${encodeURIComponent(room)}/needs-person`, { method: "POST", json: { handled } }),
    onMutate: async ({ room, handled }) => {
      if (!handled) return {};
      await qc.cancelQueries({ queryKey: dashboardKey });
      const previous = qc.getQueryData<Dashboard>(dashboardKey);
      if (previous) qc.setQueryData<Dashboard>(dashboardKey, { ...previous, needs_person: previous.needs_person.filter((n) => n.room !== room) });
      return { previous };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.previous) qc.setQueryData(dashboardKey, ctx.previous);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: dashboardKey }),
  });
}
