import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch, isSignedOut } from "@/lib/api";
import { server } from "@/test/server";

const caught = async (p: Promise<unknown>) => (await p.catch((x: unknown) => x)) as ApiError;

describe("apiFetch", () => {
  it("sends the csrf token on writes, fetching it once if missing", async () => {
    const seen: string[] = [];
    server.use(
      http.get("*/api/auth/csrf", () => {
        seen.push("GET csrf");
        document.cookie = "csrftoken=tok123; path=/";
        return HttpResponse.json({ detail: "ok" });
      }),
      http.post("*/api/things", ({ request }) => {
        seen.push(`POST ${request.headers.get("X-CSRFToken")}`);
        return HttpResponse.json({ id: 1 }, { status: 201 });
      }),
    );
    await apiFetch("/api/things", { method: "POST", json: { a: 1 } });
    await apiFetch("/api/things", { method: "POST", json: { a: 2 } });
    expect(seen).toEqual(["GET csrf", "POST tok123", "POST tok123"]);
  });

  it("does not fetch a csrf token for reads, and returns undefined on 204", async () => {
    server.use(http.delete("*/api/things/1", () => new HttpResponse(null, { status: 204 })));
    document.cookie = "csrftoken=abc; path=/";
    await expect(apiFetch("/api/things/1", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("redirects on signed-out 403 but not on permission 403", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/agents/3", search: "", origin: "http://localhost:3000", href: "http://localhost:3000/agents/3", assign });
    server.use(
      http.get("*/api/me", () =>
        HttpResponse.json({ detail: "Authentication credentials were not provided." }, { status: 403 }),
      ),
      http.get("*/api/team", () =>
        HttpResponse.json({ detail: "You do not have permission to perform this action." }, { status: 403 }),
      ),
    );
    const signedOut = await caught(apiFetch("/api/me"));
    expect(assign).toHaveBeenCalledWith("/sign-in?next=%2Fagents%2F3");
    expect(isSignedOut(signedOut)).toBe(true);
    expect(signedOut.status).toBe(401);

    assign.mockClear();
    const denied = await caught(apiFetch("/api/team"));
    expect(denied).toBeInstanceOf(ApiError);
    expect(denied.status).toBe(403);
    expect(isSignedOut(denied)).toBe(false);
    expect(assign).not.toHaveBeenCalled();
  });

  it("turns field errors into detail", async () => {
    server.use(http.get("*/api/x", () => HttpResponse.json({ name: ["A name is required."] }, { status: 400 })));
    const e = await caught(apiFetch("/api/x"));
    expect(e.detail).toBe("A name is required.");
    expect(e.fields.name).toEqual(["A name is required."]);
  });

  it("keeps publish errors as a list", async () => {
    server.use(
      http.get("*/api/y", () => HttpResponse.json({ errors: ['End step "X" needs an outcome.'] }, { status: 400 })),
    );
    const e = await caught(apiFetch("/api/y"));
    expect(e.fields.errors[0]).toBe('End step "X" needs an outcome.');
  });

  it("finds the first string in nested field errors", async () => {
    server.use(
      http.patch("*/api/agents/3", () =>
        HttpResponse.json(
          { settings: { dead_air: { non_field_errors: ["Dead-air timings must increase: first check-in, then second check-in, then hang up."] } } },
          { status: 400 },
        ),
      ),
      http.patch("*/api/agents/4", () => HttpResponse.json({ script: [{}, { body: ["Too long."] }] }, { status: 400 })),
    );
    document.cookie = "csrftoken=abc; path=/";
    const e = await caught(apiFetch("/api/agents/3", { method: "PATCH", json: {} }));
    expect(e.detail).toBe("Dead-air timings must increase: first check-in, then second check-in, then hang up.");
    expect(e.fields.settings).toEqual(["Dead-air timings must increase: first check-in, then second check-in, then hang up."]);
    const s = await caught(apiFetch("/api/agents/4", { method: "PATCH", json: {} }));
    expect(s.detail).toBe("Too long.");
    expect(s.fields.script).toEqual(["Too long."]);
  });

  it("can leave a signed-out 403 to the caller instead of redirecting", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/agents/3", search: "", origin: "http://localhost:3000", href: "http://localhost:3000/agents/3", assign });
    server.use(
      http.get("*/api/me", () => HttpResponse.json({ detail: "Authentication credentials were not provided." }, { status: 403 })),
    );
    const e = await caught(apiFetch("/api/me", { signInRedirect: false }));
    expect(isSignedOut(e)).toBe(true);
    expect(assign).not.toHaveBeenCalled();
  });

  it("falls back to a plain message when the body is not JSON", async () => {
    server.use(http.get("*/api/z", () => new HttpResponse("<html>boom</html>", { status: 502 })));
    const e = await caught(apiFetch("/api/z"));
    expect(e.detail).toBe("Something went wrong. Try again.");
    expect(e.status).toBe(502);
  });
});
