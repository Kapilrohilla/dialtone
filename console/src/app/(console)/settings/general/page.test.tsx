import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import type { Instance } from "@/lib/types";
import { Shell } from "@/components/shell/Shell";
import { retitle } from "@/lib/queries";
import type { Me } from "@/lib/types";
import { instance, me } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import { SettingsNav } from "../_components/SettingsNav";
import GeneralSettingsPage from "./page";

const superuser: Me = { ...me, is_superuser: true };

/** `me` as `who`, and PATCH /api/instance/ plus POST / DELETE /api/instance/logo that save, or answer `failure`. */
function serve(who: Me = superuser, failure?: { status: number; body: object }, logoFailure?: { status: number; body: object }) {
  const patches: unknown[] = [];
  const uploads: File[] = [];
  let deletes = 0;
  let saved: Instance = { ...instance };
  server.use(
    http.get("*/api/me", () => HttpResponse.json(who)),
    http.patch("*/api/instance/", async ({ request }) => {
      const body = (await request.json()) as Partial<Instance>;
      patches.push(body);
      if (failure) return HttpResponse.json(failure.body, { status: failure.status });
      saved = { ...saved, ...body };
      return HttpResponse.json(saved);
    }),
    http.post("*/api/instance/logo", async ({ request }) => {
      uploads.push((await request.formData()).get("file") as File);
      if (logoFailure) return HttpResponse.json(logoFailure.body, { status: logoFailure.status });
      saved = { ...saved, logo_url: `/api/instance/logo?v=v${uploads.length}` };
      return HttpResponse.json(saved);
    }),
    http.delete("*/api/instance/logo", () => {
      deletes += 1;
      saved = { ...saved, logo_url: null };
      return HttpResponse.json(saved);
    }),
  );
  return { patches, uploads, deletes: () => deletes };
}

const png = (name = "logo.png", size = 100, type = "image/png") => new File([new Uint8Array(size)], name, { type });

const open = () => renderWithProviders(<GeneralSettingsPage />, { route: "/settings/general" });

afterEach(() => {
  document.title = "";
  delete document.documentElement.dataset.palette;
  document.head.querySelectorAll('link[rel="icon"]').forEach((l) => l.remove());
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
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByLabelText("Logo file")).toBeNull();
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
    expect(view.queryClient.getQueryData(["instance"])).toEqual({ ...instance, project_name: "Acme Voice" });
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

describe("settings general: theme", () => {
  it("shows the three themes with the saved one picked", async () => {
    serve();
    server.use(http.get("*/api/instance/", () => HttpResponse.json({ ...instance, theme: "forest" })));
    open();
    const group = await screen.findByRole("radiogroup", { name: "Theme" });
    const radios = within(group).getAllByRole("radio");
    expect(radios.map((r) => (r as HTMLInputElement).value)).toEqual(["saffron", "ocean", "forest"]);
    expect(within(group).getByRole("radio", { name: "Forest" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  it("applies the theme only after Save: one PATCH with just the theme", async () => {
    const { patches } = serve();
    const user = userEvent.setup();
    const view = open();
    await user.click(await screen.findByRole("radio", { name: "Ocean" }));
    expect(screen.getByRole("radio", { name: "Ocean" })).toBeChecked();
    expect(document.documentElement.dataset.palette).toBeUndefined();

    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(patches).toEqual([{ theme: "ocean" }]));
    await waitFor(() => expect(document.documentElement.dataset.palette).toBe("ocean"));
    expect(view.queryClient.getQueryData(["instance"])).toEqual({ ...instance, theme: "ocean" });
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  it("picking the saved theme again is not a change", async () => {
    serve();
    const user = userEvent.setup();
    open();
    await user.click(await screen.findByRole("radio", { name: "Forest" }));
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
    await user.click(screen.getByRole("radio", { name: "Saffron" }));
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  it("sends the name and the theme in one PATCH", async () => {
    const { patches } = serve();
    const user = userEvent.setup();
    open();
    const field = await screen.findByLabelText("Project name");
    await user.clear(field);
    await user.type(field, "Acme");
    await user.click(screen.getByRole("radio", { name: "Forest" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(patches).toEqual([{ project_name: "Acme", theme: "forest" }]));
  });
});

describe("settings general: logo", () => {
  it("uploads the picked logo on Save; the sidebar and the tab icon follow", async () => {
    const { uploads, patches } = serve();
    const user = userEvent.setup();
    renderWithProviders(
      <Shell>
        <GeneralSettingsPage />
      </Shell>,
      { route: "/settings/general" },
    );
    const sidebar = await screen.findByRole("complementary");
    expect(await within(sidebar).findByText("NV")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload logo" })).toBeInTheDocument();

    await user.upload(await screen.findByLabelText("Logo file"), png());
    expect(await screen.findByAltText("Logo preview")).toHaveAttribute("src", expect.stringMatching(/^data:image\/png;base64,/));
    expect(uploads).toEqual([]); // not before Save

    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(uploads).toHaveLength(1));
    expect(uploads[0].size).toBe(100);
    expect(patches).toEqual([]);
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    await waitFor(() => expect(sidebar.querySelector("img")).toHaveAttribute("src", "/api/instance/logo?v=v1"));
    expect(within(sidebar).queryByText("NV")).toBeNull();
    expect(document.head.querySelector('link[rel="icon"]')).toHaveAttribute("href", "/api/instance/logo?v=v1");
    expect(screen.getByAltText("Logo preview")).toHaveAttribute("src", "/api/instance/logo?v=v1");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  it("removes the logo on Save: back to the initials tile and favicon.ico", async () => {
    const { deletes } = serve();
    server.use(http.get("*/api/instance/", () => HttpResponse.json({ ...instance, logo_url: "/api/instance/logo?v=old" })));
    const user = userEvent.setup();
    renderWithProviders(
      <Shell>
        <GeneralSettingsPage />
      </Shell>,
      { route: "/settings/general" },
    );
    const sidebar = await screen.findByRole("complementary");
    expect(await screen.findByAltText("Logo preview")).toHaveAttribute("src", "/api/instance/logo?v=old");
    await waitFor(() => expect(sidebar.querySelector("img")).toHaveAttribute("src", "/api/instance/logo?v=old"));

    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(screen.queryByAltText("Logo preview")).toBeNull();
    expect(deletes()).toBe(0);
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(deletes()).toBe(1));
    expect(await within(sidebar).findByText("NV")).toBeInTheDocument();
    expect(sidebar.querySelector("img")).toBeNull();
    expect(document.head.querySelector('link[rel="icon"]')).toHaveAttribute("href", "/favicon.ico");
  });

  it("removing a logo that was only picked just forgets it", async () => {
    const { uploads, deletes } = serve();
    const user = userEvent.setup();
    open();
    await user.upload(await screen.findByLabelText("Logo file"), png());
    await user.click(await screen.findByRole("button", { name: "Remove" }));
    expect(screen.queryByAltText("Logo preview")).toBeNull();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(uploads).toEqual([]);
    expect(deletes()).toBe(0);
  });

  it.each([
    ["a GIF", png("logo.gif", 100, "image/gif"), "Upload a PNG, SVG or JPG."],
    ["a file over 1 MB", png("logo.png", 1024 * 1024 + 1), "The logo is too large; the limit is 1 MB."],
  ])("won't take %s", async (_, file, message) => {
    const { uploads } = serve();
    const user = userEvent.setup({ applyAccept: false });
    open();
    await user.upload(await screen.findByLabelText("Logo file"), file);
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByAltText("Logo preview")).toBeNull();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(uploads).toEqual([]);
  });

  it("shows the server's file error under the logo", async () => {
    serve(superuser, undefined, { status: 400, body: { file: ["The logo must be square; this one is 64 x 32."] } });
    const user = userEvent.setup();
    open();
    await user.upload(await screen.findByLabelText("Logo file"), png());
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The logo must be square; this one is 64 x 32.");
    expect(screen.queryByText("Saved.")).toBeNull();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
  });
});

describe("retitle", () => {
  it("swaps the name in the title suffix or the whole title", () => {
    expect(retitle("Agents - Old", "Old", "New")).toBe("Agents - New");
    expect(retitle("Old", "Old", "New")).toBe("New");
    expect(retitle("Dialtone", "Old", "New")).toBe("New");
  });
});
