import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { useExpressions, useVoices } from "@/lib/queries";
import { agent, agentListItem, me } from "@/test/fixtures";
import { renderWithProviders, router } from "@/test/render";
import { server } from "@/test/server";
import type { AgentListItem } from "@/lib/types";
import AgentsPage from "./page";

const live: AgentListItem = agentListItem;
const draft: AgentListItem = { ...agentListItem, id: 8, name: "Callback follow-up", description: "Rings people who asked for a callback.", status: "draft", calls_this_week: 0 };
const archived: AgentListItem = { ...agentListItem, id: 9, name: "Old pilot", status: "archived", calls_this_week: 3 };

const serve = (rows: AgentListItem[]) => server.use(http.get("*/api/agents", () => HttpResponse.json(rows)));
const rowOf = (name: string) => screen.getByRole("link", { name }).closest("tr") as HTMLElement;

describe("agents list", () => {
  it("publish dialog names the live agent it replaces", async () => {
    serve([live, draft]);
    const user = userEvent.setup();
    renderWithProviders(<AgentsPage />);
    await user.click(within(await screen.findByRole("table")).getByRole("button", { name: "Publish" }));
    const dialog = await screen.findByRole("dialog", { name: "Publish Callback follow-up?" });
    expect(within(dialog).getByText("Driver lead qualifier will stop answering calls.")).toBeInTheDocument();
  });

  it("says the agent will answer the next call when nothing is live", async () => {
    serve([draft]);
    const user = userEvent.setup();
    renderWithProviders(<AgentsPage />);
    await user.click(await screen.findByRole("button", { name: "Publish" }));
    expect(await screen.findByText("It will answer the next call.")).toBeInTheDocument();
  });

  it("publish errors are listed in the dialog", async () => {
    serve([draft]);
    server.use(http.post("*/api/agents/8/publish", () => HttpResponse.json({ errors: ["Add a greeting.", "Pick a voice."] }, { status: 400 })));
    const user = userEvent.setup();
    renderWithProviders(<AgentsPage />);
    await user.click(await screen.findByRole("button", { name: "Publish" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));
    expect(await within(dialog).findByText("Fix these first:")).toBeInTheDocument();
    expect(within(dialog).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Add a greeting.", "Pick a voice."]);
  });

  it("new agent creates and opens the editor", async () => {
    serve([]);
    let body: unknown;
    server.use(
      http.post("*/api/agents", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ...agent, id: 11, status: "draft" }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<AgentsPage />);
    await user.click(await screen.findByRole("button", { name: "New agent" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/agents/11"));
    expect(body).toEqual({ name: "Untitled agent" });
  });

  it("tabs filter by status and All hides archived", async () => {
    serve([live, draft, archived]);
    const user = userEvent.setup();
    renderWithProviders(<AgentsPage />);
    await screen.findByRole("table");
    expect(screen.queryByRole("link", { name: "Old pilot" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Callback follow-up" })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Drafts" }));
    expect(screen.queryByRole("link", { name: "Driver lead qualifier" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Live" }));
    expect(screen.getByRole("link", { name: "Driver lead qualifier" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Callback follow-up" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Archived" }));
    expect(screen.getByRole("link", { name: "Old pilot" })).toBeInTheDocument();
  });

  it("shows an empty state for a tab with nothing in it", async () => {
    serve([live]);
    const user = userEvent.setup();
    renderWithProviders(<AgentsPage />);
    await screen.findByRole("table");
    await user.click(screen.getByRole("tab", { name: "Drafts" }));
    expect(screen.getByText("No drafts.")).toBeInTheDocument();
  });

  it("shows the outdated chip and Republish", async () => {
    serve([{ ...live, is_outdated: true }]);
    const user = userEvent.setup();
    renderWithProviders(<AgentsPage />);
    const row = within(await screen.findByRole("table"));
    expect(row.getByText("Older version")).toBeInTheDocument();
    await user.click(row.getByRole("button", { name: "Republish" }));
    expect(await screen.findByRole("dialog", { name: "Publish Driver lead qualifier?" })).toBeInTheDocument();
  });

  it("shows the live panel with calls today and unpublishes after confirming", async () => {
    serve([live]);
    let posted = false;
    server.use(http.post("*/api/agents/3/unpublish", () => ((posted = true), HttpResponse.json({ ...agent, status: "draft" }))));
    const user = userEvent.setup();
    renderWithProviders(<AgentsPage />);
    const panel = within(await screen.findByLabelText("Answering calls now"));
    expect(await panel.findByText("18")).toBeInTheDocument();
    expect(panel.getByText("+91 80 4718 2290")).toBeInTheDocument();
    expect(panel.getByRole("link", { name: "Open" })).toHaveAttribute("href", "/agents/3");
    await user.click(panel.getByRole("button", { name: "Unpublish" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Stop Driver lead qualifier answering calls? Callers will hear the built-in script until you publish an agent.")).toBeInTheDocument();
    expect(posted).toBe(false);
    await user.click(within(dialog).getByRole("button", { name: "Unpublish" }));
    await waitFor(() => expect(posted).toBe(true));
  });

  it("archive and restore from the menu", async () => {
    serve([draft, archived]);
    const calls: string[] = [];
    server.use(
      http.post("*/api/agents/:id/:action", ({ params }) => (calls.push(`${params.action}:${params.id}`), HttpResponse.json(agent))),
    );
    const user = userEvent.setup();
    renderWithProviders(<AgentsPage />);
    await screen.findByRole("table");
    await user.click(within(rowOf("Callback follow-up")).getByRole("button", { name: /More actions/ }));
    await user.click(screen.getByRole("menuitem", { name: "Archive" }));
    await waitFor(() => expect(calls).toEqual(["archive:8"]));
    await user.click(screen.getByRole("tab", { name: "Archived" }));
    await user.click(within(rowOf("Old pilot")).getByRole("button", { name: /More actions/ }));
    await user.click(screen.getByRole("menuitem", { name: "Restore" }));
    await waitFor(() => expect(calls).toEqual(["archive:8", "restore:9"]));
  });

  it("shows the server's reason when a state action is refused", async () => {
    serve([draft]);
    server.use(http.post("*/api/agents/8/archive", () => HttpResponse.json({ detail: "Unpublish it first." }, { status: 400 })));
    const user = userEvent.setup();
    renderWithProviders(<AgentsPage />);
    await screen.findByRole("table");
    await user.click(within(rowOf("Callback follow-up")).getByRole("button", { name: /More actions/ }));
    await user.click(screen.getByRole("menuitem", { name: "Archive" }));
    expect(await screen.findByText("Unpublish it first.")).toBeInTheDocument();
  });

  it("viewer sees no publish or menu actions", async () => {
    serve([live, draft]);
    server.use(http.get("*/api/me", () => HttpResponse.json({ ...me, role: "viewer" })));
    const { queryClient } = renderWithProviders(<AgentsPage />);
    await screen.findByRole("table");
    await waitFor(() => expect(queryClient.getQueryState(["me"])?.status).toBe("success"));
    expect(screen.queryByRole("button", { name: "Publish" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /More actions/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New agent" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Unpublish" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open" })).toBeInTheDocument();
  });

  it("shows built-in script note when nothing is live", async () => {
    serve([draft]);
    renderWithProviders(<AgentsPage />);
    expect(await screen.findByText("No agent is answering calls. Callers hear the built-in script.")).toBeInTheDocument();
  });

  it("shows an error state with retry", async () => {
    server.use(http.get("*/api/agents", () => HttpResponse.json({ detail: "Server is down." }, { status: 500 })));
    renderWithProviders(<AgentsPage />);
    expect(await screen.findByText("Server is down.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

function Probe() {
  const voices = useVoices();
  const expressions = useExpressions();
  return (
    <p>
      {voices.data ? `${voices.data.pipeline}:${voices.data.voices.length}` : "…"} {expressions.data ? expressions.data.map((e) => e.name).join(",") : "…"}
    </p>
  );
}

describe("voice and expression queries", () => {
  it("load from /api/voices and /api/expressions", async () => {
    server.use(http.get("*/api/expressions", () => HttpResponse.json([{ name: "happy", hint: "Warm", builtin: true }])));
    renderWithProviders(<Probe />);
    expect(await screen.findByText(/gemini-live:\d+ happy/)).toBeInTheDocument();
  });
});
