"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import type { LiveCall, Me, Preferences } from "@/lib/types";

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
