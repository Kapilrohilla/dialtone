import userEvent from "@testing-library/user-event";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { liveCall, me } from "@/test/fixtures";
import { renderWithProviders, router } from "@/test/render";
import { server } from "@/test/server";
import { Shell } from "./Shell";

const open = (route = "/") => renderWithProviders(<Shell><p>Page body</p></Shell>, { route });

describe("shell", () => {
  it("shows the project, the workspace and the page, with no user avatar", async () => {
    open();
    expect(await screen.findByText("Page body")).toBeInTheDocument();
    expect(await screen.findByText("Northwind Voice")).toBeInTheDocument();
    expect(screen.getByText("NV")).toBeInTheDocument();
    expect(await screen.findByText("Northwind Car Rentals")).toBeInTheDocument();
    expect(screen.getByText("Soon")).toBeInTheDocument();
    expect(screen.queryByText("Kapil Rohilla")).not.toBeInTheDocument();
    expect(screen.queryByText("KR")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "User menu" })).not.toBeInTheDocument();
  });

  it("links to the docs and support in new tabs", async () => {
    open();
    const docs = await screen.findByRole("link", { name: "Documentation" });
    expect(docs).toHaveAttribute("href", "https://kapilrohilla.github.io/dialtone/docs/");
    expect(docs).toHaveAttribute("target", "_blank");
    const support = screen.getByRole("link", { name: "Support" });
    expect(support).toHaveAttribute("href", "https://github.com/Kapilrohilla/dialtone/issues");
    expect(support).toHaveAttribute("target", "_blank");
  });

  it("calls the project Dialtone while the name can't be loaded", async () => {
    server.use(http.get("*/api/instance/", () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
    const view = open();
    await waitFor(() => expect(view.queryClient.getQueryState(["instance"])?.status).toBe("error"));
    expect(screen.getByText("Dialtone")).toBeInTheDocument();
    expect(screen.getByText("D")).toBeInTheDocument();
  });

  it("sidebar shows the live count only when calls are live", async () => {
    server.use(http.get("*/api/live", () => HttpResponse.json([])));
    const first = open();
    const link = await screen.findByRole("link", { name: "Live calls" });
    await waitFor(() => expect(first.queryClient.getQueryState(["live"])?.status).toBe("success"));
    expect(link).toHaveTextContent(/^Live calls$/);
    first.unmount();

    server.use(http.get("*/api/live", () => HttpResponse.json([liveCall, { ...liveCall, room: "other" }])));
    open();
    expect(await screen.findByRole("link", { name: /^Live calls\s*2$/ })).toBeInTheDocument();
  });

  it("shows no live count when the request fails", async () => {
    server.use(http.get("*/api/live", () => HttpResponse.json({ detail: "Nope." }, { status: 500 })));
    const view = open();
    const link = await screen.findByRole("link", { name: "Live calls" });
    await waitFor(() => expect(view.queryClient.getQueryState(["live"])?.status).toBe("error"));
    expect(link).toHaveTextContent(/^Live calls$/);
  });

  it("marks the current page in the sidebar", async () => {
    open("/calls");
    expect(await screen.findByRole("link", { name: "Call history" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
  });

  it("theme toggle switches to dark and saves the preference", async () => {
    let body: unknown;
    server.use(http.patch("*/api/me", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ ...me, preferences: { ...me.preferences, appearance: "dark" } });
    }));
    const user = userEvent.setup();
    open();
    const toggle = await screen.findByRole("switch", { name: "Dark mode" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await user.click(toggle);
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.cookie).toContain("cv_theme=dark");
    await waitFor(() => expect(body).toEqual({ preferences: { appearance: "dark" } }));
    await waitFor(() => expect(screen.getByRole("switch", { name: "Dark mode" })).toHaveAttribute("aria-checked", "true"));
  });

  it("syncs the theme cookie from the saved preference", async () => {
    server.use(http.get("*/api/me", () => HttpResponse.json({ ...me, preferences: { ...me.preferences, appearance: "dark" } })));
    open();
    await screen.findByText("Page body");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("logs out from the sidebar", async () => {
    let called = false;
    server.use(http.post("*/api/auth/logout", () => {
      called = true;
      return new HttpResponse(null, { status: 204 });
    }));
    const user = userEvent.setup();
    open();
    await user.click(await screen.findByRole("button", { name: "Log out" }));
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/sign-in"));
    expect(called).toBe(true);
  });

  it("says so when signing out fails", async () => {
    server.use(http.post("*/api/auth/logout", () => HttpResponse.json({ detail: "Server unavailable." }, { status: 503 })));
    const user = userEvent.setup();
    open();
    await user.click(await screen.findByRole("button", { name: "Log out" }));
    expect(await screen.findByText("Server unavailable.")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("never leaves the page when the sidebar's live poll finds the user signed out", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/agents/3", search: "", origin: "http://localhost:3000", href: "http://localhost:3000/agents/3", assign });
    server.use(http.get("*/api/live", () => HttpResponse.json({ detail: "Authentication credentials were not provided." }, { status: 403 })));
    const view = open("/agents/3");
    await waitFor(() => expect(view.queryClient.getQueryState(["live"])?.status).toBe("error"));
    expect(assign).not.toHaveBeenCalled();
  });

  it("offers a retry when me fails to load", async () => {
    server.use(http.get("*/api/me", () => HttpResponse.json({ detail: "Bad request." }, { status: 400 })));
    open();
    expect(await screen.findByRole("alert")).toHaveTextContent("Bad request.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("renders no Google button", async () => {
    open();
    await screen.findByText("Page body");
    expect(screen.queryByText(/google/i)).toBeNull();
  });
});
