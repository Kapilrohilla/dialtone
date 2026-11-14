import userEvent from "@testing-library/user-event";
import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { AuditFix, AuditFixRun, CallAudit, Me, Role } from "@/lib/types";
import { auditFixRun, me } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import CallsPage from "./page";

const OPEN = "/calls?from=2026-10-30&to=2026-11-05&room=call-7f3a";

const audit: CallAudit = {
  id: 1,
  status: "ready",
  enabled: true,
  error: "",
  skipped_reason: "",
  skipped_label: "",
  overall_score: 64,
  summary: "Asked the city twice.",
  areas: [],
  moments: [
    {
      line: 0, at: "2026-11-05T09:02:03Z", at_s: 3, step_id: "city", step_name: "Ask city", speaker: "agent",
      quote: "आप किस शहर से हैं?", kind: "problem", note: "Asked again", area: "listening",
    },
  ],
  rubric_version: "2026-11-v1",
  model: "gemini-test",
  used_audio: false,
  quotes_purged: false,
  automatic: true,
  created_at: "2026-11-05T09:05:00Z",
  finished_at: "2026-11-05T09:05:20Z",
};

type Calls = { posts: number; patches: { url: string; body: unknown }[]; accepts: string[] };

/** The call's audit and its fixes. `start` answers the POST (default: a running run, then ready on the next GET). */
function serve({ role = "editor", run = null, start }: { role?: Role; run?: AuditFixRun | null; start?: () => Response } = {}) {
  let current = run;
  const calls: Calls = { posts: 0, patches: [], accepts: [] };
  const update = (id: number, change: Partial<AuditFix>) => {
    current = current && { ...current, items: current.items.map((i) => (i.id === id ? ({ ...i, ...change } as AuditFix) : i)) };
  };
  server.use(
    http.get("*/api/me", () => HttpResponse.json({ ...me, role } satisfies Me)),
    http.get("*/api/calls/:room/audit", () => HttpResponse.json(audit)),
    http.get("*/api/calls/:room/audit/fixes", () => (current ? HttpResponse.json(current) : new HttpResponse(null, { status: 204 }))),
    http.post("*/api/calls/:room/audit/fixes", () => {
      calls.posts += 1;
      if (start) return start();
      const running = auditFixRun({ status: "running", items: [] });
      current = auditFixRun();
      return HttpResponse.json(running, { status: 202 });
    }),
    http.patch("*/api/audit-fixes/:run/:target/:item", async ({ request, params }) => {
      const body = (await request.json()) as { edited_payload?: unknown; status?: AuditFix["status"] };
      calls.patches.push({ url: `${params.run}/${params.target}/${params.item}`, body });
      if (body.edited_payload) return HttpResponse.json({ label: ["A path with this name already exists. Rename it to accept."] }, { status: 400 });
      if (body.status) update(Number(params.item), { status: body.status });
      return HttpResponse.json(current);
    }),
    http.post("*/api/audit-fixes/:run/:target/:item/accept", ({ params }) => {
      calls.accepts.push(`${params.run}/${params.target}/${params.item}`);
      update(Number(params.item), { status: "accepted", applied_revision: 4 });
      return HttpResponse.json(current);
    }),
  );
  return calls;
}

async function openCall() {
  renderWithProviders(<CallsPage />, { route: OPEN });
  const panel = await screen.findByRole("dialog");
  await within(panel).findByText("Asked the city twice.");
  return panel;
}

const fixes = (panel: HTMLElement) => within(panel).getByRole("list", { name: "Suggested fixes" });
const fix = (panel: HTMLElement, title: string) => within(fixes(panel)).getByRole("article", { name: title });

describe("call audit fixes", () => {
  it("suggests fixes from a call and shows them ranked, with their moments", async () => {
    const calls = serve();
    const panel = await openCall();
    await userEvent.setup().click(within(panel).getByRole("button", { name: "Suggest fixes" }));
    expect(await within(panel).findByText(/Finding fixes/)).toBeInTheDocument();
    expect(calls.posts).toBe(1);

    const list = await within(panel).findByRole("list", { name: "Suggested fixes" }, { timeout: 4000 });
    const titles = within(list).getAllByRole("article").map((a) => a.getAttribute("aria-label"));
    expect(titles).toEqual(["Handle callers who already said their city", "Shorter greeting"]);
    expect(within(panel).getByText("Accepting changes the draft. Publish the agent for callers to hear it.")).toBeInTheDocument();

    const first = fix(panel, "Handle callers who already said their city");
    expect(within(first).getByText("Workflow · New path")).toBeInTheDocument();
    expect(within(first).getByText(/Step: Ask city · In 3 of 5 calls · ≈6 points/)).toBeInTheDocument();
    expect(within(first).getByText(/Already said the city/)).toBeInTheDocument();
    expect(await within(first).findByText("End: interested")).toBeInTheDocument();
    const moments = within(first).getByRole("list", { name: /Moments for/ });
    expect(within(moments).getByText("आप किस शहर से हैं?")).toBeInTheDocument();
    expect(within(moments).getByText("Caller repeated Pune")).toBeInTheDocument();
    expect(within(moments).getByText("01:04")).toBeInTheDocument();

    const second = fix(panel, "Shorter greeting");
    expect(within(second).getByText("Agent · Script")).toBeInTheDocument();
    expect(within(second).getByText("नमस्ते! Maya बोल रही हूँ, Northwind से।")).toBeInTheDocument();
  });

  it("accepts a fix into the draft", async () => {
    const calls = serve({ run: auditFixRun() });
    const panel = await openCall();
    await within(panel).findByRole("list", { name: "Suggested fixes" });
    const item = fix(panel, "Handle callers who already said their city");
    await userEvent.setup().click(within(item).getByRole("button", { name: "Accept" }));
    expect(await within(item).findByText("Accepted — in draft · workflow revision 4")).toBeInTheDocument();
    expect(calls.accepts).toEqual(["41/workflow/501"]);
    expect(within(item).queryByRole("button", { name: "Accept" })).toBeNull();
    expect(within(panel).getByRole("button", { name: "Suggest again" })).toBeInTheDocument();
  });

  it("dismisses and restores a fix", async () => {
    const calls = serve({ run: auditFixRun() });
    const user = userEvent.setup();
    const panel = await openCall();
    await within(panel).findByRole("list", { name: "Suggested fixes" });
    await user.click(within(fix(panel, "Shorter greeting")).getByRole("button", { name: "Dismiss" }));
    const restore = await within(fix(panel, "Shorter greeting")).findByRole("button", { name: "Restore" });
    expect(calls.patches).toEqual([{ url: "41/agent/77", body: { status: "dismissed" } }]);
    await user.click(restore);
    expect(await within(fix(panel, "Shorter greeting")).findByRole("button", { name: "Accept" })).toBeInTheDocument();
  });

  it("shows the server's field error when an edit is refused", async () => {
    const calls = serve({ run: auditFixRun() });
    const user = userEvent.setup();
    const panel = await openCall();
    await within(panel).findByRole("list", { name: "Suggested fixes" });
    const item = fix(panel, "Handle callers who already said their city");
    await user.click(within(item).getByRole("button", { name: "Edit" }));
    const form = within(item).getByRole("form", { name: /Edit/ });
    const name = within(form).getByLabelText("Path name");
    await user.clear(name);
    await user.type(name, "Next");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(await within(form).findByText("A path with this name already exists. Rename it to accept.")).toBeInTheDocument();
    expect(calls.patches[0].body).toMatchObject({ edited_payload: { label: "Next", examples: ["बताया तो था", "I told you"] } });
  });

  it("can't accept a fix that no longer fits the draft", async () => {
    const run = auditFixRun();
    run.items[1] = { ...run.items[1], invalid_reason: "This script section has changed since." };
    serve({ run });
    const panel = await openCall();
    await within(panel).findByRole("list", { name: "Suggested fixes" });
    const item = fix(panel, "Shorter greeting");
    expect(within(item).getByText("This script section has changed since.")).toBeInTheDocument();
    expect(within(item).getByRole("button", { name: "Accept" })).toBeDisabled();
  });

  it("says why fixes can't be suggested", async () => {
    serve({ start: () => HttpResponse.json({ detail: "Daily limit reached" }, { status: 429 }) });
    const panel = await openCall();
    await userEvent.setup().click(within(panel).getByRole("button", { name: "Suggest fixes" }));
    expect(await within(panel).findByRole("alert")).toHaveTextContent("Daily limit reached");
  });

  it("viewers see the fixes but can't act on them", async () => {
    serve({ role: "viewer", run: auditFixRun({ dropped: 2 }) });
    const panel = await openCall();
    await within(panel).findByRole("list", { name: "Suggested fixes" });
    expect(within(panel).getByText("2 suggestions failed checks and were left out.")).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Suggest again" })).toBeNull();
    expect(within(panel).queryByRole("button", { name: "Accept" })).toBeNull();
    expect(within(panel).queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("says when there was nothing to fix", async () => {
    serve({ run: auditFixRun({ status: "empty", items: [] }) });
    const panel = await openCall();
    expect(await within(panel).findByText("No fixes this time")).toBeInTheDocument();
  });
});
