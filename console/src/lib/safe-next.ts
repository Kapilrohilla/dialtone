/** A post-sign-in destination is only trusted when it is a path on this site: starts with "/", not "//", no backslashes. */
export function safeNext(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return "/";
  return value;
}
