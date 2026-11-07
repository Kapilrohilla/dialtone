import userEvent from "@testing-library/user-event";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { Me, Role, Workspace } from "@/lib/types";
import { me } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import CallsSettingsPage from "./page";

/** `me` with `role`, and a PATCH /api/workspace that saves, or fails with `failure`. */
function serve(role: Role = "owner", failure?: string) {
  let workspace: Workspace = { ...me.workspace };
  const patches: unknown[] = [];
  server.use(
    http.get("*/api/me", () => HttpResponse.json({ ...me, role, workspace } satisfies Me)),
    http.patch("*/api/workspace", async ({ request }) => {
      const body = (await request.json()) as Partial<Workspace>;
      patches.push(body);
      if (failure) return HttpResponse.json({ detail: failure }, { status: 500 });
      workspace = { ...workspace, ...body };
      return HttpResponse.json(workspace);
    }),
  );
  return { patches };
}

const checkIn = () => screen.getByRole("switch", { name: "Check in when the caller goes quiet" });

describe("calls settings", () => {
  it("turns check-ins off for the whole account, straight away", async () => {
    const { patches } = serve("admin");
    const { queryClient } = renderWithProviders(<CallsSettingsPage />, { route: "/settings/calls" });
    expect(await screen.findByRole("heading", { name: "Silent callers" })).toBeInTheDocument();
    expect(checkIn()).toHaveAttribute("aria-checked", "true");
    await userEvent.setup().click(checkIn());
    expect(await screen.findByText("Check-ins are off for every agent from the next call.")).toBeInTheDocument();
    expect(patches).toEqual([{ dead_air_enabled: false }]);
    expect(checkIn()).toHaveAttribute("aria-checked", "false");
    expect(queryClient.getQueryData<Me>(["me"])?.workspace.dead_air_enabled).toBe(false);
  });

  it("puts the switch back and says why when saving fails", async () => {
    serve("owner", "Could not reach the server.");
    renderWithProviders(<CallsSettingsPage />, { route: "/settings/calls" });
    await screen.findByRole("heading", { name: "Silent callers" });
    await userEvent.setup().click(checkIn());
    expect(await screen.findByText("Could not reach the server.")).toBeInTheDocument();
    await waitFor(() => expect(checkIn()).toHaveAttribute("aria-checked", "true"));
  });

  it("editors and viewers see the switch but only owners and admins change it", async () => {
    serve("editor");
    renderWithProviders(<CallsSettingsPage />, { route: "/settings/calls" });
    await screen.findByRole("heading", { name: "Silent callers" });
    expect(checkIn()).toBeDisabled();
    expect(screen.getByText("Only owners and admins can change this.")).toBeInTheDocument();
  });
});
