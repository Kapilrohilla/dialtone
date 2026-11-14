import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { Shell } from "@/components/shell/Shell";
import { retitle } from "@/lib/queries";
import type { Me } from "@/lib/types";
import { instance, me } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import { SettingsNav } from "../_components/SettingsNav";
import GeneralSettingsPage from "./page";

const superuser: Me = { ...me, is_superuser: true };

/** `me` as `who`, and a PATCH /api/instance/ that saves, or answers `failure`. */
function serve(who: Me = superuser, failure?: { status: number; body: object }) {
  const patches: unknown[] = [];
  server.use(
    http.get("*/api/me", () => HttpResponse.json(who)),
    http.patch("*/api/instance/", async ({ request }) => {
      const body = (await request.json()) as { project_name: string };
      patches.push(body);
      if (failure) return HttpResponse.json(failure.body, { status: failure.status });
      return HttpResponse.json({ project_name: body.project_name });
    }),
  );
  return { patches };
}

const open = () => renderWithProviders(<GeneralSettingsPage />, { route: "/settings/general" });

afterEach(() => {
  document.title = "";
});

describe("settings nav", () => {
  it("lists General for a superuser", async () => {
    serve();
    renderWithProviders(<SettingsNav />, { route: "/settings/general" });
    const nav = screen.getByRole("navigation", { name: "Settings" });
    expect(await within(nav).findByRole("link", { name: "General" })).toHaveAttribute("aria-current", "page");
  });

  it("hides General from everyone else", async () => {
    serve(me);
    const view = renderWithProviders(<SettingsNav />, { route: "/settings" });
    await waitFor(() => expect(view.queryClient.getQueryState(["me"])?.status).toBe("success"));
    expect(screen.getByRole("link", { name: "Team" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "General" })).toBeNull();
  });
});

describe("settings general", () => {
  it("tells a non-superuser they can't change it, with no form", async () => {
    serve(me);
    open();
    expect(await screen.findByText("You can't change these settings.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Project name")).toBeNull();
  });

  it("renames the install: one PATCH, then the sidebar and the tab title follow", async () => {
    const { patches } = serve();
    document.title = "Northwind Voice";
    const user = userEvent.setup();
    const view = renderWithProviders(
      <Shell>
        <GeneralSettingsPage />
      </Shell>,
      { route: "/settings/general" },
    );
    const field = await screen.findByLabelText("Project name");
    expect(field).toHaveValue(instance.project_name);
    expect(field).toHaveAttribute("maxLength", "60");
    const sidebar = screen.getByRole("complementary");
    expect(within(sidebar).getByText("Northwind Voice")).toBeInTheDocument();

    await user.clear(field);
    await user.type(field, "  Acme Voice  ");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(patches).toEqual([{ project_name: "Acme Voice" }]));
    expect(await within(sidebar).findByText("Acme Voice")).toBeInTheDocument();
    expect(view.queryClient.getQueryData(["instance"])).toEqual({ project_name: "Acme Voice" });
    expect(document.title).toBe("Acme Voice");
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(screen.getByLabelText("Project name")).toHaveValue("Acme Voice");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  it("won't send a blank name", async () => {
    const { patches } = serve();
    const user = userEvent.setup();
    open();
    const field = await screen.findByLabelText("Project name");
    await user.clear(field);
    await user.type(field, "   ");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Enter a project name.")).toBeInTheDocument();
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(patches).toEqual([]);
  });

  it("shows the server's field error under the field", async () => {
    serve(superuser, { status: 400, body: { project_name: ["Ensure this field has no more than 60 characters."] } });
    const user = userEvent.setup();
    open();
    const field = await screen.findByLabelText("Project name");
    await user.type(field, " 2");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Ensure this field has no more than 60 characters.")).toBeInTheDocument();
    expect(field).toHaveAttribute("aria-invalid", "true");
  });

  it("says so when the server refuses", async () => {
    serve(superuser, { status: 403, body: { detail: "You do not have permission to perform this action." } });
    const user = userEvent.setup();
    open();
    await user.type(await screen.findByLabelText("Project name"), " 2");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("You do not have permission to perform this action.")).toBeInTheDocument();
  });
});

describe("retitle", () => {
  it("swaps the name in the title suffix or the whole title", () => {
    expect(retitle("Agents - Old", "Old", "New")).toBe("Agents - New");
    expect(retitle("Old", "Old", "New")).toBe("New");
    expect(retitle("Dialtone", "Old", "New")).toBe("New");
  });
});
