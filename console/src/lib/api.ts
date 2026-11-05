const SIGNED_OUT_DETAIL = "Authentication credentials were not provided.";
const FALLBACK = "Something went wrong. Try again.";
const CSRF_COOKIE = "csrftoken";

export class ApiError extends Error {
  status: number;
  detail: string;
  fields: Record<string, string[]>;

  constructor(status: number, detail: string, fields: Record<string, string[]> = {}) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.fields = fields;
  }
}

export function isSignedOut(e: unknown): boolean {
  return e instanceof ApiError && e.status === 401;
}

function readCookie(name: string): string | undefined {
  const hit = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return hit ? decodeURIComponent(hit.slice(name.length + 1)) : undefined;
}

let csrfRequest: Promise<unknown> | null = null;

async function csrfToken(): Promise<string | undefined> {
  if (!readCookie(CSRF_COOKIE)) {
    csrfRequest ??= fetch("/api/auth/csrf", { credentials: "same-origin" })
      .catch(() => undefined)
      .finally(() => {
        csrfRequest = null;
      });
    await csrfRequest;
  }
  return readCookie(CSRF_COOKIE);
}

const asStrings = (v: unknown): string[] =>
  (Array.isArray(v) ? v : [v]).filter((x): x is string => typeof x === "string" && x !== "");

function parseError(status: number, body: unknown): ApiError {
  const fields: Record<string, string[]> = {};
  let detail = "";
  if (body && typeof body === "object" && !Array.isArray(body)) {
    for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
      if (key === "detail") continue;
      const list = asStrings(value);
      if (list.length) fields[key] = list;
    }
    const d = (body as { detail?: unknown }).detail;
    if (typeof d === "string" && d) detail = d;
  } else if (Array.isArray(body)) {
    const list = asStrings(body);
    if (list.length) fields.errors = list;
  }
  if (!detail) detail = Object.values(fields)[0]?.[0] ?? FALLBACK;
  return new ApiError(status, detail, fields);
}

function goToSignIn() {
  const { pathname, search } = globalThis.location;
  if (pathname.startsWith("/sign-in") || pathname.startsWith("/set-password")) return;
  globalThis.location.assign("/sign-in?next=" + encodeURIComponent(pathname + search));
}

export async function apiFetch<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers: extra, ...rest } = init;
  const method = (rest.method ?? "GET").toUpperCase();
  const headers = new Headers(extra);
  if (json !== undefined) headers.set("Content-Type", "application/json");
  if (method !== "GET" && method !== "HEAD") {
    const token = await csrfToken();
    if (token) headers.set("X-CSRFToken", token);
  }
  const res = await fetch(path, {
    ...rest,
    method,
    headers,
    credentials: "same-origin",
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (res.status === 204) return undefined as T;
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    body = undefined;
  }
  if (!res.ok) {
    const err = parseError(res.status, body);
    if (res.status === 403 && err.detail === SIGNED_OUT_DETAIL) {
      goToSignIn();
      throw new ApiError(401, err.detail, err.fields);
    }
    throw err;
  }
  return body as T;
}
