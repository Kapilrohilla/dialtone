import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { NUMBER } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import PhoneNumbersPage from "./page";

describe("phone numbers", () => {
  it("lists numbers with their agent and the empty state", async () => {
    server.use(
      http.get("*/api/phone-numbers", () =>
        HttpResponse.json([
          { number: NUMBER, trunk_name: "Northwind inbound", agent_name: "Driver lead qualifier" },
          { number: "+918047182291", trunk_name: "Spare line", agent_name: null },
        ]),
      ),
    );
    const first = renderWithProviders(<PhoneNumbersPage />, { route: "/settings/phone-numbers" });
    expect(await screen.findByText(NUMBER)).toBeInTheDocument();
    expect(screen.getByText("Northwind inbound")).toBeInTheDocument();
    expect(screen.getByText("Driver lead qualifier")).toBeInTheDocument();
    expect(screen.getByText("No agent")).toBeInTheDocument();
    expect(screen.getByText("Numbers are set up by your admin.")).toBeInTheDocument();
    first.unmount();

    server.use(http.get("*/api/phone-numbers", () => HttpResponse.json([])));
    renderWithProviders(<PhoneNumbersPage />, { route: "/settings/phone-numbers" });
    expect(await screen.findByText("No numbers found on the call server.")).toBeInTheDocument();
  });

  it("says when the call server can't be reached", async () => {
    server.use(http.get("*/api/phone-numbers", () => HttpResponse.json({ detail: "boom" }, { status: 502 })));
    renderWithProviders(<PhoneNumbersPage />, { route: "/settings/phone-numbers" });
    expect(await screen.findByText("Couldn't reach the call server.")).toBeInTheDocument();
  });
});
