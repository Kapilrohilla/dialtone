import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";
import { middleware } from "./middleware";

function req(url: string, headers: Record<string, string> = {}) {
  return new NextRequest(url, { headers });
}

describe("middleware sign-in redirect", () => {
  it("redirects to the host the browser used, not the internal one", () => {
    const res = middleware(req("http://localhost:3000/agents?x=1", { host: "34.93.218.151", "x-forwarded-proto": "https" }));
    expect(res.status).toBe(307);
    const location = res.headers.get("location")!;
    expect(location).not.toContain("localhost");
    expect(location).toBe("https://34.93.218.151/sign-in?next=%2Fagents%3Fx%3D1");
  });

  it("prefers x-forwarded-host over host", () => {
    const res = middleware(
      req("http://localhost:3000/", { host: "localhost:3000", "x-forwarded-host": "console.example.com, proxy", "x-forwarded-proto": "https" }),
    );
    expect(res.headers.get("location")).toBe("https://console.example.com/sign-in?next=%2F");
  });

  it("falls back to the request URL when no proxy headers are present", () => {
    const res = middleware(req("http://localhost:3000/"));
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("http://localhost:3000/sign-in?next=%2F");
  });

  it("lets signed-in and open paths through", () => {
    expect(middleware(req("http://localhost:3000/sign-in")).headers.get("location")).toBeNull();
    expect(middleware(req("http://localhost:3000/", { cookie: "sessionid=abc" })).headers.get("location")).toBeNull();
  });
});
