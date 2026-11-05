import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { me } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import IntegrationsPage from "./page";

describe("integrations", () => {
  it("lists the eight coming-soon integrations", () => {
    renderWithProviders(<IntegrationsPage />, { route: "/integrations" });
    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(8);
    expect(within(rows[0]).getByText("Google Sheets")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Add each call as a row")).toBeInTheDocument();
    expect(within(rows[7]).getByText("Your own phone number (SIP)")).toBeInTheDocument();
    expect(screen.getAllByText("Coming soon")).toHaveLength(8);
    expect(screen.getByText("Connect your agents to the tools your team already uses. These are coming soon.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /connect/i })).not.toBeInTheDocument();
  });

  it("request posts tool and note", async () => {
    let body: unknown;
    server.use(
      http.get("*/api/me", () => HttpResponse.json({ ...me, role: "viewer" })),
      http.post("*/api/integrations/requests", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ id: 1 }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    const { queryClient } = renderWithProviders(<IntegrationsPage />, { route: "/integrations" });
    await waitFor(() => expect(queryClient.getQueryState(["me"])?.status ?? "none").not.toBe("pending"));
    // Any member may ask, viewers included.
    await user.click(screen.getByRole("button", { name: "Request an integration" }));
    const send = screen.getByRole("button", { name: "Send request" });
    expect(send).toBeDisabled();
    await user.type(screen.getByLabelText("Which tool?"), "Zoho CRM");
    await user.type(screen.getByLabelText("What should it do?"), "Create a lead per call");
    await user.click(send);
    expect(await screen.findByText("Request sent.")).toBeInTheDocument();
    expect(body).toEqual({ tool: "Zoho CRM", note: "Create a lead per call" });
    expect(screen.queryByLabelText("Which tool?")).not.toBeInTheDocument();
  });
});
