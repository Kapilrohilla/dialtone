import userEvent from "@testing-library/user-event";
import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { AgentListItem, Workflow, WorkflowListItem } from "@/lib/types";
import { agentListItem, me, workflow } from "@/test/fixtures";
import { renderWithProviders, router } from "@/test/render";
import { server } from "@/test/server";
import WorkflowsPage from "./page";

const second: WorkflowListItem = { id: 5, name: "Call back follow-up", updated_at: "2026-11-01T09:00:00Z", current_revision: 1, dead_air_enabled: true };
const agents: AgentListItem[] = [
  { ...agentListItem, id: 3, name: "Driver lead qualifier", workflow: 2 },
  { ...agentListItem, id: 4, name: "Weekend shift", workflow: 2, status: "draft" },
  { ...agentListItem, id: 6, name: "Old pilot", workflow: 5, status: "archived" },
];

describe("workflows list", () => {
  it("lists workflows with who uses them", async () => {
    server.use(
      http.get("*/api/workflows", () => HttpResponse.json([workflow, second])),
      http.get("*/api/agents", () => HttpResponse.json(agents)),
    );
    renderWithProviders(<WorkflowsPage />, { route: "/workflows" });
    const table = await screen.findByRole("table", { name: "Workflows" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("link", { name: "Driver onboarding" })).toHaveAttribute("href", "/workflows/2");
    expect(await within(rows[0]).findByText("Driver lead qualifier, Weekend shift")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Not used")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Last edited" })).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(within(rows[1]).getByRole("button", { name: "More actions for Call back follow-up" }));
    await user.click(screen.getByRole("menuitem", { name: "Open" }));
    expect(router.push).toHaveBeenCalledWith("/workflows/5");
  });

  it("new workflow opens the builder", async () => {
    const calls: { method: string; body: unknown }[] = [];
    const created: Workflow = { ...workflow, id: 9, name: "Untitled workflow", current_revision: 0, graph: { steps: [], paths: [] } };
    server.use(
      http.post("*/api/workflows", async ({ request }) => {
        calls.push({ method: "POST", body: await request.json() });
        return HttpResponse.json(created, { status: 201 });
      }),
      http.patch("*/api/workflows/9", async ({ request }) => {
        const body = (await request.json()) as { graph: Workflow["graph"] };
        calls.push({ method: "PATCH", body });
        return HttpResponse.json({ ...created, current_revision: 1, graph: body.graph });
      }),
    );
    renderWithProviders(<WorkflowsPage />, { route: "/workflows" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "New workflow" }));
    await vi.waitFor(() => expect(router.push).toHaveBeenCalledWith("/workflows/9"));
    expect(calls).toEqual([
      { method: "POST", body: { name: "Untitled workflow" } },
      {
        method: "PATCH",
        body: { graph: { steps: [{ id: "start", type: "start", name: "Greeting", prompt: "", position: { x: 0, y: 0 } }], paths: [] } },
      },
    ]);
  });

  it("still opens a new workflow when its start step can't be saved", async () => {
    let lists = 0;
    const created: Workflow = { ...workflow, id: 9, name: "Untitled workflow", current_revision: 0, graph: { steps: [], paths: [] } };
    server.use(
      http.get("*/api/workflows", () => {
        lists += 1;
        return HttpResponse.json(lists > 1 ? [workflow, created] : [workflow]);
      }),
      http.post("*/api/workflows", () => HttpResponse.json(created, { status: 201 })),
      http.patch("*/api/workflows/9", () => HttpResponse.json({ detail: "Server error." }, { status: 500 })),
    );
    renderWithProviders(<WorkflowsPage />, { route: "/workflows" });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "New workflow" }));
    await vi.waitFor(() => expect(router.push).toHaveBeenCalledWith("/workflows/9"));
    expect(screen.getByText(/the start step could not be added/)).toBeInTheDocument();
    await vi.waitFor(() => expect(lists).toBe(2));
  });

  it("shows the empty state, and no New workflow for viewers", async () => {
    server.use(
      http.get("*/api/workflows", () => HttpResponse.json([])),
      http.get("*/api/me", () => HttpResponse.json({ ...me, role: "viewer" })),
    );
    const { queryClient } = renderWithProviders(<WorkflowsPage />, { route: "/workflows" });
    expect(await screen.findByText("No workflows yet. A workflow splits a call into steps, each with its own prompt.")).toBeInTheDocument();
    await vi.waitFor(() => expect(queryClient.getQueryData<{ role: string }>(["me"])?.role).toBe("viewer"));
    expect(screen.queryByRole("button", { name: "New workflow" })).not.toBeInTheDocument();
  });

  it("shows an error with Try again", async () => {
    server.use(http.get("*/api/workflows", () => HttpResponse.json({ detail: "Database is down." }, { status: 500 })));
    renderWithProviders(<WorkflowsPage />, { route: "/workflows" });
    expect(await screen.findByText("Database is down.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
