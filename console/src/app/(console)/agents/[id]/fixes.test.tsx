import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { Agent, AuditFix, AuditFixRun, Me } from "@/lib/types";
import { agent as baseAgent, agentVersions, auditFixRun, me } from "@/test/fixtures";
import { setParams } from "@/test/navigation";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import AgentEditorPage from "./page";

const batch = (over: Partial<AuditFixRun> = {}) => auditFixRun({ scope: "batch", call: null, calls: 20, ...over });

function serve({ run = null as AuditFixRun | null, role = "owner" as Me["role"] } = {}) {
  let agent: Agent = baseAgent;
  let current = run;
  const posts: unknown[] = [];
  const accepts: string[] = [];
  server.use(
    http.get("*/api/me", () => HttpResponse.json({ ...me, role } satisfies Me)),
    http.get("*/api/agents/3", () => HttpResponse.json(agent)),
    http.get("*/api/agents/3/versions", () => HttpResponse.json(agentVersions)),
    http.get("*/api/agents/3/audit-fixes", () => (current ? HttpResponse.json(current) : new HttpResponse(null, { status: 204 }))),
    http.post("*/api/agents/3/audit-fixes", async ({ request }) => {
      posts.push(await request.json());
      current = batch();
      return HttpResponse.json(current, { status: 202 });
    }),
    http.post("*/api/audit-fixes/:run/:target/:item/accept", ({ params }) => {
      accepts.push(`${params.target}/${params.item}`);
      const fixed = current!.items.find((i) => i.id === Number(params.item))!;
      if (fixed.kind === "script") {
        agent = { ...agent, script: agent.script.map((s) => (s.id === fixed.payload.section_id ? { ...s, body: fixed.payload.after } : s)) };
      }
      current = { ...current!, items: current!.items.map((i) => (i.id === fixed.id ? ({ ...i, status: "accepted" } as AuditFix) : i)) };
      return HttpResponse.json(current);
    }),
  );
  return { posts, accepts };
}

function open() {
  setParams({ id: "3" });
  const user = userEvent.setup();
  renderWithProviders(<AgentEditorPage />, { route: "/agents/3" });
  return user;
}

const side = () => screen.getByRole("complementary", { name: "Agent settings" });

describe("agent audit fixes", () => {
  it("suggests fixes from recent calls with the chosen limit and source", async () => {
    const { posts } = serve();
    const user = open();
    await screen.findByRole("textbox", { name: "Greeting" });
    await user.selectOptions(within(side()).getByLabelText("Calls to look at"), "Last 50 calls");
    await user.selectOptions(within(side()).getByLabelText("Calls from"), "This workflow revision");
    await user.click(within(side()).getByRole("button", { name: "Suggest fixes" }));
    expect(await within(side()).findByRole("list", { name: "Suggested fixes" })).toBeInTheDocument();
    expect(posts).toEqual([{ limit: 50, by: "workflow_revision" }]);
    expect(within(side()).getByText("From 20 audited calls on v4.")).toBeInTheDocument();
    // Moments from other calls link to them.
    expect(within(side()).getByRole("link", { name: "call-1c0d" })).toHaveAttribute("href", "/calls?room=call-1c0d");
  });

  it("accepting a script fix reloads the editor with the new text", async () => {
    const { accepts } = serve({ run: batch() });
    const user = open();
    const greeting = await screen.findByRole("textbox", { name: "Greeting" });
    expect(greeting).toHaveTextContent("Northwind Car Rentals से Maya");
    const item = await within(side()).findByRole("article", { name: "Shorter greeting" });
    await user.click(within(item).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Greeting" })).toHaveTextContent("Maya बोल रही हूँ, Northwind से।"));
    expect(accepts).toEqual(["agent/77"]);
    expect(await within(side()).findByText("Accepted — in draft")).toBeInTheDocument();
  });

  it("lists versions with their fixes and the score change", async () => {
    serve();
    open();
    const versions = await within(await screen.findByRole("complementary", { name: "Agent settings" })).findByRole("list", { name: "Versions" });
    const v5 = within(versions).getByRole("article", { name: "Version 5" });
    expect(within(v5).getByRole("list", { name: "Audit fixes in v5" })).toHaveTextContent("Shorter greeting");
    expect(within(v5).getByText("Average score 78.5 from 12 audited calls")).toBeInTheDocument();
    expect(within(v5).getByText("+6.2 vs v4")).toBeInTheDocument();
    const areas = within(v5).getByRole("list", { name: "Score change by area in v5" });
    expect(within(areas).getByText("Sounds human").nextSibling).toHaveTextContent("+0.5");
    expect(within(areas).getByText("Listening").nextSibling).toHaveTextContent("−0.1");
    const v4 = within(versions).getByRole("article", { name: "Version 4" });
    expect(within(v4).getByText("Not enough calls yet (need 10 per version).")).toBeInTheDocument();
  });

  it("viewers see fixes and versions but can't start or accept", async () => {
    serve({ run: batch(), role: "viewer" });
    open();
    await within(await screen.findByRole("complementary", { name: "Agent settings" })).findByRole("list", { name: "Suggested fixes" });
    expect(within(side()).queryByRole("button", { name: "Suggest fixes" })).toBeNull();
    expect(within(side()).queryByRole("button", { name: "Accept" })).toBeNull();
  });
});
