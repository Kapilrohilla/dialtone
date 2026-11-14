import userEvent from "@testing-library/user-event";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { WorkflowUpdate } from "@/lib/queries";
import type { AgentListItem, Graph, Workflow } from "@/lib/types";
import { agentListItem, me, onboardingGraph, workflow as baseWorkflow } from "@/test/fixtures";
import { setParams } from "@/test/navigation";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import WorkflowBuilderPage from "./page";

const STEP_NAMES = [
  "Greeting",
  "Ask city",
  "Ask licence and experience",
  "Explain the plan",
  "End: interested",
  "Schedule a call back",
  "Transfer to a telecaller",
  "End: not in your city",
  "End: not eligible",
];

/** Serves the onboarding workflow; records each request in order and answers a PATCH with the saved graph. */
function serve(opts: { graph?: Graph; errors?: string[]; patchErrors?: (body: WorkflowUpdate) => string[]; patch?: () => Response } = {}) {
  let current: Workflow = { ...baseWorkflow, graph: opts.graph ?? onboardingGraph(), errors: opts.errors ?? [] };
  const log: string[] = [];
  const patches: WorkflowUpdate[] = [];
  server.use(
    http.get("*/api/workflows/2", () => HttpResponse.json(current)),
    http.patch("*/api/workflows/2", async ({ request }) => {
      const body = (await request.json()) as WorkflowUpdate;
      log.push("PATCH");
      patches.push(body);
      const failed = opts.patch?.();
      if (failed) return failed;
      current = {
        ...current,
        ...(body.name ? { name: body.name } : {}),
        ...(body.graph ? { graph: body.graph, current_revision: current.current_revision + 1 } : {}),
        ...(body.dead_air_enabled !== undefined ? { dead_air_enabled: body.dead_air_enabled } : {}),
        errors: opts.patchErrors?.(body) ?? [],
      };
      return HttpResponse.json(current);
    }),
    http.post("*/api/workflows/2/simulate", () => {
      log.push("SIMULATE");
      return HttpResponse.json({ reply: "नमस्ते", state: {}, step: { id: "greeting", name: "Greeting" }, outcome: null, ended: false });
    }),
  );
  return { log, patches };
}

function open(role: "owner" | "viewer" = "owner") {
  if (role !== "owner") server.use(http.get("*/api/me", () => HttpResponse.json({ ...me, role })));
  setParams({ id: "2" });
  const user = userEvent.setup();
  const view = renderWithProviders(<WorkflowBuilderPage />, { route: "/workflows/2" });
  return { user, ...view };
}

const canvas = () => document.querySelector<HTMLElement>(".react-flow")!;
const card = (name: string) => within(canvas()).getByText(name).closest<HTMLElement>(".react-flow__node")!;
const panel = () => screen.getByRole("complementary", { name: "Step" });

/** Clicks a card the way React Flow selects it. (user-event's mousedown has no `view`, which d3-drag needs;
 *  dragging is covered by graph.test.ts.) Focus moves to the card, as a real click would. */
function pick(name: string) {
  const el = card(name);
  fireEvent.click(el);
  el.focus();
}

async function select(name: string) {
  pick(name);
  await waitFor(() => expect(within(panel()).getByRole("heading", { name })).toBeInTheDocument());
}

describe("workflow builder", () => {
  it("renders the seeded onboarding graph with every step visible", async () => {
    serve();
    open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    for (const name of STEP_NAMES) expect(within(canvas()).getByText(name)).toBeInTheDocument();
    expect(canvas().querySelectorAll(".react-flow__node")).toHaveLength(9);
    expect(within(card("Explain the plan")).getByText("[excited]{{lead.city}} में हमारे plan के बारे में बताऊँ?[pause 1s]")).toBeInTheDocument();
    expect(within(card("End: interested")).getByText("End: Interested")).toBeInTheDocument();
    expect(within(card("Greeting")).getByText("Start")).toBeInTheDocument();
    expect(within(panel()).getByText("Select a step to edit it.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add step" })).toBeInTheDocument();
  });

  it("edits a step's prompt and saves the whole graph", async () => {
    const { patches } = serve();
    const { user } = open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    await select("Ask city");
    const says = await within(panel()).findByRole("textbox", { name: "What the agent says" });
    await user.click(says);
    await user.click(within(panel()).getByRole("button", { name: "Expression" }));
    await user.click(screen.getByRole("menuitem", { name: /^excited/ }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(Object.keys(patches[0])).toEqual(["graph"]);
    const steps = patches[0].graph!.steps;
    expect(steps).toHaveLength(9);
    expect(steps.find((s) => s.id === "ask_city")?.prompt).toContain("[[expr:excited]]");
    expect(steps.find((s) => s.id === "ask_city")?.prompt?.replace("[[expr:excited]]", "")).toBe("आप अभी किस शहर में रहते हैं?");
    expect(steps.find((s) => s.id === "greeting")).toEqual(onboardingGraph().steps[0]);
    expect(patches[0].graph!.paths).toHaveLength(8);
    expect(patches[0].graph!.paths.every((p) => p.id)).toBe(true);
    expect(await screen.findByText("Saved. Agents using this workflow need republishing before callers hear the change.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeDisabled());
  });

  it("adds a path from the side panel", async () => {
    server.use(http.get("*/api/agents", () => HttpResponse.json([{ ...agentListItem, workflow: null } satisfies AgentListItem])));
    const { patches } = serve();
    const { user } = open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    await select("Ask city");
    expect(within(panel()).getAllByRole("textbox", { name: /^Label of path/ })).toHaveLength(2);
    await user.click(within(panel()).getByRole("button", { name: "Add path" }));
    const label = within(panel()).getByRole("textbox", { name: "Label of path 3" });
    expect(label).toHaveValue("New path");
    await user.clear(label);
    await user.type(label, "Wrong time");
    await user.selectOptions(within(panel()).getByRole("combobox", { name: "Where path 3 goes" }), "Schedule a call back");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    const added = patches[0].graph!.paths.filter((p) => p.from === "ask_city");
    expect(added).toHaveLength(3);
    expect(added[2]).toMatchObject({ from: "ask_city", to: "schedule_callback", label: "Wrong time" });
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
  });

  it("removes a path from the side panel", async () => {
    const { patches } = serve();
    const { user } = open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    await select("Ask city");
    await user.click(within(panel()).getByRole("button", { name: "Remove path Other city" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0].graph!.paths.some((p) => p.label === "Other city")).toBe(false);
  });

  it("shows save errors and selects the step an error names", async () => {
    const { patches } = serve({ patchErrors: () => ['Step "Ask city" has two paths labelled "Pune or Delhi". Labels must be different.'] });
    const { user } = open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    expect(screen.queryByText("Fix these before an agent can use this workflow:")).not.toBeInTheDocument();
    await select("Ask city");
    const label = within(panel()).getByRole("textbox", { name: "Label of path 2" });
    await user.clear(label);
    await user.type(label, "Pune or Delhi");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    const problems = await screen.findByRole("region", { name: "Problems with this workflow" });
    expect(within(problems).getByText("Fix these before an agent can use this workflow:")).toBeInTheDocument();
    fireEvent.click(canvas().querySelector(".react-flow__pane")!);
    await waitFor(() => expect(within(panel()).getByText("Select a step to edit it.")).toBeInTheDocument());
    await user.click(within(problems).getByRole("button", { name: /Step "Ask city" has two paths/ }));
    expect(within(panel()).getByRole("heading", { name: "Ask city" })).toBeInTheDocument();
  });

  it("drops paths to missing steps from the canvas and shows the server error", async () => {
    const graph = onboardingGraph();
    graph.paths.push({ from: "ask_city", to: "gone", label: "Lost" });
    const error = 'The path "Lost" leaving "Ask city" points to a step that does not exist.';
    serve({ graph, errors: [error] });
    const { user } = open();
    const problems = await screen.findByRole("region", { name: "Problems with this workflow" });
    expect(within(problems).getByText(error)).toBeInTheDocument();
    expect(canvas().querySelectorAll(".react-flow__node")).toHaveLength(9);
    await user.click(within(problems).getByRole("button", { name: error }));
    expect(within(panel()).getByRole("heading", { name: "Ask city" })).toBeInTheDocument();
    expect(within(panel()).getByRole("combobox", { name: "Where path 3 goes" })).toHaveDisplayValue("A missing step");
  });

  it("end steps choose an outcome from the 14 codes", async () => {
    const { patches } = serve();
    const { user } = open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    await select("End: interested");
    const outcome = within(panel()).getByRole("combobox", { name: "Outcome" });
    expect(outcome).toHaveValue("INTERESTED");
    const codes = within(outcome).getAllByRole("option").filter((o) => (o as HTMLOptionElement).value);
    expect(codes).toHaveLength(14);
    expect(Array.from(outcome.querySelectorAll("optgroup")).map((g) => g.label)).toEqual(["Interested", "Call back", "Not interested", "Dropped", "Not reached"]);
    expect(within(panel()).queryByRole("button", { name: "Add path" })).not.toBeInTheDocument();
    await user.selectOptions(outcome, "Asked to talk later");
    expect(within(card("End: interested")).getByText("End: Call back")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0].graph!.steps.find((s) => s.id === "end_interested")?.outcome).toBe("CBR");
  });

  it("shows each step type's own field", async () => {
    serve();
    const { user } = open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    await select("Ask licence and experience");
    expect(within(panel()).getByRole("textbox", { name: "Save the answer as" })).toHaveValue("licence");
    expect(within(panel()).getByText("Lowercase letters, digits and underscores")).toBeInTheDocument();
    await select("Transfer to a telecaller");
    expect(within(panel()).getByText("Hands the caller to the telecalling team.")).toBeInTheDocument();
    await select("Ask city");
    const use = within(panel()).getByRole("combobox", { name: "Use knowledge" });
    expect(use).toHaveDisplayValue("None");
    await user.selectOptions(use, "Pricing and plans, Pune");
    expect(use).toHaveValue("7");
  });

  it("adds a step below the selected one and deletes a step after asking", async () => {
    const { patches } = serve();
    const { user } = open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    await select("Ask city");
    await user.click(screen.getByRole("button", { name: "Add step" }));
    await user.click(screen.getByRole("menuitem", { name: "Collect an answer" }));
    expect(within(panel()).getByRole("heading", { name: "Collect an answer" })).toBeInTheDocument();
    expect(canvas().querySelectorAll(".react-flow__node")).toHaveLength(10);

    pick("Ask licence and experience");
    await user.keyboard("{Delete}");
    const dialog = await screen.findByRole("dialog", { name: "Delete Ask licence and experience?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete step" }));
    expect(within(canvas()).queryByText("Ask licence and experience")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    const { steps, paths } = patches[0].graph!;
    expect(steps.map((s) => s.id)).not.toContain("ask_licence");
    expect(paths.some((p) => p.from === "ask_licence" || p.to === "ask_licence")).toBe(false);
    expect(steps.find((s) => s.name === "Collect an answer")).toMatchObject({ type: "collect", position: { x: 290, y: 400 } });
  });

  it("try it flushes unsaved changes first", async () => {
    const { log, patches } = serve();
    const { user } = open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    await select("Greeting");
    await user.type(within(panel()).getByRole("textbox", { name: "Step name" }), " and consent");
    await user.click(screen.getByRole("button", { name: "Test chat" }));
    expect(await screen.findByRole("dialog", { name: "Test chat" })).toBeInTheDocument();
    await waitFor(() => expect(log).toEqual(["PATCH", "SIMULATE"]));
    expect(patches[0].graph!.steps[0].name).toBe("Greeting and consent");
  });

  it("try it stops when the save fails", async () => {
    const { log } = serve({ patch: () => HttpResponse.json({ detail: "The graph is too large." }, { status: 400 }) });
    const { user } = open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    await select("Greeting");
    await user.type(within(panel()).getByRole("textbox", { name: "Step name" }), "!");
    await user.click(screen.getByRole("button", { name: "Test chat" }));
    expect(await screen.findByText("The graph is too large.")).toBeInTheDocument();
    expect(log).toEqual(["PATCH"]);
    expect(screen.queryByRole("dialog", { name: "Test chat" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("try it with nothing unsaved does not save", async () => {
    const { log } = serve();
    const { user } = open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    await user.click(screen.getByRole("button", { name: "Test chat" }));
    await waitFor(() => expect(log).toEqual(["SIMULATE"]));
  });

  it("renames the workflow from the breadcrumb", async () => {
    const { patches } = serve();
    const { user } = open();
    await user.click(await screen.findByRole("button", { name: "Rename Driver onboarding" }));
    const input = screen.getByRole("textbox", { name: "Workflow name" });
    await user.clear(input);
    await user.type(input, "Onboarding v2{Enter}");
    await waitFor(() => expect(patches).toEqual([{ name: "Onboarding v2" }]));
    expect(await screen.findByRole("button", { name: "Rename Onboarding v2" })).toBeInTheDocument();
  });

  it("asks before leaving with unsaved changes", async () => {
    serve();
    const { user } = open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    const unload = () => {
      const e = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(e);
      return e.defaultPrevented;
    };
    expect(unload()).toBe(false);
    await select("Greeting");
    await user.type(within(panel()).getByRole("textbox", { name: "Step name" }), "!");
    expect(unload()).toBe(true);
    await user.click(screen.getByRole("link", { name: "Workflows" }));
    expect(await screen.findByRole("dialog", { name: "Discard unsaved changes to Driver onboarding?" })).toBeInTheDocument();
  });

  it("is read-only for viewers", async () => {
    serve();
    const { user, queryClient } = open("viewer");
    await screen.findByRole("heading", { level: 1, name: "Driver onboarding" });
    expect(queryClient.getQueryData<{ role: string }>(["me"])?.role).toBe("viewer");
    for (const name of STEP_NAMES) expect(within(canvas()).getByText(name)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Test chat" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add step" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Rename/ })).not.toBeInTheDocument();
    expect(card("Greeting")).not.toHaveClass("draggable");
    expect(canvas().querySelector(".react-flow__handle.connectable")).toBeNull();

    await select("Ask city");
    expect(card("Ask city")).toHaveFocus();
    expect(within(panel()).getByRole("textbox", { name: "Step name" })).toHaveAttribute("readonly");
    expect(within(panel()).getByRole("textbox", { name: "What the agent says" })).toHaveAttribute("contenteditable", "false");
    expect(within(panel()).getByRole("combobox", { name: "Use knowledge" })).toBeDisabled();
    expect(within(panel()).queryByRole("button", { name: "Add path" })).not.toBeInTheDocument();
    expect(within(panel()).queryByRole("button", { name: /^Remove path/ })).not.toBeInTheDocument();
    expect(within(panel()).queryByRole("button", { name: "Advanced" })).not.toBeInTheDocument();
    expect(within(panel()).getByText("Pune or Delhi")).toBeInTheDocument();
    await user.keyboard("{Delete}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("every card has handles for its saved paths, and new paths can't enter a start or leave an end", async () => {
    const graph = onboardingGraph();
    graph.paths.push({ from: "end_city", to: "greeting", label: "Start over" });
    serve({ graph });
    open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    const handle = (name: string, id: string) => card(name).querySelector(`.react-flow__handle[data-handleid="${id}"]`);
    for (const id of ["top", "left", "bottom", "right"]) {
      expect(handle("Greeting", id)).not.toBeNull();
      expect(handle("End: not in your city", id)).not.toBeNull();
    }
    expect(handle("Greeting", "top")).not.toHaveClass("connectable");
    expect(handle("Greeting", "bottom")).toHaveClass("connectable");
    expect(handle("End: not in your city", "right")).not.toHaveClass("connectable");
    expect(handle("End: not in your city", "left")).toHaveClass("connectable");
  });

  it("a step named with spaces is still found from the server's error", async () => {
    const graph = onboardingGraph();
    graph.steps[1] = { ...graph.steps[1], name: "Ask city " };
    const error = 'Step "Ask city " has no way out. Add a path or make it an end step.';
    serve({ graph, errors: [error] });
    const { user } = open();
    const problems = await screen.findByRole("region", { name: "Problems with this workflow" });
    await user.click(within(problems).getByRole("button", { name: error.trim() }));
    expect(within(panel()).getByRole("textbox", { name: "Step name" })).toHaveValue("Ask city ");
  });

  it("changing a step's type drops fields it no longer uses", async () => {
    const { patches } = serve();
    const { user } = open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    await select("Ask licence and experience");
    await user.click(within(panel()).getByRole("button", { name: "Advanced" }));
    await user.selectOptions(within(panel()).getByRole("combobox", { name: "Step type" }), "Say something");
    expect(within(panel()).queryByRole("textbox", { name: "Save the answer as" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    const step = patches[0].graph!.steps.find((s) => s.id === "ask_licence")!;
    expect(step.type).toBe("prompt");
    expect("field" in step).toBe(false);
  });

  it("an editor sees the edit controls once the role loads", async () => {
    serve();
    open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    expect(card("Greeting")).toHaveClass("draggable");
    expect(canvas().querySelector(".react-flow__handle.connectable")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Test chat" })).toBeInTheDocument();
  });

  it("shows an error with Try again", async () => {
    server.use(http.get("*/api/workflows/2", () => HttpResponse.json({ detail: "Not found." }, { status: 404 })));
    open();
    expect(await screen.findByText("Not found.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  const checkIn = () => within(panel()).getByRole("switch", { name: "Check in when the caller goes quiet" });

  it("turns check-ins off for the workflow from the side panel", async () => {
    const { patches } = serve();
    server.use(http.get("*/api/agents", () => HttpResponse.json([{ ...agentListItem, workflow: 2 }])));
    const { user } = open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    expect(within(panel()).getByRole("heading", { name: "Workflow settings" })).toBeInTheDocument();
    expect(checkIn()).toHaveAttribute("aria-checked", "true");
    await user.click(checkIn());
    await waitFor(() => expect(patches).toEqual([{ dead_air_enabled: false }]));
    expect(await screen.findByText("Saved. Agents using this workflow need republishing before callers hear the change.")).toBeInTheDocument();
    expect(checkIn()).toHaveAttribute("aria-checked", "false");
    // A setting, not a graph edit: nothing to save.
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("puts the switch back when saving it fails", async () => {
    serve({ patch: () => HttpResponse.json({ detail: "Could not reach the server." }, { status: 500 }) });
    const { user } = open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    await user.click(checkIn());
    expect(await screen.findByText("Could not reach the server.")).toBeInTheDocument();
    await waitFor(() => expect(checkIn()).toHaveAttribute("aria-checked", "true"));
  });

  it("says when the account has check-ins off", async () => {
    serve();
    server.use(http.get("*/api/me", () => HttpResponse.json({ ...me, workspace: { ...me.workspace, dead_air_enabled: false } })));
    open();
    await screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });
    expect(within(panel()).getByText(/Off for the whole account/)).toBeInTheDocument();
    expect(within(panel()).getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings/calls");
  });

  it("viewers see the workflow switch but can't change it", async () => {
    serve();
    open("viewer");
    await screen.findByRole("heading", { level: 1, name: "Driver onboarding" });
    expect(checkIn()).toBeDisabled();
  });
});
