import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Me, Role, TeamMember } from "@/lib/types";
import { me } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import TeamPage from "./page";

const members: TeamMember[] = [
  { id: 1, name: "Kapil Rohilla", email: "kapil@carrum.example", role: "owner", last_login: "2026-11-05T09:00:00Z" },
  { id: 2, name: "Asha Rao", email: "asha@carrum.example", role: "editor", last_login: null },
];

function serve(role: Role, extra: Partial<Me> = {}) {
  server.use(
    http.get("*/api/me", () => HttpResponse.json({ ...me, role, id: role === "owner" ? 1 : 9, ...extra })),
    http.get("*/api/team", () => HttpResponse.json(members)),
  );
}

/** Absence assertions mean nothing until the role has arrived. */
async function loaded(queryClient: { getQueryState: (key: readonly string[]) => { status: string } | undefined }) {
  await screen.findByText("Asha Rao");
  await waitFor(() => expect(queryClient.getQueryState(["me"])?.status).toBe("success"));
}

afterEach(() => vi.unstubAllGlobals());

describe("team", () => {
  it("lists members with last sign-in and Never", async () => {
    serve("viewer");
    const qc = renderWithProviders(<TeamPage />, { route: "/settings/team" });
    await loaded(qc.queryClient);
    expect(screen.getByText("Never")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByText("Editor")).toBeInTheDocument();
  });

  it("owner sees Owner in the role picker, admin doesn't", async () => {
    serve("owner");
    const first = renderWithProviders(<TeamPage />, { route: "/settings/team" });
    await loaded(first.queryClient);
    const picker = screen.getByLabelText("Role for Asha Rao");
    expect(within(picker).getByRole("option", { name: "Owner" })).toBeInTheDocument();
    // You can't change your own role.
    expect(screen.queryByLabelText("Role for Kapil Rohilla")).not.toBeInTheDocument();
    first.unmount();

    serve("admin");
    const second = renderWithProviders(<TeamPage />, { route: "/settings/team" });
    await loaded(second.queryClient);
    const adminPicker = screen.getByLabelText("Role for Asha Rao");
    expect(within(adminPicker).queryByRole("option", { name: "Owner" })).not.toBeInTheDocument();
    expect(within(adminPicker).getByRole("option", { name: "Admin" })).toBeInTheDocument();
    // An owner's role is plain text for an admin.
    expect(screen.queryByLabelText("Role for Kapil Rohilla")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Invite someone" })).toBeInTheDocument();
  });

  it("invite shows the full set-password link", async () => {
    serve("owner");
    let body: unknown;
    server.use(
      http.post("*/api/team", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ set_password_url: "/set-password/Mw/abc-123" }, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
    renderWithProviders(<TeamPage />, { route: "/settings/team" });
    await user.click(await screen.findByRole("button", { name: "Invite someone" }));
    await user.type(screen.getByLabelText("Name"), "Ravi Kumar");
    await user.type(screen.getByLabelText("Work email"), "ravi@carrum.example");
    await user.selectOptions(screen.getByLabelText("Role"), "viewer");
    await user.click(screen.getByRole("button", { name: "Create link" }));
    const link = await screen.findByLabelText("Set-password link");
    expect(link).toHaveValue(`${location.origin}/set-password/Mw/abc-123`);
    expect(body).toEqual({ name: "Ravi Kumar", email: "ravi@carrum.example", role: "viewer" });
    expect(screen.getByText("Send this link to Ravi Kumar. It works once.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy link" }));
    expect(writeText).toHaveBeenCalledWith(`${location.origin}/set-password/Mw/abc-123`);
    expect(await screen.findByText("Link copied.")).toBeInTheDocument();
  });

  it("copy link says so when the clipboard is missing", async () => {
    serve("owner");
    server.use(http.post("*/api/team", () => HttpResponse.json({ set_password_url: "/set-password/Mw/abc" }, { status: 201 })));
    const user = userEvent.setup();
    vi.stubGlobal("navigator", { userAgent: "test" });
    renderWithProviders(<TeamPage />, { route: "/settings/team" });
    await user.click(await screen.findByRole("button", { name: "Invite someone" }));
    await user.type(screen.getByLabelText("Name"), "Ravi");
    await user.type(screen.getByLabelText("Work email"), "ravi@carrum.example");
    await user.click(screen.getByRole("button", { name: "Create link" }));
    await user.click(await screen.findByRole("button", { name: "Copy link" }));
    expect(await screen.findByText("Couldn't copy. Select the link and copy it.")).toBeInTheDocument();
  });

  it("invite shows the server's email error under the field", async () => {
    serve("admin");
    server.use(http.post("*/api/team", () => HttpResponse.json({ email: ["A user with this email already exists."] }, { status: 400 })));
    const user = userEvent.setup();
    renderWithProviders(<TeamPage />, { route: "/settings/team" });
    await user.click(await screen.findByRole("button", { name: "Invite someone" }));
    await user.type(screen.getByLabelText("Name"), "Ravi");
    await user.type(screen.getByLabelText("Work email"), "asha@carrum.example");
    await user.click(screen.getByRole("button", { name: "Create link" }));
    expect(await screen.findByText("A user with this email already exists.")).toBeInTheDocument();
  });

  it("editor sees no invite button", async () => {
    serve("editor");
    const qc = renderWithProviders(<TeamPage />, { route: "/settings/team" });
    await loaded(qc.queryClient);
    expect(screen.queryByRole("button", { name: "Invite someone" })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("role change shows the owner-only error", async () => {
    serve("admin");
    server.use(http.patch("*/api/team/:id", () => HttpResponse.json({ detail: "Only an owner can do that." }, { status: 403 })));
    const user = userEvent.setup();
    renderWithProviders(<TeamPage />, { route: "/settings/team" });
    await user.selectOptions(await screen.findByLabelText("Role for Asha Rao"), "admin");
    expect(await screen.findByText("Only an owner can do that.")).toBeInTheDocument();
    expect(screen.getByLabelText("Role for Asha Rao")).toHaveValue("editor");
  });
});
