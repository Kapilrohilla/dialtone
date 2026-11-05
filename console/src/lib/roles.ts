import type { Role } from "@/lib/types";

export const canEdit = (role: Role | undefined): boolean => role === "owner" || role === "admin" || role === "editor";
export const canManageTeam = (role: Role | undefined): boolean => role === "owner" || role === "admin";
export const isOwner = (role: Role | undefined): boolean => role === "owner";
