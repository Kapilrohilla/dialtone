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

/** Every non-empty string in a DRF error value, depth first: nested serializers give
 *  `{"settings": {"dead_air": {"non_field_errors": ["…"]}}}` and list fields `{"script": [{}, {"body": ["…"]}]}`. */
function asStrings(v: unknown): string[] {
  if (typeof v === "string") return v ? [v] : [];
  if (Array.isArray(v)) return v.flatMap(asStrings);
  if (v && typeof v === "object") return Object.values(v).flatMap(asStrings);
  return [];
}

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

export type ApiInit = RequestInit & {
  json?: unknown;
  /** false: a signed-out 403 is only thrown (as a 401 ApiError), for screens that keep unsaved work on the page. */
  signInRedirect?: boolean;
};

export async function apiFetch<T>(path: string, init: ApiInit = {}): Promise<T> {
  const { json, headers: extra, signInRedirect = true, ...rest } = init;
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
      if (signInRedirect) goToSignIn();
      throw new ApiError(401, err.detail, err.fields);
    }
    throw err;
  }
  return body as T;
}
