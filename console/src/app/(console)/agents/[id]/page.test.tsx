import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { AgentUpdate } from "@/lib/queries";
import type { Agent, KnowledgeListItem, Voice } from "@/lib/types";
import { agent as baseAgent, me, voices, workflow as baseWorkflow } from "@/test/fixtures";
import { setParams } from "@/test/navigation";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import AgentEditorPage from "./page";

const DRAFT_KEY = "cv-draft-agent-3";
const SAVE_WAIT = { timeout: 2500 };

/** Serves `agent` and records each PATCH body, answering with the merged agent (or `respond`'s answer). */
function serve(agent: Agent = baseAgent, respond?: (body: AgentUpdate) => Response | undefined | Promise<Response | undefined>) {
  let current = agent;
  const patches: AgentUpdate[] = [];
  server.use(
    http.get("*/api/agents/3", () => HttpResponse.json(current)),
    http.patch("*/api/agents/3", async ({ request }) => {
      const body = (await request.json()) as AgentUpdate;
      patches.push(body);
      const answer = await respond?.(body);
      if (answer) return answer;
      const { settings, ...rest } = body;
      current = {
        ...current,
        ...rest,
        settings: settings
          ? { ...current.settings, ...settings, dead_air: { ...current.settings.dead_air, ...settings.dead_air } }
          : current.settings,
      };
      return HttpResponse.json(current);
    }),
  );
  return patches;
}

function open(role: "owner" | "viewer" = "owner") {
  if (role !== "owner") server.use(http.get("*/api/me", () => HttpResponse.json({ ...me, role })));
  setParams({ id: "3" });
  const user = userEvent.setup();
  const view = renderWithProviders(<AgentEditorPage />, { route: "/agents/3" });
  return { user, ...view };
}

const section = (title: string) => screen.getByRole("region", { name: title });

describe("agent script editor", () => {
  it("loads sections into editors and autosaves edits", async () => {
    const patches = serve();
    const { user } = open();
    const greeting = await screen.findByRole("textbox", { name: "Greeting" });
    expect(screen.getByRole("textbox", { name: "City and licence" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "If the driver hesitates" })).toBeInTheDocument();
    expect(greeting).toHaveTextContent("नमस्ते");
    expect(within(section("Greeting")).getByRole("button", { name: "Variable" })).toBeInTheDocument();
    expect(within(section("Greeting")).queryByRole("button", { name: "Bold" })).not.toBeInTheDocument();

    await user.click(greeting);
    await user.keyboard("ok");
    await waitFor(() => expect(patches).toHaveLength(1), SAVE_WAIT);
    expect(Object.keys(patches[0])).toEqual(["script"]);
    const script = patches[0].script!;
    expect(script.map((s) => s.id)).toEqual(["greeting", "city-and-licence", "if-the-driver-hesitates"]);
    expect(script[0].body).toContain("ok");
    expect(script[0].body.replace("ok", "")).toBe(baseAgent.script[0].body);
    expect(script[1]).toEqual(baseAgent.script[1]);
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("adds, reorders and deletes sections", async () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue("0000-new");
    const patches = serve();
    const { user } = open();
    await screen.findByRole("textbox", { name: "Greeting" });

    await user.click(screen.getByRole("button", { name: "Add section" }));
    expect(screen.getByRole("textbox", { name: "Heading of section 4" })).toHaveValue("New section");

    await user.click(within(section("City and licence")).getByRole("button", { name: "Section actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Move up" }));

    await user.click(within(section("New section")).getByRole("button", { name: "Section actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(within(section("Greeting")).getByRole("button", { name: "Section actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    const confirm = screen.getByRole("dialog", { name: "Delete Greeting?" });
    await user.click(within(confirm).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(patches.at(-1)?.script?.map((s) => s.id)).toEqual(["city-and-licence", "if-the-driver-hesitates"]), SAVE_WAIT);
    expect(screen.queryByRole("region", { name: "Greeting" })).not.toBeInTheDocument();
  });

  it("adds a section that is saved with a new id", async () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue("0000-new");
    const patches = serve();
    const { user } = open();
    await screen.findByRole("textbox", { name: "Greeting" });
    await user.click(screen.getByRole("button", { name: "Add section" }));
    const heading = screen.getByRole("textbox", { name: "Heading of section 4" });
    await user.clear(heading);
    await user.type(heading, "Closing");
    await waitFor(() => expect(patches.at(-1)?.script?.at(-1)).toEqual({ id: "0000-new", title: "Closing", body: "" }), SAVE_WAIT);
  });

  it("publish flushes pending edits first", async () => {
    const order: string[] = [];
    serve({ ...baseAgent, status: "draft", published_version: null }, async () => {
      order.push("patch");
      await delay(100);
      order.push("patch saved");
      return undefined;
    });
    server.use(
      http.post("*/api/agents/3/publish", () => {
        order.push("publish");
        return HttpResponse.json({ version: 5 });
      }),
    );
    const { user } = open();
    await user.click(await screen.findByRole("textbox", { name: "Greeting" }));
    await user.keyboard("ok");
    await user.click(screen.getByRole("button", { name: "Publish" }));
    const dialog = await screen.findByRole("dialog", { name: "Publish Driver lead qualifier?" });
    expect(order).toEqual(["patch", "patch saved"]);
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(order).toEqual(["patch", "patch saved", "publish"]));
  });

  it("keeps the draft and shows the signed-out message when autosave gets a signed-out 403", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/agents/3", search: "", origin: "http://localhost:3000", href: "http://localhost:3000/agents/3", assign });
    const patches = serve(baseAgent, () =>
      HttpResponse.json({ detail: "Authentication credentials were not provided." }, { status: 403 }),
    );
    const { user, unmount } = open();
    const greeting = await screen.findByRole("textbox", { name: "Greeting" });
    await user.click(greeting);
    await user.keyboard("ok");
    expect(await screen.findByText("You were signed out. Sign in again to keep your changes.", {}, SAVE_WAIT)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/sign-in?next=/agents/3");
    expect(assign).not.toHaveBeenCalled();
    expect(greeting).toHaveTextContent("ok");
    const draft = JSON.parse(sessionStorage.getItem(DRAFT_KEY)!);
    expect(draft[0].body).toContain("ok");

    await user.click(greeting);
    await user.keyboard("more");
    await new Promise((r) => setTimeout(r, 1000));
    expect(patches).toHaveLength(1);
    expect(JSON.parse(sessionStorage.getItem(DRAFT_KEY)!)[0].body).toContain("more");
    unmount();
    sessionStorage.removeItem(DRAFT_KEY);
  });

  it("offers to restore a draft that differs from the server", async () => {
    const restored = [{ ...baseAgent.script[0], body: "Restored greeting" }, ...baseAgent.script.slice(1)];
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify(restored));
    const patches = serve();
    const { user } = open();
    await user.click(await screen.findByRole("button", { name: "Restore unsaved changes" }));
    expect(await screen.findByRole("textbox", { name: "Greeting" })).toHaveTextContent("Restored greeting");
    await waitFor(() => expect(patches.at(-1)?.script?.[0].body).toBe("Restored greeting"), SAVE_WAIT);
    await waitFor(() => expect(sessionStorage.getItem(DRAFT_KEY)).toBeNull());
    expect(screen.queryByRole("button", { name: "Restore unsaved changes" })).not.toBeInTheDocument();
  });

  it("forgets a draft that matches the server", async () => {
    sessionStorage.setItem(DRAFT_KEY, JSON.stringify(baseAgent.script));
    serve();
    open();
    await screen.findByRole("textbox", { name: "Greeting" });
    expect(screen.queryByRole("button", { name: "Restore unsaved changes" })).not.toBeInTheDocument();
    expect(sessionStorage.getItem(DRAFT_KEY)).toBeNull();
  });

  it("picks a voice and previews it", async () => {
    const puck: Voice = { id: "Puck", name: "Puck", description: "Male, upbeat", sample: "/voices/puck.wav" };
    server.use(http.get("*/api/voices", () => HttpResponse.json({ pipeline: "gemini-live", voices: [...voices, puck] })));
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    const patches = serve();
    const { user, container } = open();
    const select = await screen.findByRole("combobox", { name: "Voice" });
    await screen.findByRole("option", { name: "Puck, Male, upbeat" });
    expect(within(select).getAllByRole("option")[0]).toHaveTextContent("Default for this line");
    expect(screen.getByText("Voices for Gemini Live.")).toBeInTheDocument();
    await user.selectOptions(select, "Puck");
    await waitFor(() => expect(patches).toEqual([{ voice_id: "Puck" }]));
    await user.click(screen.getByRole("button", { name: "Preview" }));
    expect(container.querySelector("audio")).toHaveAttribute("src", "/voices/puck.wav");
    expect(play).toHaveBeenCalled();

    await user.selectOptions(select, "priya");
    expect(screen.queryByRole("button", { name: "Preview" })).not.toBeInTheDocument();
  });

  it("saves the agent's name from the field when it loses focus", async () => {
    const patches = serve();
    const { user } = open();
    const field = await screen.findByRole("textbox", { name: "Agent's name" });
    await user.clear(field);
    await user.type(field, "Asha");
    await user.tab();
    await waitFor(() => expect(patches).toEqual([{ persona_name: "Asha" }]));
  });

  it("opens an agent with no name and can clear the name", async () => {
    const patches = serve({ ...baseAgent, persona_name: "" });
    const { user } = open();
    const field = await screen.findByRole("textbox", { name: "Agent's name" });
    expect(field).toHaveValue("");
    await user.type(field, "Maya");
    await user.tab();
    await waitFor(() => expect(patches).toEqual([{ persona_name: "Maya" }]));
    await user.clear(field);
    await user.tab();
    await waitFor(() => expect(patches).toEqual([{ persona_name: "Maya" }, { persona_name: "" }]));
  });

  it("saves company name, name pronunciation and consent line under settings, trimmed", async () => {
    const patches = serve();
    const { user } = open();
    await user.type(await screen.findByRole("textbox", { name: "Company name" }), " Northwind Car Rentals ");
    await user.tab();
    await user.type(screen.getByRole("textbox", { name: "How to say the agent's name" }), "Maa-yaa");
    await user.tab();
    await user.type(screen.getByRole("textbox", { name: "Consent line" }), "This call is recorded.");
    await user.tab();
    await waitFor(() =>
      expect(patches).toEqual([
        { settings: { company_name: "Northwind Car Rentals" } },
        { settings: { name_pronunciation: "Maa-yaa" } },
        { settings: { consent_line: "This call is recorded." } },
      ]),
    );
  });

  it("shows the server's dead-air error under the timings", async () => {
    const patches = serve(baseAgent, (body) =>
      body.settings
        ? HttpResponse.json(
            { settings: { dead_air: { non_field_errors: ["Dead-air timings must increase: first check-in, then second check-in, then hang up."] } } },
            { status: 400 },
          )
        : undefined,
    );
    const { user } = open();
    await user.click(await screen.findByRole("button", { name: "Advanced" }));
    const first = screen.getByRole("spinbutton", { name: "First check-in after (s)" });
    await user.clear(first);
    await user.type(first, "10");
    await user.tab();
    await waitFor(() => expect(patches).toEqual([{ settings: { dead_air: { nudge_s: 10 } } }]));
    const group = screen.getByRole("group", { name: "Check-in timings" });
    expect(await within(group).findByText("Dead-air timings must increase: first check-in, then second check-in, then hang up.")).toBeInTheDocument();
    expect(first).toHaveValue(10);
    expect(screen.getByText("Gemini Live")).toBeInTheDocument();
  });

  it("switches behaviour and links a workflow", async () => {
    const patches = serve({ ...baseAgent, workflow: null });
    const { user } = open();
    await user.click(await screen.findByRole("switch", { name: "Adjust to caller's mood" }));
    await waitFor(() => expect(patches).toEqual([{ settings: { mood_adaptation: false } }]));
    await user.click(screen.getByRole("switch", { name: "Check in when the caller goes quiet" }));
    await waitFor(() => expect(patches.at(-1)).toEqual({ settings: { dead_air: { enabled: false } } }));
    const workflow = screen.getByRole("combobox", { name: "Workflow" });
    expect(within(workflow).getAllByRole("option")[0]).toHaveTextContent("None, script only");
    await screen.findByRole("option", { name: "Driver onboarding" });
    expect(screen.queryByRole("link", { name: "Open workflow" })).not.toBeInTheDocument();
    await user.selectOptions(workflow, "Driver onboarding");
    await waitFor(() => expect(patches.at(-1)).toEqual({ workflow: 2 }));
    expect(screen.getByRole("link", { name: "Open workflow" })).toHaveAttribute("href", "/workflows/2");
  });

  it("says when its workflow keeps check-ins off", async () => {
    serve();
    server.use(http.get("*/api/workflows", () => HttpResponse.json([{ ...baseWorkflow, dead_air_enabled: false }])));
    open();
    expect(await screen.findByText('Off in the workflow "Driver onboarding", so this agent won\'t check in.')).toBeInTheDocument();
  });

  it("says when the account keeps check-ins off, ahead of the workflow", async () => {
    serve();
    server.use(
      http.get("*/api/me", () => HttpResponse.json({ ...me, workspace: { ...me.workspace, dead_air_enabled: false } })),
      http.get("*/api/workflows", () => HttpResponse.json([{ ...baseWorkflow, dead_air_enabled: false }])),
    );
    open();
    expect(await screen.findByText(/Off for the whole account, so this agent won't check in\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings/calls");
    expect(screen.queryByText(/Off in the workflow/)).not.toBeInTheDocument();
  });

  it("says nothing extra when check-ins are on everywhere", async () => {
    serve();
    open();
    await screen.findByRole("switch", { name: "Check in when the caller goes quiet" });
    await screen.findByRole("option", { name: "Driver onboarding" });
    expect(screen.queryByText(/so this agent won't check in/)).not.toBeInTheDocument();
  });

  it("attaches and removes knowledge", async () => {
    const docs: KnowledgeListItem[] = [
      { id: 1, title: "Pricing and plans, Pune", updated_at: "2026-11-03T12:00:00Z", current_revision: 2, used_by: 1 },
      { id: 2, title: "Documents needed", updated_at: "2026-11-03T12:00:00Z", current_revision: 1, used_by: 0 },
    ];
    server.use(http.get("*/api/knowledge", () => HttpResponse.json(docs)));
    const patches = serve({ ...baseAgent, knowledge: [] });
    const { user } = open();
    expect(await screen.findByText("The agent only quotes what is written in these documents.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Attach" }));
    const dialog = screen.getByRole("dialog", { name: "Attach knowledge" });
    await user.click(await within(dialog).findByRole("checkbox", { name: "Pricing and plans, Pune" }));
    await user.click(within(dialog).getByRole("checkbox", { name: "Documents needed" }));
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches).toEqual([{ knowledge: [1, 2] }]));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Linked documents" });
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Pricing and plans, Pune", "Documents needed"]);
    await user.click(screen.getByRole("button", { name: "Remove Pricing and plans, Pune" }));
    await waitFor(() => expect(patches.at(-1)).toEqual({ knowledge: [2] }));
    expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Documents needed"]);
  });

  it("creates a custom expression and saves it on the agent", async () => {
    const patches = serve();
    const { user } = open();
    await screen.findByRole("textbox", { name: "Greeting" });
    await user.click(within(section("Greeting")).getByRole("button", { name: "Expression" }));
    await user.click(screen.getByRole("menuitem", { name: "New expression…" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "calm");
    await user.type(screen.getByRole("textbox", { name: "How to say it" }), "say this slowly and calmly");
    await user.click(screen.getByRole("button", { name: "Add expression" }));
    await waitFor(() => expect(patches[0]).toEqual({ custom_expressions: { calm: "say this slowly and calmly" } }));
    await waitFor(() => expect(patches[1]?.script?.[0].body).toContain("[[expr:calm]]"), SAVE_WAIT);
    expect(patches).toHaveLength(2);
  });

  it("renames the agent from the breadcrumb", async () => {
    const patches = serve();
    const { user } = open();
    await user.click(await screen.findByRole("button", { name: "Rename Driver lead qualifier" }));
    const input = screen.getByRole("textbox", { name: "Agent name" });
    await user.clear(input);
    await user.type(input, "Driver qualifier{Enter}");
    await waitFor(() => expect(patches).toEqual([{ name: "Driver qualifier" }]));
    expect(await screen.findByRole("button", { name: "Rename Driver qualifier" })).toBeInTheDocument();
  });

  it("shows the older-version banner and Republish", async () => {
    serve({ ...baseAgent, is_outdated: true });
    open();
    expect(await screen.findByText("Uses an older version. Callers hear the last published version until you republish.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Republish" })).toBeEnabled();
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("disables Publish when the live version is up to date", async () => {
    serve();
    open();
    const publish = await screen.findByRole("button", { name: "Publish" });
    expect(publish).toBeDisabled();
    expect(publish).toHaveAttribute("title", "Up to date");
    expect(screen.queryByText(/Uses an older version/)).not.toBeInTheDocument();
  });

  it("opens the test call with the agent's draft", async () => {
    const asked: unknown[] = [];
    server.use(
      http.post("*/api/agents/3/simulate", async ({ request }) => {
        asked.push(await request.json());
        return HttpResponse.json({ reply: "नमस्ते!", state: {}, step: null, outcome: null, ended: false });
      }),
    );
    serve();
    const { user } = open();
    await user.click(await screen.findByRole("button", { name: "Test chat" }));
    const panel = screen.getByRole("dialog", { name: "Test chat" });
    expect(await within(panel).findByText("नमस्ते!")).toBeInTheDocument();
    expect(asked).toEqual([{ messages: [], state: null }]);
  });

  it("opens the voice test, which asks the dashboard for a call token", async () => {
    let asked = 0;
    server.use(
      http.post("*/api/agents/3/web-call", () => {
        asked += 1;
        return HttpResponse.json({ detail: "LiveKit isn't set up." }, { status: 503 });
      }),
    );
    serve();
    const { user } = open();
    await user.click(await screen.findByRole("button", { name: "Voice test" }));
    const panel = screen.getByRole("dialog", { name: "Voice test" });
    expect(await within(panel).findByRole("alert")).toHaveTextContent("LiveKit isn't set up.");
    expect(asked).toBe(1);
  });

  it("is read-only for viewers", async () => {
    serve();
    open("viewer");
    const greeting = await screen.findByRole("textbox", { name: "Greeting" });
    await waitFor(() => expect(greeting).toHaveAttribute("contenteditable", "false"));
    expect(screen.queryByRole("button", { name: "Publish" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Test chat" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Voice test" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add section" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Section actions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Expression" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Attach" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Remove / })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Rename / })).not.toBeInTheDocument();
    expect(screen.getByText("Driver lead qualifier")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Agent's name" })).toHaveAttribute("readonly");
    expect(screen.getByRole("combobox", { name: "Voice" })).toBeDisabled();
    expect(screen.getByRole("switch", { name: "Adjust to caller's mood" })).toBeDisabled();
  });

  it("shows an error state when the agent cannot load", async () => {
    server.use(http.get("*/api/agents/3", () => HttpResponse.json({ detail: "Not found." }, { status: 404 })));
    open();
    expect(await screen.findByText("Not found.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("keeps a timings error after a later save elsewhere succeeds, and blocks Publish", async () => {
    const message = "Dead-air timings must increase: first check-in, then second check-in, then hang up.";
    const patches = serve({ ...baseAgent, status: "draft", published_version: null }, (body) =>
      body.settings?.dead_air?.nudge_s !== undefined
        ? HttpResponse.json({ settings: { dead_air: { non_field_errors: [message] } } }, { status: 400 })
        : undefined,
    );
    const { user } = open();
    await user.click(await screen.findByRole("button", { name: "Advanced" }));
    const first = screen.getByRole("spinbutton", { name: "First check-in after (s)" });
    await user.clear(first);
    await user.type(first, "10");
    await user.tab();
    const group = screen.getByRole("group", { name: "Check-in timings" });
    expect(await within(group).findByText(message)).toBeInTheDocument();

    await user.selectOptions(screen.getByRole("combobox", { name: "Voice" }), "priya");
    await waitFor(() => expect(patches.at(-1)).toEqual({ voice_id: "priya" }));
    await waitFor(() => expect(screen.queryByText("Saving…")).not.toBeInTheDocument());
    expect(within(group).getByText(message)).toBeInTheDocument();
    expect(screen.getByText("Not saved")).toBeInTheDocument();
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Publish" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.clear(first);
    await user.type(first, "4");
    await user.tab();
    await waitFor(() => expect(within(group).queryByText(message)).not.toBeInTheDocument());
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });

  it("does not send timings that are not whole seconds, and blocks Publish", async () => {
    const patches = serve({ ...baseAgent, status: "draft", published_version: null });
    const { user } = open();
    await user.click(await screen.findByRole("button", { name: "Advanced" }));
    const hangUp = screen.getByRole("spinbutton", { name: "Hang up after (s)" });
    await user.clear(hangUp);
    await user.type(hangUp, "1.5");
    await user.tab();
    expect(within(screen.getByRole("group", { name: "Check-in timings" })).getByText("Use whole seconds.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Publish" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(patches).toEqual([]);
  });

  it("inserts no chip when the new expression can't be saved", async () => {
    const patches = serve(baseAgent, (body) =>
      body.custom_expressions ? HttpResponse.json({ custom_expressions: ["At most 20 custom expressions."] }, { status: 400 }) : undefined,
    );
    const { user } = open();
    const greeting = await screen.findByRole("textbox", { name: "Greeting" });
    await user.click(within(section("Greeting")).getByRole("button", { name: "Expression" }));
    await user.click(screen.getByRole("menuitem", { name: "New expression…" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "calm");
    await user.type(screen.getByRole("textbox", { name: "How to say it" }), "say this slowly and calmly");
    await user.click(screen.getByRole("button", { name: "Add expression" }));
    expect(await screen.findByText("At most 20 custom expressions.")).toBeInTheDocument();
    expect(greeting).not.toHaveTextContent("[calm]");
    await new Promise((r) => setTimeout(r, 1000));
    expect(patches).toEqual([{ custom_expressions: { calm: "say this slowly and calmly" } }]);
    await user.click(within(section("Greeting")).getByRole("button", { name: "Expression" }));
    expect(screen.queryByRole("menuitem", { name: /^calm/ })).not.toBeInTheDocument();
  });

  describe("a failed field save clears when the field goes back to its saved value", () => {
    const draft = { ...baseAgent, status: "draft" as const, published_version: null };
    const refuse = (field: keyof AgentUpdate) => (body: AgentUpdate) =>
      field in body && body[field] !== draft[field as keyof Agent]
        ? HttpResponse.json({ [field]: ["Not allowed here."] }, { status: 400 })
        : undefined;

    async function expectPublishOpens(user: ReturnType<typeof userEvent.setup>) {
      await waitFor(() => expect(screen.queryByText("Not allowed here.")).not.toBeInTheDocument());
      await user.click(screen.getByRole("button", { name: "Publish" }));
      expect(await screen.findByRole("dialog", { name: "Publish Driver lead qualifier?" })).toBeInTheDocument();
    }

    it("agent's name field", async () => {
      const patches = serve(draft, refuse("persona_name"));
      const { user } = open();
      const field = await screen.findByRole("textbox", { name: "Agent's name" });
      await user.clear(field);
      await user.type(field, "Asha");
      await user.tab();
      expect(await screen.findByText("Not allowed here.")).toBeInTheDocument();
      await user.clear(field);
      await user.type(field, draft.persona_name);
      await user.tab();
      await expectPublishOpens(user);
      expect(patches).toEqual([{ persona_name: "Asha" }]);
    });

    it("phone number", async () => {
      const patches = serve(draft, refuse("phone_number"));
      const { user } = open();
      await user.click(await screen.findByRole("button", { name: "Advanced" }));
      const field = screen.getByRole("textbox", { name: "Phone number" });
      await user.clear(field);
      await user.type(field, "12");
      await user.tab();
      expect(await screen.findByText("Not allowed here.")).toBeInTheDocument();
      await user.clear(field);
      await user.type(field, draft.phone_number);
      await user.tab();
      await expectPublishOpens(user);
      expect(patches).toEqual([{ phone_number: "12" }]);
    });

    it("description", async () => {
      const patches = serve(draft, refuse("description"));
      const { user } = open();
      await user.click(await screen.findByRole("button", { name: "Advanced" }));
      const field = screen.getByRole("textbox", { name: "Description" });
      await user.type(field, " more");
      await user.tab();
      expect(await screen.findByText("Not allowed here.")).toBeInTheDocument();
      await user.clear(field);
      await user.type(field, draft.description);
      await user.tab();
      await expectPublishOpens(user);
      expect(patches).toEqual([{ description: `${draft.description} more` }]);
    });

    it("breadcrumb rename", async () => {
      const patches = serve(draft, refuse("name"));
      const { user } = open();
      await user.click(await screen.findByRole("button", { name: "Rename Driver lead qualifier" }));
      const input = screen.getByRole("textbox", { name: "Agent name" });
      await user.clear(input);
      await user.type(input, "Driver qualifier{Enter}");
      expect(await screen.findByText("Not allowed here.")).toBeInTheDocument();
      // The crumb shows the saved name again; finishing with it clears the error.
      await user.click(screen.getByRole("button", { name: "Rename Driver lead qualifier" }));
      await user.keyboard("{Enter}");
      await expectPublishOpens(user);
      expect(patches).toEqual([{ name: "Driver qualifier" }]);
    });
  });

  it("says why Publish stopped when a field is not saved", async () => {
    serve({ ...baseAgent, status: "draft", published_version: null }, (body) =>
      body.persona_name ? HttpResponse.json({ persona_name: ["Not allowed here."] }, { status: 400 }) : undefined,
    );
    const { user } = open();
    const field = await screen.findByRole("textbox", { name: "Agent's name" });
    await user.clear(field);
    await user.type(field, "Asha");
    await user.tab();
    expect(await screen.findByText("Not allowed here.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Publish" }));
    expect(await screen.findByText("Fix the errors before publishing.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("sends a quick off-on toggle one save at a time, in order", async () => {
    const events: string[] = [];
    serve(baseAgent, async (body) => {
      const value = String(body.settings?.mood_adaptation);
      events.push(`start ${value}`);
      if (value === "false") await delay(150);
      events.push(`end ${value}`);
      return undefined;
    });
    const { user } = open();
    const toggle = await screen.findByRole("switch", { name: "Adjust to caller's mood" });
    await user.click(toggle);
    await user.click(toggle);
    await waitFor(() => expect(events).toEqual(["start false", "end false", "start true", "end true"]));
    await waitFor(() => expect(screen.queryByText("Saving…")).not.toBeInTheDocument());
  });
});
