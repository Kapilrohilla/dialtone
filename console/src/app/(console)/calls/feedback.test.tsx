import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { CallDetail, CallFeedback } from "@/lib/types";
import { callDetail } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import CallsPage from "./page";

const OPEN = `/calls?room=${callDetail.room}`;

const theirs: CallFeedback = {
  id: 7, author: "Ravi", mine: false, ratings: { listening: 4, pacing: 2 }, overall: 3,
  remarks: "Talked over me while I gave my number.", updated_at: "2026-11-14T10:00:00Z",
};

function serve(detail: Partial<CallDetail>, feedback: CallFeedback[] = []) {
  const puts: unknown[] = [];
  server.use(
    http.get("*/api/calls/:room", () => HttpResponse.json({ ...callDetail, ...detail })),
    http.get("*/api/calls/:room/feedback", () => HttpResponse.json(feedback)),
    http.put("*/api/calls/:room/feedback", async ({ request }) => {
      const body = (await request.json()) as CallFeedback;
      puts.push(body);
      return HttpResponse.json({ ...body, id: 9, author: "Me", mine: true, updated_at: "2026-11-14T11:00:00Z" });
    }),
  );
  return puts;
}

describe("call detail: response time and tester ratings", () => {
  it("shows the response gap, heard and without opening pauses", async () => {
    serve({
      response_gap: {
        n: 4,
        system: { avg_ms: 900, p50_ms: 800, p95_ms: 1400, max_ms: 1400 },
        perceived: { avg_ms: 1250, p50_ms: 1100, p95_ms: 2600, max_ms: 2600 },
        slow_replies: 1, slow_threshold_ms: 2000, agent_cut_ins: 2, replies: [],
      },
    });
    renderWithProviders(<CallsPage />, { route: OPEN });
    const section = (await screen.findByRole("heading", { name: "Response time" })).closest("section")!;
    expect(section).toHaveTextContent("Heard by caller1.3 s avg · 2.6 s p95 · 2.6 s worst");
    expect(section).toHaveTextContent("Without opening pauses0.9 s avg · 1.4 s p95 · 1.4 s worst");
    expect(section).toHaveTextContent("Slow replies1 of 4 over 2.0 s");
    expect(section).toHaveTextContent("Agent cut in2 times");
  });

  it("leaves the section out for calls measured before the response gap existed", async () => {
    serve({ response_gap: null });
    renderWithProviders(<CallsPage />, { route: OPEN });
    await screen.findByRole("heading", { name: "Tester ratings" });
    expect(screen.queryByRole("heading", { name: "Response time" })).not.toBeInTheDocument();
  });

  it("lists ratings and lets you add yours", async () => {
    const puts = serve({ response_gap: null }, [theirs]);
    const user = userEvent.setup();
    renderWithProviders(<CallsPage />, { route: OPEN });
    const section = (await screen.findByRole("heading", { name: "Tester ratings" })).closest("section")!;
    expect(await within(section).findByText("Ravi")).toBeInTheDocument();
    expect(section).toHaveTextContent("overall 3/5");
    expect(section).toHaveTextContent("Listening 4 · Pacing and turn-taking 2");
    expect(section).toHaveTextContent("Talked over me while I gave my number.");

    await user.click(within(section).getByRole("button", { name: "Rate this call" }));
    const form = within(section).getByRole("form", { name: "Rate this call" });
    await user.click(within(within(form).getByRole("radiogroup", { name: "Flow and goal" })).getByRole("radio", { name: "5 of 5" }));
    await user.click(within(form).getByRole("button", { name: "Save rating" }));
    await waitFor(() => expect(puts).toEqual([{ ratings: { flow: 5 }, overall: null, remarks: "" }]));
  });
});
