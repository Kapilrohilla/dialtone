import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { AgentListItem, DispositionListRow } from "@/lib/types";
import { agentListItem, dispositionList, dispositionListRow, me } from "@/test/fixtures";
import { renderWithProviders, router } from "@/test/render";
import { server } from "@/test/server";
import DispositionsPage from "./page";

const unused: DispositionListRow = { ...dispositionListRow, id: 6, name: "Insurance renewals", items: dispositionListRow.items.slice(0, 7), used_by: [] };
const survey: AgentListItem = { ...agentListItem, id: 8, name: "Survey agent", status: "draft", disposition_list: null };
const archived: AgentListItem = { ...agentListItem, id: 9, name: "Old pilot", status: "archived", disposition_list: null };

const rowOf = (name: string) => screen.getByRole("link", { name }).closest("tr")!;

describe("dispositions lists", () => {
  it("lists each list with its size, agents and a Not used chip", async () => {
    server.use(http.get("*/api/dispositions", () => HttpResponse.json([dispositionListRow, unused])));
    renderWithProviders(<DispositionsPage />, { route: "/dispositions" });
    expect(await screen.findByRole("link", { name: "Driver hiring" })).toHaveAttribute("href", "/dispositions/5");
    expect(within(rowOf("Driver hiring")).getByText("14 dispositions")).toBeInTheDocument();
    expect(within(rowOf("Driver hiring")).getByText(agentListItem.name)).toBeInTheDocument();
    expect(within(rowOf("Insurance renewals")).getByText("7 dispositions")).toBeInTheDocument();
    expect(within(rowOf("Insurance renewals")).getByText("Not used")).toBeInTheDocument();
    expect(screen.getByText(/A disposition list is the set of outcomes/)).toBeInTheDocument();
  });

  it("names the agents that have no list, leaving archived ones out", async () => {
    server.use(http.get("*/api/agents", () => HttpResponse.json([agentListItem, survey, archived])));
    renderWithProviders(<DispositionsPage />, { route: "/dispositions" });
    const callout = await screen.findByRole("complementary", { name: "Agents without a list" });
    expect(callout).toHaveTextContent("1 agent doesn't record dispositions: Survey agent.");
    expect(within(callout).getByRole("link", { name: "Attach a list →" })).toHaveAttribute("href", "/agents");
  });

  it("hides the callout when every agent has a list", async () => {
    renderWithProviders(<DispositionsPage />, { route: "/dispositions" });
    await screen.findByRole("link", { name: "Driver hiring" });
    expect(screen.queryByRole("complementary", { name: "Agents without a list" })).not.toBeInTheDocument();
  });

  it("New list creates a one-item list and opens it", async () => {
    let body: unknown;
    server.use(
      http.post("*/api/dispositions", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ...dispositionList, id: 12, name: "New list" }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<DispositionsPage />, { route: "/dispositions" });
    await user.click(await screen.findByRole("button", { name: "New list" }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/dispositions/12"));
    expect(body).toEqual({
      name: "New list",
      items: [{ code: "UNRESOLVED", name: "No clear outcome", description: "Use when the outcome is unclear. Don't guess.", group: "Dropped", fields: [] }],
      fallback_code: "UNRESOLVED",
    });
  });

  it("says why a list in use can't be deleted", async () => {
    server.use(http.delete("*/api/dispositions/5", () => HttpResponse.json({ detail: "Detach this list from Driver lead qualifier first." }, { status: 409 })));
    const user = userEvent.setup();
    renderWithProviders(<DispositionsPage />, { route: "/dispositions" });
    await screen.findByRole("link", { name: "Driver hiring" });
    await user.click(within(rowOf("Driver hiring")).getByRole("button", { name: "More actions for Driver hiring" }));
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete Driver hiring?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete list" }));
    expect(await screen.findByText("Detach this list from Driver lead qualifier first.")).toBeInTheDocument();
  });

  it("viewers see the lists without New list or row actions", async () => {
    server.use(http.get("*/api/me", () => HttpResponse.json({ ...me, role: "viewer" })));
    renderWithProviders(<DispositionsPage />, { route: "/dispositions" });
    await screen.findByRole("link", { name: "Driver hiring" });
    expect(screen.queryByRole("button", { name: "New list" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /More actions/ })).not.toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    server.use(http.get("*/api/dispositions", () => HttpResponse.json([])));
    renderWithProviders(<DispositionsPage />, { route: "/dispositions" });
    expect(await screen.findByText("No disposition lists yet")).toBeInTheDocument();
  });
});
