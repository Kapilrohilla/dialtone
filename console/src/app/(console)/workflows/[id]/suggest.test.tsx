import userEvent from "@testing-library/user-event";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { StartSuggestions, SuggestionPatch, WorkflowUpdate } from "@/lib/queries";
import type { Graph, SuggestionSet, Workflow } from "@/lib/types";
import { me, onboardingGraph, suggestionSet, workflow as baseWorkflow } from "@/test/fixtures";
import { setParams } from "@/test/navigation";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import WorkflowBuilderPage from "./page";

type Serve = { set?: SuggestionSet | null; start?: () => Response | SuggestionSet; graph?: Graph };

/** Serves the onboarding workflow and its "Suggest with AI" draft; records every write. */
function serve(opts: Serve = {}) {
  let current: Workflow = { ...baseWorkflow, graph: opts.graph ?? onboardingGraph(), errors: [] };
  let set: SuggestionSet | null = opts.set === undefined ? suggestionSet() : opts.set;
  const patches: WorkflowUpdate[] = [];
  const starts: StartSuggestions[] = [];
  const itemPatches: (SuggestionPatch & { id: number })[] = [];
  const closes: number[] = [];
  server.use(
    http.get("*/api/workflows/2", () => HttpResponse.json(current)),
    http.patch("*/api/workflows/2", async ({ request }) => {
      const body = (await request.json()) as WorkflowUpdate;
      patches.push(body);
      current = { ...current, ...(body.graph ? { graph: body.graph, current_revision: current.current_revision + 1 } : {}) };
      return HttpResponse.json(current);
    }),
    http.get("*/api/workflows/2/suggestions/current", () => (set ? HttpResponse.json(set) : new HttpResponse(null, { status: 204 }))),
    http.post("*/api/workflows/2/suggestions", async ({ request }) => {
      starts.push((await request.json()) as StartSuggestions);
      // By default the run is already done when the POST answers; a `start` answer of "running" is finished by the next poll.
      set = opts.set === undefined ? suggestionSet() : opts.set;
      const out = opts.start?.() ?? set;
      if (out instanceof Response) return out;
      return HttpResponse.json(out, { status: 202 });
    }),
    http.patch("*/api/workflows/2/suggestions/:item", async ({ request, params }) => {
      const body = (await request.json()) as SuggestionPatch;
      const id = Number(params.item);
      itemPatches.push({ ...body, id });
      if (set) {
        set = {
          ...set,
          items: set.items.map((i) =>
            i.id === id ? ({ ...i, ...(body.status ? { status: body.status } : {}), ...(body.edited_payload ? { payload: body.edited_payload, edited: true } : {}) } as typeof i) : i,
          ),
        };
      }
      return HttpResponse.json(set);
    }),
    http.post("*/api/workflows/2/suggestions/:set/close", ({ params }) => {
      closes.push(Number(params.set));
      set = null;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  return { patches, starts, itemPatches, closes };
}

function open(role: "owner" | "viewer" = "owner") {
  if (role !== "owner") server.use(http.get("*/api/me", () => HttpResponse.json({ ...me, role })));
  setParams({ id: "2" });
  const user = userEvent.setup();
  return { user, ...renderWithProviders(<WorkflowBuilderPage />, { route: "/workflows/2" }) };
}

const canvas = () => document.querySelector<HTMLElement>(".react-flow")!;
const suggestions = () => screen.getByRole("complementary", { name: "Suggestions" });
const loaded = () => screen.findByRole("heading", { level: 1, name: /Driver onboarding/ });

async function review(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "Review" }));
  return suggestions();
}

describe("Suggest with AI", () => {
  it("starts a run for the whole workflow, waits for it and shows the answers and expressions", async () => {
    const { starts } = serve({ set: null, start: () => suggestionSet({ status: "running", items: [] }) });
    const { user } = open();
    await loaded();
    await user.click(screen.getByRole("button", { name: "Suggest with AI" }));
    const dialog = screen.getByRole("dialog", { name: "Suggest with AI" });
    expect(within(dialog).getByRole("radio", { name: /This step/ })).toBeDisabled();
    expect(within(dialog).getByRole("radio", { name: "Whole workflow" })).toBeChecked();
    // The run is going when the POST answers; the next poll finds it done.
    server.use(http.get("*/api/workflows/2/suggestions/current", () => HttpResponse.json(suggestionSet())));
    await user.click(within(dialog).getByRole("button", { name: "Suggest" }));
    expect(starts).toEqual([{ scope: "workflow", kinds: ["answers", "expressions"] }]);
    const panel = await screen.findByRole("complementary", { name: "Suggestions" });
    expect(await within(panel).findByText("Looking at 4 steps…")).toBeInTheDocument();
    expect(await within(panel).findByText(/These are a draft. Your workflow hasn.t changed./, undefined, { timeout: 4000 })).toBeInTheDocument();
    expect(within(panel).getByRole("tab", { name: "Answers 2" })).toHaveAttribute("aria-selected", "true");
    const first = within(panel).getByRole("article", { name: "Answer Not sure which licence" });
    expect(within(first).getByText("New step")).toBeInTheDocument();
    expect(within(first).getByText("“पता नहीं”")).toBeInTheDocument();
    // Pending answers are drawn on the canvas, not added to the graph.
    expect(within(canvas()).getByText("Explain licence types")).toBeInTheDocument();
    expect(within(canvas()).getByText("Suggested")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await user.click(within(panel).getByRole("tab", { name: "Expressions 1" }));
    expect(within(panel).getByText("Expressions guide the agent's tone. They are hints, not exact audio.")).toBeInTheDocument();
    expect(within(panel).getByTestId("suggested-103").querySelector("[data-added]")).toHaveTextContent("[sad]");
  });

  it("asks for one step from 'Suggest more answers' and offers to save first", async () => {
    const { starts, patches } = serve({ set: null });
    const { user } = open();
    await loaded();
    const el = within(canvas()).getByText("Ask city").closest<HTMLElement>(".react-flow__node")!;
    fireEvent.click(el);
    const panel = await screen.findByRole("complementary", { name: "Step" });
    await user.clear(within(panel).getByRole("textbox", { name: "Step name" }));
    await user.type(within(panel).getByRole("textbox", { name: "Step name" }), "City");
    await user.click(within(panel).getByRole("button", { name: "Suggest more answers" }));
    const dialog = screen.getByRole("dialog", { name: "Suggest with AI" });
    expect(within(dialog).getByRole("radio", { name: "This step (City)" })).toBeChecked();
    expect(within(dialog).getByText("Suggestions use the last saved version. Save first?")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("checkbox", { name: /Expressions/ }));
    await user.click(within(dialog).getByRole("button", { name: "Save and suggest" }));
    await waitFor(() => expect(starts).toEqual([{ scope: "step", step_id: "ask_city", kinds: ["answers"] }]));
    expect(patches).toHaveLength(1);
  });

  it("accepts, undoes and saves accepted suggestions with the graph", async () => {
    const { patches } = serve();
    const { user } = open();
    await loaded();
    const panel = await review(user);
    await user.click(within(within(panel).getByRole("article", { name: "Answer Licence applied, not received" })).getByRole("button", { name: "Accept" }));
    expect(within(panel).getByText("Accepted. Save to keep it.")).toBeInTheDocument();
    expect(within(panel).queryByRole("article", { name: "Answer Licence applied, not received" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    await user.click(within(panel).getByRole("button", { name: "Undo" }));
    expect(within(panel).getByRole("article", { name: "Answer Licence applied, not received" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    await user.click(within(within(panel).getByRole("article", { name: "Answer Not sure which licence" })).getByRole("button", { name: "Accept" }));
    // One accepted, two still a draft: the Save dialog says what is kept.
    await user.click(screen.getByRole("button", { name: "Save" }));
    const dialog = screen.getByRole("dialog", { name: "Save accepted suggestions?" });
    expect(within(dialog).getByText("Still a draft").nextSibling).toHaveTextContent("2");
    expect(within(dialog).getByText(/Calls change only when you republish the agent./)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0].accepted_suggestions).toEqual([101]);
    const g = patches[0].graph!;
    const step = g.steps.find((s) => s.name === "Explain licence types")!;
    expect(g.paths.find((p) => p.to === step.id)).toMatchObject({ from: "ask_licence", label: "Not sure which licence", examples: ["पता नहीं", "शायद yellow है", "not sure ji"] });
    expect(g.paths.find((p) => p.from === step.id)).toMatchObject({ to: "ask_licence", label: "Explained licence types" });
  });

  it("accepts every valid item at once", async () => {
    const { patches } = serve();
    const { user } = open();
    await loaded();
    const panel = await review(user);
    await user.click(within(panel).getByRole("button", { name: "Accept all 2" }));
    await user.click(within(panel).getByRole("tab", { name: "Expressions 1" }));
    await user.click(within(panel).getByRole("button", { name: "Accept all 1" }));
    expect(within(panel).getByText("All reviewed")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0].accepted_suggestions).toEqual([101, 102, 103]);
    expect(patches[0].graph!.steps.find((s) => s.id === "end_no_licence")?.prompt).toBe("[[expr:sad]] बिना लाइसेंस के हम आगे नहीं बढ़ पाएँगे, धन्यवाद।");
  });

  it("blocks Accept when a local edit clashes, and dismisses for everyone", async () => {
    const { itemPatches } = serve();
    const { user } = open();
    await loaded();
    const el = within(canvas()).getByText("Ask licence and experience").closest<HTMLElement>(".react-flow__node")!;
    fireEvent.click(el);
    const step = await screen.findByRole("complementary", { name: "Step" });
    const label = within(step).getByRole("textbox", { name: "Label of path 2" });
    await user.clear(label);
    await user.type(label, "Licence applied, not received");
    const panel = await review(user);
    const row = within(panel).getByRole("article", { name: "Answer Licence applied, not received" });
    expect(within(row).getByText("A path with this name already exists. Rename it to accept.")).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "Dismiss Licence applied, not received" }));
    await waitFor(() => expect(itemPatches).toEqual([{ id: 102, status: "dismissed" }]));
    await waitFor(() => expect(within(panel).queryByRole("article", { name: "Answer Licence applied, not received" })).not.toBeInTheDocument());
  });

  it("edits a suggestion and saves it to the draft", async () => {
    const { itemPatches } = serve();
    const { user } = open();
    await loaded();
    const panel = await review(user);
    await user.click(within(within(panel).getByRole("article", { name: "Answer Licence applied, not received" })).getByRole("button", { name: "Edit" }));
    const form = screen.getByRole("complementary", { name: "Edit suggestion" });
    const name = within(form).getByRole("textbox", { name: "Path name" });
    await user.clear(name);
    await user.type(name, "Applied, waiting");
    await user.click(within(form).getByRole("button", { name: "Add phrase" }));
    await user.type(within(form).getByRole("textbox", { name: "New phrase for Caller phrases" }), "abhi aaya nahi{Enter}");
    await user.click(within(form).getByRole("button", { name: "Save to draft" }));
    await waitFor(() => expect(itemPatches).toHaveLength(1));
    expect(itemPatches[0]).toMatchObject({
      id: 102,
      edited_payload: { label: "Applied, waiting", examples: ["apply किया है", "abhi aaya nahi"], target: { step_id: "schedule_callback" } },
    });
    expect(await screen.findByRole("article", { name: "Answer Applied, waiting" })).toBeInTheDocument();
  });

  it("shows a teammate's draft in a banner, and discards it", async () => {
    const { closes } = serve({ set: suggestionSet({ created_by: { id: 9, name: "Asha" } }) });
    const { user } = open();
    await loaded();
    expect(await screen.findByText("3 suggestions are waiting for review")).toBeInTheDocument();
    expect(screen.getByText(/From Asha/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Suggest with AI" }));
    expect(screen.getByText("This replaces 3 pending suggestions from Asha.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Discard draft" }));
    await waitFor(() => expect(closes).toEqual([7]));
    await waitFor(() => expect(screen.queryByText(/waiting for review/)).not.toBeInTheDocument());
  });

  it("shows the empty, error and daily limit states", async () => {
    serve({ set: suggestionSet({ status: "empty", items: [], scope: "step", step_ids: ["ask_city"] }) });
    const { user } = open();
    await loaded();
    await user.click(screen.getByRole("button", { name: "Suggest with AI" }));
    await user.click(screen.getByRole("button", { name: "Suggest" }));
    expect(await screen.findByText("This step already covers the answers callers usually give.")).toBeInTheDocument();
    server.use(http.post("*/api/workflows/2/suggestions", () => HttpResponse.json({ detail: "Daily limit reached" }, { status: 429 })));
    await user.click(within(suggestions()).getByRole("button", { name: "Suggest again" }));
    expect(await within(suggestions()).findByText("Daily limit reached. Try again tomorrow.")).toBeInTheDocument();
    expect(within(suggestions()).queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("shows a failed run with Try again", async () => {
    serve({ set: suggestionSet({ status: "error", error: "Couldn't get suggestions.", items: [] }) });
    const { user } = open();
    await loaded();
    await user.click(screen.getByRole("button", { name: "Suggest with AI" }));
    await user.click(screen.getByRole("button", { name: "Suggest" }));
    expect(await screen.findByText("Couldn't get suggestions. Your workflow hasn't changed.")).toBeInTheDocument();
    expect(within(suggestions()).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("warns when the suggestions are out of date", async () => {
    const set = suggestionSet();
    set.items[0] = { ...set.items[0], stale: true };
    set.items[1] = { ...set.items[1], stale: true, invalid_reason: "The step this pointed to was removed." };
    serve({ set });
    const { user } = open();
    await loaded();
    const panel = await review(user);
    expect(within(panel).getByText("These suggestions are out of date.")).toBeInTheDocument();
    const valid = within(panel).getByRole("region", { name: "Still valid suggestions" });
    expect(within(valid).getByText(/Not sure which licence/)).toBeInTheDocument();
    const invalid = within(panel).getByRole("region", { name: "No longer valid suggestions" });
    expect(within(invalid).getByText("The step this pointed to was removed.")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Review anyway" }));
    expect(within(panel).getByRole("article", { name: "Answer Not sure which licence" })).toBeInTheDocument();
  });

  it("is read-only for viewers", async () => {
    serve();
    const { user } = open("viewer");
    await loaded();
    expect(screen.queryByRole("button", { name: "Suggest with AI" })).not.toBeInTheDocument();
    expect(await screen.findByText("3 suggestions are waiting for review")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Discard draft" })).not.toBeInTheDocument();
    const panel = await review(user);
    expect(within(panel).getByRole("article", { name: "Answer Not sure which licence" })).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: /^Accept/ })).not.toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: /^Dismiss/ })).not.toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Discard all" })).not.toBeInTheDocument();
  });

  it("adds caller phrases to a path by hand", async () => {
    const { patches } = serve({ set: null });
    const { user } = open();
    await loaded();
    fireEvent.click(within(canvas()).getByText("Ask licence and experience").closest<HTMLElement>(".react-flow__node")!);
    const step = await screen.findByRole("complementary", { name: "Step" });
    await user.click(within(step).getAllByRole("button", { name: "Add phrase" })[1]);
    await user.type(within(step).getByRole("textbox", { name: "New phrase for Caller phrases for No licence" }), "license nahi hai{Enter}");
    expect(within(step).getByRole("list", { name: "Caller phrases for No licence" })).toHaveTextContent("“license nahi hai”");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0].graph!.paths.find((p) => p.label === "No licence")?.examples).toEqual(["license nahi hai"]);
    await user.click(within(step).getByRole("button", { name: "Remove phrase license nahi hai" }));
    expect(within(step).queryByText("“license nahi hai”")).not.toBeInTheDocument();
  });
});
