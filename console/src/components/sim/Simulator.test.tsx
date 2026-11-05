import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { SimRequest } from "@/lib/queries";
import type { SimResponse } from "@/lib/types";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import { Simulator } from "./Simulator";

const reply = (over: Partial<SimResponse> = {}): SimResponse => ({ reply: "", state: {}, step: null, outcome: null, ended: false, ...over });

/** Serves the given replies in order and records each request body. */
function serve(replies: (SimResponse | Response)[], path = "*/api/agents/3/simulate") {
  const bodies: SimRequest[] = [];
  let i = 0;
  server.use(
    http.post(path, async ({ request }) => {
      bodies.push((await request.json()) as SimRequest);
      const next = replies[Math.min(i++, replies.length - 1)];
      return next instanceof Response ? next : HttpResponse.json(next);
    }),
  );
  return bodies;
}

const transcript = () => screen.getByRole("log", { name: "Conversation" });

describe("Simulator", () => {
  it("opens with the agent's first line", async () => {
    const bodies = serve([reply({ reply: "[[expr:happy]] नमस्ते! क्या मेरी बात {{lead.name}} जी से हो रही है?", state: { turn: 1 } })]);
    renderWithProviders(<Simulator kind="agent" id={3} onClose={() => {}} />);
    expect(screen.getByRole("dialog", { name: "Test call" })).toBeInTheDocument();
    expect(screen.getByText("Type as the caller. Nothing is saved and nobody is called.")).toBeInTheDocument();
    const log = transcript();
    expect(await within(log).findByText("Agent")).toBeInTheDocument();
    expect(within(log).getByText("[happy]")).toHaveAttribute("data-expr", "happy");
    expect(within(log).getByText("{{lead.name}}")).toBeInTheDocument();
    expect(log).not.toHaveTextContent("[[expr:happy]]");
    expect(bodies).toEqual([{ messages: [], state: null }]);
  });

  it("sends caller text with the previous state", async () => {
    const bodies = serve([reply({ reply: "Hello, am I speaking to Ravi?", state: { turn: 1 } }), reply({ reply: "Great, which city?", state: { turn: 2 } })]);
    const user = userEvent.setup();
    renderWithProviders(<Simulator kind="agent" id={3} onClose={() => {}} />);
    await within(transcript()).findByText("Hello, am I speaking to Ravi?");
    const box = screen.getByRole("textbox", { name: "Your reply" });
    expect(box).toHaveAttribute("maxlength", "2000");
    await user.type(box, "Yes{Shift>}{Enter}{/Shift}speaking");
    expect(box).toHaveValue("Yes\nspeaking");
    await user.keyboard("{Enter}");
    expect(await within(transcript()).findByText("Great, which city?")).toBeInTheDocument();
    expect(bodies[1]).toEqual({
      messages: [
        { role: "agent", text: "Hello, am I speaking to Ravi?" },
        { role: "caller", text: "Yes\nspeaking" },
      ],
      state: { turn: 1 },
    });
    expect(within(transcript()).getByText("Caller")).toBeInTheDocument();
    expect(box).toHaveValue("");
  });

  it("shows the current step", async () => {
    serve([reply({ reply: "Let me explain the weekly plan.", step: { id: "plan", name: "Explain the plan" } })], "*/api/workflows/2/simulate");
    renderWithProviders(<Simulator kind="workflow" id={2} onClose={() => {}} />);
    expect(screen.getByRole("dialog", { name: "Try it" })).toBeInTheDocument();
    expect(await screen.findByText("Step: Explain the plan")).toBeInTheDocument();
  });

  it("shows the simulator-down message and keeps the typed text", async () => {
    serve([
      reply({ reply: "Hello?" }),
      HttpResponse.json({ detail: "The test simulator isn't running." }, { status: 503 }),
      reply({ reply: "Sure." }),
    ]);
    const user = userEvent.setup();
    renderWithProviders(<Simulator kind="agent" id={3} onClose={() => {}} />);
    await within(transcript()).findByText("Hello?");
    const box = screen.getByRole("textbox", { name: "Your reply" });
    await user.type(box, "Haan bolo");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("The test simulator isn't running.")).toBeInTheDocument();
    expect(box).toHaveValue("Haan bolo");
    expect(within(transcript()).queryByText("Haan bolo")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await within(transcript()).findByText("Sure.")).toBeInTheDocument();
    expect(screen.queryByText("The test simulator isn't running.")).not.toBeInTheDocument();
  });

  it("shows the end of the call with the outcome", async () => {
    const bodies = serve([reply({ reply: "Hello?" }), reply({ reply: "Thank you, bye!", ended: true, outcome: { disposition: "INTERESTED" } }), reply({ reply: "Hello again?" })]);
    const user = userEvent.setup();
    renderWithProviders(<Simulator kind="agent" id={3} onClose={() => {}} />);
    await within(transcript()).findByText("Hello?");
    await user.type(screen.getByRole("textbox", { name: "Your reply" }), "I want to join{Enter}");
    expect(await screen.findByText("The call ended.")).toBeInTheDocument();
    expect(screen.getByText("Interested")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Your reply" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start again" }));
    expect(await within(transcript()).findByText("Hello again?")).toBeInTheDocument();
    expect(within(transcript()).queryByText("Thank you, bye!")).not.toBeInTheDocument();
    await waitFor(() => expect(bodies[2]).toEqual({ messages: [], state: null }));
  });

  it("closes", async () => {
    serve([reply({ reply: "Hello?" })]);
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<Simulator kind="agent" id={3} onClose={onClose} />);
    await within(transcript()).findByText("Hello?");
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
  });
});
