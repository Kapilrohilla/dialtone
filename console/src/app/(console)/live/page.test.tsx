import userEvent from "@testing-library/user-event";
import { act, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "@/components/shell/Sidebar";
import type { LiveCall } from "@/lib/types";
import { dashboard, liveCall, me } from "@/test/fixtures";
import { renderWithProviders, router } from "@/test/render";
import { server } from "@/test/server";
import LivePage from "./page";

const START = "2026-11-05T10:00:00Z";
const second: LiveCall = {
  ...liveCall,
  room: "call-77aa",
  caller: "+919811122233",
  city: "",
  started_at: "2026-11-05T09:50:00Z",
  mood: "frustrated",
  step_path: ["Greeting"],
  current_step: "Greeting",
  captured: {},
  transcript_tail: [{ speaker: "caller", text: "Mujhe kisi se baat karni hai.", expressions: [], at: "2026-11-05T09:55:00Z" }],
};

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date(START));
});
afterEach(() => {
  vi.useRealTimers();
});

const advance = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));
const setup = () => userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
const serveLive = (...calls: LiveCall[]) => server.use(http.get("*/api/live", () => HttpResponse.json(calls)));

/** The viewer assertions mean nothing until the role has arrived: wait for it. */
async function roleLoaded(queryClient: { getQueryState: (key: readonly string[]) => { status: string } | undefined }) {
  await waitFor(() => expect(queryClient.getQueryState(["me"])?.status).toBe("success"));
}

describe("live calls", () => {
  it("polls and shows new transcript lines, with a ticking timer", async () => {
    let polls = 0;
    server.use(
      http.get("*/api/live", () => {
        polls += 1;
        const tail = polls > 1 ? [...liveCall.transcript_tail, { speaker: "caller", text: "Main Pune se hoon.", expressions: [], at: START }] : liveCall.transcript_tail;
        return HttpResponse.json([{ ...liveCall, transcript_tail: tail }]);
      }),
    );
    renderWithProviders(<LivePage />, { route: "/live" });
    const log = await screen.findByRole("log", { name: "Live transcript" });
    expect(within(log).getByText("हाँ, बोलिए।")).toBeInTheDocument();
    expect(within(log).queryByText("Main Pune se hoon.")).not.toBeInTheDocument();
    const timer = screen.getByLabelText("Call length");
    const before = timer.textContent;
    expect(before).toMatch(/^02:0\d$/);

    await advance(2500);
    expect(await within(log).findByText("Main Pune se hoon.")).toBeInTheDocument();
    expect(timer.textContent).not.toBe(before);
  });

  it("selects the first call and switches by click", async () => {
    serveLive(liveCall, second);
    const user = setup();
    renderWithProviders(<LivePage />, { route: "/live" });
    const list = await screen.findByRole("navigation", { name: "Calls in progress" });
    const rows = within(list).getAllByRole("button");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("aria-current", "true");
    expect(rows[1]).toHaveAttribute("aria-current", "false");
    expect(within(rows[0]).getByText("+91 80 4718 2290")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Pune")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Neutral")).toBeInTheDocument();
    expect(within(rows[1]).getByText("—")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Frustrated")).toBeInTheDocument();
    expect(await screen.findByText("हाँ, बोलिए।")).toBeInTheDocument();

    await user.click(rows[1]);
    expect(screen.getByText("Mujhe kisi se baat karni hai.")).toBeInTheDocument();
    expect(screen.queryByText("हाँ, बोलिए।")).not.toBeInTheDocument();
    expect(rows[1]).toHaveAttribute("aria-current", "true");
  });

  it("opens the call named in ?room=", async () => {
    serveLive(liveCall, second);
    renderWithProviders(<LivePage />, { route: "/live?room=call-77aa" });
    expect(await screen.findByText("Mujhe kisi se baat karni hai.")).toBeInTheDocument();
  });

  it("step line marks the current step in amber and past ones with a check", async () => {
    serveLive({ ...liveCall, step_path: ["Greeting", "Ask city", "Ask licence"] });
    renderWithProviders(<LivePage />, { route: "/live" });
    const steps = within(await screen.findByRole("list", { name: "Steps so far" })).getAllByRole("listitem");
    expect(steps.map((s) => s.textContent)).toEqual(["Greeting", "Ask city", "Ask licence"]);
    expect(steps[2]).toHaveAttribute("aria-current", "step");
    expect(steps[2].className).toMatch(/current/);
    expect(steps[0].className).not.toMatch(/current/);
    expect(steps[0].querySelector("svg")).not.toBeNull();
    expect(steps[2].querySelector("svg")).toBeNull();
  });

  it("shows no step line without steps, and captured details with plain labels", async () => {
    serveLive({ ...liveCall, step_path: [], captured: { city: "Pune", driving_years: "6", callback_time: "5 pm" } });
    renderWithProviders(<LivePage />, { route: "/live" });
    await screen.findByRole("log");
    expect(screen.queryByRole("list", { name: "Steps so far" })).not.toBeInTheDocument();
    const user = setup();
    expect(screen.getByRole("button", { name: "Details" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("City").nextSibling).toHaveTextContent("Pune");
    expect(screen.getByText("Driving years").nextSibling).toHaveTextContent("6");
    expect(screen.getByText("Call back at").nextSibling).toHaveTextContent("5 pm");
    await user.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.queryByText("Driving years")).not.toBeInTheDocument();
  });

  it("transfer confirms and shows the API message", async () => {
    let posted = 0;
    server.use(
      http.post("*/api/live/call-9b21/transfer", () => {
        posted += 1;
        return HttpResponse.json({ detail: "Live transfer isn't set up." }, { status: 409 });
      }),
    );
    const user = setup();
    renderWithProviders(<LivePage />, { route: "/live" });
    await user.click(await screen.findByRole("button", { name: "Transfer to a telecaller" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Transfer this caller to the telecalling team?")).toBeInTheDocument();
    expect(posted).toBe(0);
    await user.click(within(dialog).getByRole("button", { name: "Transfer" }));
    expect(await screen.findByText("Live transfer isn't set up.")).toBeInTheDocument();
    expect(posted).toBe(1);
  });

  it("cancelling the transfer sends nothing", async () => {
    let posted = 0;
    server.use(http.post("*/api/live/:room/transfer", () => { posted += 1; return HttpResponse.json({ detail: "Transferred." }); }));
    const user = setup();
    renderWithProviders(<LivePage />, { route: "/live" });
    await user.click(await screen.findByRole("button", { name: "Transfer to a telecaller" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posted).toBe(0);
  });

  it("end call confirms and posts", async () => {
    const posts: string[] = [];
    server.use(
      http.post("*/api/live/:room/end", ({ params }) => {
        posts.push(String(params.room));
        return HttpResponse.json({ detail: "Call ended." });
      }),
    );
    const user = setup();
    renderWithProviders(<LivePage />, { route: "/live" });
    await user.click(await screen.findByRole("button", { name: "End call" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("End this call now? The caller will be disconnected.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "End call" }));
    expect(await screen.findByText("Call ended.")).toBeInTheDocument();
    expect(posts).toEqual(["call-9b21"]);
  });

  it("shows a refused action's message", async () => {
    server.use(http.post("*/api/live/:room/end", () => HttpResponse.json({ detail: "The call server refused that; try again." }, { status: 502 })));
    const user = setup();
    renderWithProviders(<LivePage />, { route: "/live" });
    await user.click(await screen.findByRole("button", { name: "End call" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "End call" }));
    expect(await screen.findByText("The call server refused that; try again.")).toBeInTheDocument();
  });

  it("keeps an ended call visible with a history link", async () => {
    let live = true;
    server.use(http.get("*/api/live", () => HttpResponse.json(live ? [liveCall, second] : [second])));
    renderWithProviders(<LivePage />, { route: "/live" });
    expect(await screen.findByText("हाँ, बोलिए।")).toBeInTheDocument();
    live = false;
    await advance(2500);
    expect(await screen.findByText("This call has ended.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in call history" })).toHaveAttribute("href", "/calls?room=call-9b21");
    expect(screen.getByText("हाँ, बोलिए।")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "End call" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Transfer to a telecaller" })).not.toBeInTheDocument();
    const frozen = screen.getByLabelText("Call length").textContent;
    await advance(3000);
    expect(screen.getByLabelText("Call length").textContent).toBe(frozen);
    expect(within(screen.getByRole("navigation", { name: "Calls in progress" })).getAllByRole("button")).toHaveLength(1);
  });

  it("keeps the selected call when the list reorders", async () => {
    let order = [liveCall, second];
    server.use(http.get("*/api/live", () => HttpResponse.json(order)));
    renderWithProviders(<LivePage />, { route: "/live" });
    expect(await screen.findByText("हाँ, बोलिए।")).toBeInTheDocument();
    order = [second, liveCall];
    await advance(2500);
    await waitFor(() => expect(within(screen.getByRole("navigation", { name: "Calls in progress" })).getAllByRole("button")[0]).toHaveTextContent("Frustrated"));
    expect(screen.getByText("हाँ, बोलिए।")).toBeInTheDocument();
    expect(screen.queryByText("Mujhe kisi se baat karni hai.")).not.toBeInTheDocument();
  });

  it("holds a stale ?room= on the first call across a reorder", async () => {
    let order = [liveCall, second];
    server.use(http.get("*/api/live", () => HttpResponse.json(order)));
    renderWithProviders(<LivePage />, { route: "/live?room=gone" });
    expect(await screen.findByText("हाँ, बोलिए।")).toBeInTheDocument();
    order = [second, liveCall];
    await advance(2500);
    await waitFor(() => expect(within(screen.getByRole("navigation", { name: "Calls in progress" })).getAllByRole("button")[0]).toHaveTextContent("Frustrated"));
    expect(screen.getByText("हाँ, बोलिए।")).toBeInTheDocument();
  });

  it("a reorder while the confirm is open still ends the original call", async () => {
    let order = [liveCall, second];
    const posts: string[] = [];
    server.use(
      http.get("*/api/live", () => HttpResponse.json(order)),
      http.post("*/api/live/:room/end", ({ params }) => { posts.push(String(params.room)); return HttpResponse.json({ detail: "Call ended." }); }),
    );
    const user = setup();
    renderWithProviders(<LivePage />, { route: "/live" });
    await user.click(await screen.findByRole("button", { name: "End call" }));
    const dialog = await screen.findByRole("dialog");
    order = [second, liveCall];
    await advance(2500);
    await user.click(within(dialog).getByRole("button", { name: "End call" }));
    expect(await screen.findByText("Call ended.")).toBeInTheDocument();
    expect(posts).toEqual(["call-9b21"]);
  });

  it("closes an open confirm when the call ends", async () => {
    let live = true;
    server.use(http.get("*/api/live", () => HttpResponse.json(live ? [liveCall] : [second])));
    const user = setup();
    renderWithProviders(<LivePage />, { route: "/live" });
    await user.click(await screen.findByRole("button", { name: "End call" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    live = false;
    await advance(2500);
    expect(await screen.findByText("This call has ended.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("hang-up then failed poll keeps the ended note and hides actions", async () => {
    let mode: "both" | "one" | "fail" = "both";
    server.use(
      http.get("*/api/live", () =>
        mode === "fail" ? HttpResponse.json({ detail: "Couldn't reach the call server." }, { status: 502 }) : HttpResponse.json(mode === "both" ? [liveCall, second] : [second]),
      ),
    );
    renderWithProviders(<LivePage />, { route: "/live" });
    expect(await screen.findByText("हाँ, बोलिए।")).toBeInTheDocument();
    mode = "one";
    await advance(2500);
    expect(await screen.findByText("This call has ended.")).toBeInTheDocument();
    const frozen = screen.getByLabelText("Call length").textContent;
    mode = "fail";
    await advance(2500);
    await screen.findByText("Open in call history");
    await waitFor(() => expect(screen.getAllByRole("alert")).not.toHaveLength(0));
    expect(screen.getByText("This call has ended.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "End call" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Transfer to a telecaller" })).not.toBeInTheDocument();
    await advance(3000);
    expect(screen.getByLabelText("Call length").textContent).toBe(frozen);
  });

  it("replaces a stale ?room= in the URL with the first call", async () => {
    serveLive(liveCall, second);
    renderWithProviders(<LivePage />, { route: "/live?room=gone" });
    await screen.findByText("हाँ, बोलिए।");
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/live?room=call-9b21", { scroll: false }));
  });

  it("hides actions for viewers once the role has loaded", async () => {
    server.use(http.get("*/api/me", () => HttpResponse.json({ ...me, role: "viewer" })));
    const { queryClient } = renderWithProviders(<LivePage />, { route: "/live" });
    await screen.findByRole("log");
    await roleLoaded(queryClient);
    expect(screen.queryByRole("button", { name: "End call" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Transfer to a telecaller" })).not.toBeInTheDocument();
  });

  it("shows the actions to editors once the role loads", async () => {
    const { queryClient } = renderWithProviders(<LivePage />, { route: "/live" });
    await roleLoaded(queryClient);
    expect(await screen.findByRole("button", { name: "End call" })).toBeInTheDocument();
  });

  it("empty state names the live agent's number", async () => {
    serveLive();
    renderWithProviders(<LivePage />, { route: "/live" });
    expect(await screen.findByText("No calls right now.")).toBeInTheDocument();
    const line = await screen.findByText(/Calls show up here/);
    await waitFor(() => expect(line).toHaveTextContent("Calls show up here as soon as someone calls +91 80 4718 2290."));
  });

  it("empty state without a live agent says 'your number'", async () => {
    serveLive();
    server.use(http.get("*/api/dashboard", () => HttpResponse.json({ ...dashboard, live_agent: null })));
    renderWithProviders(<LivePage />, { route: "/live" });
    expect(await screen.findByText(/as someone calls your number\./)).toBeInTheDocument();
  });

  it("shows a loading state before the first answer", async () => {
    server.use(http.get("*/api/live", () => new Promise(() => undefined)));
    renderWithProviders(<LivePage />, { route: "/live" });
    expect(await screen.findByText("Loading calls")).toBeInTheDocument();
  });

  it("error state offers retry, and polling continues", async () => {
    let fail = true;
    let requests = 0;
    server.use(
      http.get("*/api/live", () => {
        requests += 1;
        return fail ? HttpResponse.json({ detail: "Couldn't reach the call server." }, { status: 502 }) : HttpResponse.json([liveCall]);
      }),
    );
    const user = setup();
    renderWithProviders(<LivePage />, { route: "/live" });
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't reach the call server.");
    fail = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("log")).toBeInTheDocument();

    // a later failure keeps the last calls on screen with a notice, and the next poll recovers
    fail = true;
    await advance(2500);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't reach the call server.");
    expect(screen.getByRole("log")).toBeInTheDocument();
    expect(screen.queryByText("This call has ended.")).not.toBeInTheDocument();
    fail = false;
    const seen = requests;
    await advance(2500);
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(requests).toBeGreaterThan(seen);
  });

  it("the sidebar stops polling while this screen polls faster", async () => {
    let requests = 0;
    server.use(http.get("*/api/live", () => { requests += 1; return HttpResponse.json([liveCall]); }));
    const { queryClient } = renderWithProviders(<><Sidebar /><LivePage /></>, { route: "/live" });
    await screen.findByRole("log");
    const intervals = () => queryClient.getQueryCache().find({ queryKey: ["live"] })?.observers.map((o) => o.options.refetchInterval);
    expect(intervals()).toHaveLength(2);
    expect(intervals()).toContain(2000);
    expect(intervals()).not.toContain(10_000);
    await advance(10_500);
    // the first load, then one poll every 2 seconds
    expect(requests).toBeGreaterThanOrEqual(5);
    expect(requests).toBeLessThanOrEqual(6);
  });
});
