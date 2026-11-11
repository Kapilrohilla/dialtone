import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { dashboard, me } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import DashboardPage from "./page";

const serve = (body: object, status = 200) => server.use(http.get("*/api/dashboard", () => HttpResponse.json(body, { status })));

describe("dashboard", () => {
  it("shows the four readings with dashes for missing values", async () => {
    serve({ ...dashboard, connected_pct: null, avg_duration_s: null });
    renderWithProviders(<DashboardPage />);
    await screen.findByText("18");
    const readings = screen.getByLabelText("Today in numbers");
    const text = (label: string) => within(readings).getByText(label).nextElementSibling?.textContent;
    expect(within(readings).getByText("Calls today")).toBeInTheDocument();
    expect(text("Calls today")).toBe("18");
    expect(text("Connected")).toBe("—");
    expect(text("Interested")).toBe("5");
    expect(text("Average call")).toBe("—");
    expect(screen.getByRole("link", { name: "Open live calls" })).toHaveAttribute("href", "/live");
  });

  it("shows connected percent and average call when known", async () => {
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("72%")).toBeInTheDocument();
    expect(screen.getByText("2:14")).toBeInTheDocument();
    expect(screen.getAllByText("+91 80 4718 2290").length).toBeGreaterThan(0);
    expect(screen.getByText("Asked to talk to a person.")).toBeInTheDocument();
  });

  it("call back marks the call handled and offers undo", async () => {
    const posts: unknown[] = [];
    let handled = false;
    server.use(
      http.get("*/api/dashboard", () => HttpResponse.json({ ...dashboard, needs_person: handled ? [] : dashboard.needs_person })),
      http.post("*/api/calls/:room/needs-person", async ({ request, params }) => {
        const body = (await request.json()) as { handled: boolean };
        handled = body.handled;
        posts.push({ room: params.room, body });
        return HttpResponse.json({ detail: "ok" });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<DashboardPage />);
    await user.click(await screen.findByRole("button", { name: "Call back" }));
    expect(await screen.findByText("Marked as handled.")).toBeInTheDocument();
    expect(screen.queryByText("Asked to talk to a person.")).not.toBeInTheDocument();
    expect(posts).toEqual([{ room: "call-1c0d", body: { handled: true } }]);

    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1]).toEqual({ room: "call-1c0d", body: { handled: false } });
  });

  it("hides call back for viewers", async () => {
    server.use(http.get("*/api/me", () => HttpResponse.json({ ...me, role: "viewer" })));
    const view = renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("Asked to talk to a person.")).toBeInTheDocument();
    await waitFor(() => expect(view.queryClient.getQueryState(["me"])?.status).toBe("success"));
    expect(screen.queryByRole("button", { name: "Call back" })).not.toBeInTheDocument();
  });

  it("toasts each call back and an error when undo fails", async () => {
    server.use(
      http.get("*/api/dashboard", () => HttpResponse.json({ ...dashboard, needs_person: [dashboard.needs_person[0], { ...dashboard.needs_person[0], room: "call-2" }] })),
      http.post("*/api/calls/:room/needs-person", async ({ request }) => {
        const { handled } = (await request.json()) as { handled: boolean };
        return handled ? HttpResponse.json({ detail: "ok" }) : HttpResponse.json({ detail: "Could not undo that." }, { status: 500 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<DashboardPage />);
    await user.click((await screen.findAllByRole("button", { name: "Call back" }))[0]);
    await user.click((await screen.findAllByRole("button", { name: "Call back" }))[0]);
    await waitFor(() => expect(screen.getAllByText("Marked as handled.")).toHaveLength(2));
    await user.click(screen.getAllByRole("button", { name: "Undo" })[0]);
    expect(await screen.findByText("Could not undo that.")).toBeInTheDocument();
  });

  it("shows the empty states", async () => {
    serve({
      ...dashboard,
      needs_person: [],
      outcomes_week: dashboard.outcomes_week.map((o) => ({ ...o, count: 0 })),
    });
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("No one is waiting for a call back.")).toBeInTheDocument();
    expect(screen.getByText("No calls this week yet.")).toBeInTheDocument();
  });

  it("shows an empty reason in muted words", async () => {
    serve({ ...dashboard, needs_person: [{ ...dashboard.needs_person[0], reason: "" }] });
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("No reason given")).toBeInTheDocument();
  });

  it("draws outcome bars in proportion to the largest count", async () => {
    renderWithProviders(<DashboardPage />);
    await screen.findByText("Outcomes this week");
    const bar = (o: string) => document.querySelector<HTMLElement>(`[data-outcome="${o}"]`)!;
    await waitFor(() => expect(bar("Not interested")).not.toBeNull());
    expect(bar("Not interested").style.width).toBe("100%");
    expect(bar("Interested").style.width).toBe("70%");
    expect(bar("Interested").style.background).toBe("var(--blue)");
    expect(bar("Dropped").style.background).toBe("var(--rule-strong)");
  });

  it("shows the live agent line, or how to publish one", async () => {
    serve({ ...dashboard, live_agent: { id: 1, name: "Maya", phone_number: "+918047182290" } });
    const first = renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("Maya")).toBeInTheDocument();
    expect(screen.getByText("Live")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Manage agents" })).toHaveAttribute("href", "/agents");
    first.unmount();

    serve({ ...dashboard, live_agent: null });
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("No agent is answering calls.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Publish an agent" })).toHaveAttribute("href", "/agents");
  });

  it("shows no live agent line when none is published", async () => {
    serve({ ...dashboard, live_agent: null });
    renderWithProviders(<DashboardPage />);
    await screen.findByText("No agent is answering calls.");
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("shows an error with retry", async () => {
    serve({ detail: "Dashboard is down." }, 500);
    const user = userEvent.setup();
    renderWithProviders(<DashboardPage />);
    expect(await screen.findByText("Dashboard is down.")).toBeInTheDocument();
    serve(dashboard);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("72%")).toBeInTheDocument();
  });
});
