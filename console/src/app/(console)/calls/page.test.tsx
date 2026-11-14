import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { agentListItem, callDetail, callPage, callRow, me } from "@/test/fixtures";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toast } from "@/components/ui";
import { setRoute } from "@/test/navigation";
import { renderWithProviders, router } from "@/test/render";
import { server } from "@/test/server";
import CallsPage from "./page";

// Only Date is faked: the debounce and the request round trips run on real timers.
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-05T10:00:00Z"));
});
afterEach(() => vi.useRealTimers());

const RANGE = "from=2026-10-30&to=2026-11-05";

/** Records the query string of every list request. */
function recordLists(page = callPage) {
  const seen: URLSearchParams[] = [];
  server.use(
    http.get("*/api/calls", ({ request }) => {
      seen.push(new URL(request.url).searchParams);
      return HttpResponse.json(page);
    }),
  );
  return seen;
}

const asViewer = () => server.use(http.get("*/api/me", () => HttpResponse.json({ ...me, role: "viewer" })));
const lastUrl = (fn: typeof router.push) => String(fn.mock.calls.at(-1)?.[0]);

describe("call history", () => {
  it("defaults to the last 7 days in the URL and request", async () => {
    const seen = recordLists();
    renderWithProviders(<CallsPage />, { route: "/calls" });
    await screen.findByRole("table", { name: "Calls" });
    expect(seen[0].get("from")).toBe("2026-10-30");
    expect(seen[0].get("to")).toBe("2026-11-05");
    expect(router.replace).toHaveBeenCalledWith(`/calls?${RANGE}`, { scroll: false });
    expect(screen.getByRole("radio", { name: "Last 7 days" })).toBeChecked();
  });

  it("works out today in the user's time zone", async () => {
    vi.setSystemTime(new Date("2026-11-05T20:00:00Z")); // already 6 Nov in Kolkata, still 5 Nov in UTC
    server.use(http.get("*/api/me", () => HttpResponse.json({ ...me, preferences: { ...me.preferences, time_zone: "UTC" } })));
    const seen = recordLists();
    renderWithProviders(<CallsPage />, { route: "/calls" });
    await screen.findByRole("table", { name: "Calls" });
    expect(seen).toHaveLength(1);
    expect(seen[0].get("to")).toBe("2026-11-05");
    expect(seen[0].get("from")).toBe("2026-10-30");
  });

  it("shows the table with outcome, mood, duration and summary", async () => {
    renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}` });
    const row = (await screen.findByRole("button", { name: /Open call from \+91 80 4718 2290/ })).closest("tr")!;
    expect(within(row).getByText("Interested")).toBeInTheDocument();
    expect(within(row).getByText("Happy")).toBeInTheDocument();
    expect(within(row).getByText("02:05")).toBeInTheDocument();
    expect(within(row).getByText("No recording")).toBeInTheDocument();
    expect(within(row).getByText(callRow.summary)).toBeInTheDocument();
  });

  it("shows dashes for a call with no report yet", async () => {
    server.use(
      http.get("*/api/calls", () =>
        HttpResponse.json({ ...callPage, results: [{ ...callRow, outcome: "", mood: "", summary: "", duration_s: null }] }),
      ),
    );
    renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}` });
    const row = (await screen.findByRole("button", { name: /Open call from/ })).closest("tr")!;
    expect(within(row).getAllByText("—")).toHaveLength(4); // outcome, mood, score, duration
    expect(within(row).getByText("No summary")).toBeInTheDocument();
  });

  it("labels the phone search like the other filters", async () => {
    renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}` });
    await screen.findByRole("table", { name: "Calls" });
    expect(screen.getByLabelText("Phone number")).toHaveAttribute("type", "search");
  });

  it("search debounces into q", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}` });
    await screen.findByRole("table", { name: "Calls" });
    await user.type(screen.getByRole("searchbox", { name: "Phone number" }), "9876");
    expect(router.replace).not.toHaveBeenCalledWith(expect.stringContaining("q="), expect.anything());
    await waitFor(() => expect(lastUrl(router.replace)).toContain("q=9876"));
    expect(router.replace.mock.calls.filter(([url]) => String(url).includes("q="))).toHaveLength(1);
  });

  it("keeps keystrokes typed while the URL echoes an earlier commit", async () => {
    const user = userEvent.setup();
    const view = renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}` });
    const again = () =>
      view.rerender(
        <QueryClientProvider client={view.queryClient}>
          <Toast>
            <CallsPage />
          </Toast>
        </QueryClientProvider>,
      );
    const box = screen.getByRole("searchbox", { name: "Phone number" });
    await user.type(box, "98");
    await waitFor(() => expect(lastUrl(router.replace)).toContain("q=98"));
    await user.type(box, "7 "); // typed before the URL catches up
    setRoute(`/calls?${RANGE}&q=98`); // the echo of the first commit
    again();
    expect(box).toHaveValue("987 ");
    await waitFor(() => expect(lastUrl(router.replace)).toContain("q=987"));
    setRoute(`/calls?${RANGE}&q=987`);
    again();
    expect(box).toHaveValue("987 ");
  });

  it("follows an external URL change, such as Clear filters", async () => {
    const user = userEvent.setup();
    const view = renderWithProviders(<CallsPage />, { route: `/calls?q=98&${RANGE}` });
    const box = screen.getByRole("searchbox", { name: "Phone number" });
    expect(box).toHaveValue("98");
    await user.type(box, "7");
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    setRoute(`/calls?${RANGE}`);
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <Toast>
          <CallsPage />
        </Toast>
      </QueryClientProvider>,
    );
    expect(box).toHaveValue("");
  });

  it("outcome and agent filters update the URL and request", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}&page=3` });
    await screen.findByRole("table", { name: "Calls" });
    await user.selectOptions(screen.getByRole("combobox", { name: "Outcome" }), "Call back");
    expect(lastUrl(router.push)).toBe(`/calls?outcome=Call+back&${RANGE}`);
    await user.selectOptions(await screen.findByRole("combobox", { name: "Agent" }), String(agentListItem.id));
    expect(lastUrl(router.push)).toContain(`agent=${agentListItem.id}`);
  });

  it("sends the filters in the URL with the request", async () => {
    const seen = recordLists();
    renderWithProviders(<CallsPage />, { route: `/calls?outcome=Dropped&agent=${agentListItem.id}&mood=angry&city=Pune&q=98&${RANGE}` });
    await screen.findByRole("table", { name: "Calls" });
    expect(Object.fromEntries(seen[0])).toMatchObject({ outcome: "Dropped", agent: String(agentListItem.id), mood: "angry", city: "Pune", q: "98", from: "2026-10-30" });
    expect(screen.getByRole("combobox", { name: "Outcome" })).toHaveValue("Dropped");
    expect(screen.getByLabelText("Mood")).toHaveValue("angry");
  });

  it("export link carries the same filters", async () => {
    renderWithProviders(<CallsPage />, { route: `/calls?outcome=Dropped&q=98&page=2&${RANGE}&room=call-7f3a` });
    const link = screen.getByRole("link", { name: "Export" });
    expect(link).toHaveAttribute("download");
    expect(link).toHaveAttribute("href", `/api/calls/export.csv?q=98&outcome=Dropped&${RANGE}`);
  });

  it("More filters reveals mood and city, which commit to the URL", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}` });
    expect(screen.queryByLabelText("Mood")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "More filters" }));
    await user.type(screen.getByLabelText("City"), "Pune");
    await waitFor(() => expect(lastUrl(router.replace)).toContain("city=Pune"));
    await user.type(screen.getByLabelText("Mood"), "angry");
    await waitFor(() => expect(lastUrl(router.replace)).toContain("mood=angry"));
  });

  it("clears filters but keeps the dates", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CallsPage />, { route: `/calls?outcome=Dropped&${RANGE}` });
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(lastUrl(router.push)).toBe(`/calls?${RANGE}`);
  });

  it("shows the preset again when the URL range matches one", async () => {
    const user = userEvent.setup();
    const view = renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}` });
    await user.click(screen.getByRole("radio", { name: "Custom" }));
    expect(screen.getByLabelText("From date")).toBeInTheDocument();
    setRoute("/calls?from=2026-11-05&to=2026-11-05"); // back navigation
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <Toast>
          <CallsPage />
        </Toast>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("radio", { name: "Today" })).toBeChecked();
    expect(screen.queryByLabelText("From date")).not.toBeInTheDocument();
  });

  it("changes the date range", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}` });
    await user.click(screen.getByRole("radio", { name: "Today" }));
    expect(lastUrl(router.push)).toBe("/calls?from=2026-11-05&to=2026-11-05");
    await user.click(screen.getByRole("radio", { name: "Custom" }));
    expect(screen.getByLabelText("From date")).toHaveValue("2026-10-30");
    expect(screen.getByLabelText("To date")).toHaveValue("2026-11-05");
  });

  it("opens the slide-over from a row and the URL", async () => {
    const user = userEvent.setup();
    const first = renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}` });
    await user.click(await screen.findByRole("button", { name: /Open call from/ }));
    expect(lastUrl(router.push)).toBe(`/calls?${RANGE}&room=call-7f3a`);
    first.unmount();

    renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}&room=call-7f3a` });
    const panel = await screen.findByRole("dialog");
    expect(await within(panel).findByText("What happened")).toBeInTheDocument();
    expect(within(panel).getByText(callRow.summary)).toBeInTheDocument();
    expect(within(panel).getByText("Greeting → Ask city")).toBeInTheDocument();
    expect(within(panel).getByText("City")).toBeInTheDocument();
    expect(within(panel).getByText("Pune")).toBeInTheDocument();
    expect(within(panel).getByText("हाँ, बोलिए।")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Close" }));
    expect(router.replace).toHaveBeenLastCalledWith(`/calls?${RANGE}`, { scroll: false });
  });

  it("slide-over says why there's no recording", async () => {
    const view = renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}&room=call-7f3a` });
    const panel = await screen.findByRole("dialog");
    await within(panel).findByText("What happened");
    expect(panel.querySelector("audio")).toBeNull();
    expect(within(panel).getByText("No recording for this call")).toBeInTheDocument();
    expect(within(panel).getByText("This call wasn't recorded.")).toBeInTheDocument();
    view.unmount();

    server.use(http.get("*/api/calls/:room", () => HttpResponse.json({ ...callDetail, outcome: "Not reached" })));
    const second = renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}&room=call-7f3a` });
    expect(await screen.findByText("The caller didn't pick up, so nothing was recorded.")).toBeInTheDocument();
    second.unmount();

    server.use(http.get("*/api/calls/:room", () => HttpResponse.json({ ...callDetail, recording_status: "purged" })));
    const third = renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}&room=call-7f3a` });
    expect(await screen.findByText("Recordings are kept for 90 days.")).toBeInTheDocument();
    third.unmount();

    server.use(http.get("*/api/calls/:room", () => HttpResponse.json({ ...callDetail, recording_status: "processing" })));
    renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}&room=call-7f3a` });
    expect(await screen.findByText("Recording is being prepared")).toBeInTheDocument();
  });

  describe("recordings", () => {
    const recorded = {
      ...callDetail,
      recording_url: "/api/calls/call-7f3a/recording",
      recording_status: "complete",
      recording_duration_s: 134.2,
      recording_started_at: "2026-11-05T09:02:00Z",
    };
    const serveAudio = (status = 200) =>
      server.use(
        http.get("*/api/calls/:room", () => HttpResponse.json(recorded)),
        http.get("*/api/calls/:room/recording", () =>
          status === 200 ? new HttpResponse(new Uint8Array([79, 103, 103, 83]), { headers: { "Content-Type": "audio/ogg" } }) : HttpResponse.json({ detail: "Nope." }, { status }),
        ),
      );

    it("plays, seeks from the transcript and changes speed", async () => {
      serveAudio();
      const user = userEvent.setup();
      renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}&room=call-7f3a` });
      const panel = await screen.findByRole("dialog");
      const play = await within(panel).findByRole("button", { name: "Play" });
      expect(within(panel).getByText("Paused")).toBeInTheDocument();
      expect(within(panel).getByText("00:00 / 02:14")).toBeInTheDocument();
      expect(within(panel).getByText("2 turns")).toBeInTheDocument();
      expect(within(panel).getByRole("link", { name: "Download recording" })).toHaveAttribute("href", "/api/calls/call-7f3a/recording?download=1");

      await user.click(play);
      expect(await within(panel).findByRole("button", { name: "Pause" })).toBeInTheDocument();
      expect(within(panel).getAllByText("Playing").length).toBeGreaterThan(0);

      const audio = panel.querySelector("audio")!;
      await user.click(within(panel).getByRole("button", { name: "Play from 00:09" }));
      expect(audio.currentTime).toBe(9);
      const line = within(panel).getByText("हाँ, बोलिए।").closest("[data-line]");
      expect(line).toHaveAttribute("aria-current", "true");

      const slider = within(panel).getByRole("slider", { name: "Seek" });
      slider.focus();
      await user.keyboard("{ArrowRight}");
      expect(audio.currentTime).toBe(14);

      await user.click(within(panel).getByRole("button", { name: "Playback speed 1x" }));
      await user.click(within(panel).getByRole("menuitemradio", { name: "1.5x" }));
      expect(audio.playbackRate).toBe(1.5);
      expect(within(panel).getByRole("button", { name: "Playback speed 1.5x" })).toBeInTheDocument();
    });

    it("says when the recording can't load and tries again", async () => {
      serveAudio(500);
      const user = userEvent.setup();
      renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}&room=call-7f3a` });
      expect(await screen.findByText("Couldn't load this recording.")).toBeInTheDocument();
      serveAudio();
      await user.click(screen.getByRole("button", { name: "Try again" }));
      expect(await screen.findByRole("button", { name: "Play" })).toBeInTheDocument();
    });

    it("the table shows a play button, processing and no recording", async () => {
      server.use(
        http.get("*/api/calls", () =>
          HttpResponse.json({
            ...callPage,
            count: 3,
            results: [
              { ...callRow, has_recording: true, recording_status: "complete" },
              { ...callRow, room: "call-2", caller: "+919820111984", recording_status: "processing" },
              { ...callRow, room: "call-3", caller: "+919820111985" },
            ],
          }),
        ),
      );
      const user = userEvent.setup();
      renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}` });
      const play = await screen.findByRole("button", { name: "Play recording of call from +91 80 4718 2290" });
      expect(screen.getByText("Processing")).toBeInTheDocument();
      expect(screen.getByText("No recording")).toBeInTheDocument();
      await user.click(play);
      expect(lastUrl(router.push)).toBe(`/calls?${RANGE}&room=call-7f3a`);
    });
  });

  it("slide-over falls back to the reason, hides empty steps and answers, and explains an empty transcript", async () => {
    server.use(
      http.get("*/api/calls/:room", () =>
        HttpResponse.json({ ...callDetail, summary: "", reason: "Caller asked for a person.", answers: {}, step_path: [], transcript: [] }),
      ),
    );
    renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}&room=call-7f3a` });
    const panel = await screen.findByRole("dialog");
    expect(await within(panel).findByText("Caller asked for a person.")).toBeInTheDocument();
    expect(within(panel).queryByText("Steps")).not.toBeInTheDocument();
    expect(within(panel).queryByText("Answers")).not.toBeInTheDocument();
    expect(within(panel).getByText("No transcript. Transcripts are kept for 90 days.")).toBeInTheDocument();
  });

  it("mark for call back posts needs_person", async () => {
    const user = userEvent.setup();
    let body: unknown;
    server.use(
      http.post("*/api/calls/:room/needs-person", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ room: "call-7f3a", needs_person: true, handled_at: null });
      }),
    );
    const view = renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}&room=call-7f3a` });
    const invalidate = vi.spyOn(view.queryClient, "invalidateQueries");
    const button = await screen.findByRole("button", { name: "Mark for call back" });
    await user.click(button);
    expect(await screen.findByText("Marked for a call back. It shows on the dashboard under Needs a person.")).toBeInTheDocument();
    expect(body).toEqual({ needs_person: true });
    expect(screen.queryByRole("button", { name: "Mark for call back" })).not.toBeInTheDocument();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["dashboard"] });
  });

  it("viewers get no call back button once the role has loaded", async () => {
    asViewer();
    const view = renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}&room=call-7f3a` });
    const panel = await screen.findByRole("dialog");
    await within(panel).findByText("What happened");
    await waitFor(() => expect(view.queryClient.getQueryState(["me"])?.status).toBe("success"));
    expect(view.queryClient.getQueryData<{ role: string }>(["me"])?.role).toBe("viewer");
    await new Promise((r) => setTimeout(r, 50)); // let the loaded role render
    expect(screen.queryByRole("button", { name: "Mark for call back" })).not.toBeInTheDocument();
  });

  it("paginates", async () => {
    const user = userEvent.setup();
    const seen = recordLists({ ...callPage, page: 2, pages: 7, count: 160 });
    renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}&page=2` });
    expect(await screen.findByText("Page 2 of 7")).toBeInTheDocument();
    expect(seen[0].get("page")).toBe("2");
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(lastUrl(router.push)).toBe(`/calls?${RANGE}&page=3`);
    await user.click(screen.getByRole("button", { name: "Previous" }));
    expect(lastUrl(router.push)).toBe(`/calls?${RANGE}`);
  });

  it("shows empty, filtered-empty and error states", async () => {
    const empty = { results: [], count: 0, page: 1, pages: 1 };
    server.use(http.get("*/api/calls", () => HttpResponse.json(empty)));
    const a = renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}` });
    expect(await screen.findByText("No calls yet.")).toBeInTheDocument();
    a.unmount();

    // Nothing in this range, but the workspace has calls: say so honestly.
    server.use(
      http.get("*/api/calls", ({ request }) => HttpResponse.json(new URL(request.url).searchParams.has("from") ? empty : callPage)),
    );
    const b = renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}` });
    expect(await screen.findByText("No calls match these filters.")).toBeInTheDocument();
    expect(screen.queryByText("No calls yet.")).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Show last 30 days" }));
    expect(lastUrl(router.push)).toBe("/calls?from=2026-10-07&to=2026-11-05");
    b.unmount();

    server.use(http.get("*/api/calls", () => HttpResponse.json(empty)));
    renderWithProviders(<CallsPage />, { route: `/calls?q=00&${RANGE}` });
    expect(await screen.findByText("No calls match these filters.")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Clear filters" })).toHaveLength(2);
  });

  it("shows a server error with a retry", async () => {
    const user = userEvent.setup();
    let ok = false;
    server.use(http.get("*/api/calls", () => (ok ? HttpResponse.json(callPage) : HttpResponse.json({ detail: "Down." }, { status: 500 }))));
    renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}` });
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load calls");
    ok = true;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("table", { name: "Calls" })).toBeInTheDocument();
  });

  it("shows a bad-filter error next to the filters", async () => {
    server.use(http.get("*/api/calls", () => HttpResponse.json({ from: ["Use a date like 2026-11-05."] }, { status: 400 })));
    renderWithProviders(<CallsPage />, { route: "/calls?from=nope&to=2026-11-05" });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Use a date like 2026-11-05.");
    expect(within(screen.getByRole("region", { name: "Filters" })).getByRole("alert")).toBe(alert);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
