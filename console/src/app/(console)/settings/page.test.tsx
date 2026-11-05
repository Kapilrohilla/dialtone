import userEvent from "@testing-library/user-event";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { me } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import ProfilePage from "./page";

function capturePatches() {
  const patches: unknown[] = [];
  server.use(
    http.patch("*/api/me", async ({ request }) => {
      const body = (await request.json()) as { name?: string; phone?: string; preferences?: object };
      patches.push(body);
      return HttpResponse.json({ ...me, ...body, preferences: { ...me.preferences, ...body.preferences } });
    }),
  );
  return patches;
}

describe("settings profile", () => {
  it("saves name, phone, time zone and notification switches in one PATCH", async () => {
    const patches = capturePatches();
    const user = userEvent.setup();
    renderWithProviders(<ProfilePage />, { route: "/settings" });
    const name = await screen.findByLabelText("Full name");
    await user.clear(name);
    await user.type(name, "Kapil R");
    const phone = screen.getByLabelText("Phone");
    await user.clear(phone);
    await user.type(phone, "+919810000002");
    await user.selectOptions(screen.getByLabelText("Time zone"), "Asia/Dubai");
    await user.click(screen.getByRole("switch", { name: "Email me when a call needs a person" }));
    await user.click(screen.getByRole("switch", { name: "Send a daily summary" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({
      name: "Kapil R",
      phone: "+919810000002",
      preferences: { time_zone: "Asia/Dubai", notify_needs_person: false, notify_daily_summary: true },
    });
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(screen.getByLabelText("Work email")).toHaveAttribute("readonly");
  });

  it("appearance previews instantly and Cancel restores it", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProfilePage />, { route: "/settings" });
    await screen.findByLabelText("Full name");
    await user.click(screen.getByRole("radio", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.cookie).toContain("cv_theme=dark");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(document.cookie).not.toContain("cv_theme=dark");
    expect(screen.getByRole("radio", { name: "Match system" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  it("saving an appearance updates the me cache so the sidebar toggle agrees", async () => {
    capturePatches();
    const user = userEvent.setup();
    const { queryClient } = renderWithProviders(<ProfilePage />, { route: "/settings" });
    await screen.findByLabelText("Full name");
    await user.click(screen.getByRole("radio", { name: "Dark" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect((queryClient.getQueryData(["me"]) as typeof me).preferences.appearance).toBe("dark"));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("change password shows the server's field error", async () => {
    server.use(http.post("*/api/me/password", () => HttpResponse.json({ current_password: ["Current password is incorrect."] }, { status: 400 })));
    const user = userEvent.setup();
    renderWithProviders(<ProfilePage />, { route: "/settings" });
    await user.click(await screen.findByRole("button", { name: "Change password" }));
    await user.type(screen.getByLabelText("Current password"), "wrong");
    await user.type(screen.getByLabelText("New password"), "a-long-new-pass-1");
    await user.type(screen.getByLabelText("Confirm new password"), "different");
    await user.click(screen.getAllByRole("button", { name: "Change password" })[1]);
    expect(await screen.findByText("The two passwords do not match.")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Confirm new password"));
    await user.type(screen.getByLabelText("Confirm new password"), "a-long-new-pass-1");
    await user.click(screen.getAllByRole("button", { name: "Change password" })[1]);
    expect(await screen.findByText("Current password is incorrect.")).toBeInTheDocument();
  });

  it("change password succeeds with a toast", async () => {
    let body: unknown;
    server.use(
      http.post("*/api/me/password", async ({ request }) => {
        body = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<ProfilePage />, { route: "/settings" });
    await user.click(await screen.findByRole("button", { name: "Change password" }));
    await user.type(screen.getByLabelText("Current password"), "old-pass");
    await user.type(screen.getByLabelText("New password"), "a-long-new-pass-1");
    await user.type(screen.getByLabelText("Confirm new password"), "a-long-new-pass-1");
    await user.click(screen.getAllByRole("button", { name: "Change password" })[1]);
    expect(await screen.findByText("Password changed.")).toBeInTheDocument();
    expect(body).toEqual({ current_password: "old-pass", new_password: "a-long-new-pass-1" });
    expect(screen.queryByLabelText("Current password")).not.toBeInTheDocument();
  });

  it("save is disabled until something changes", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProfilePage />, { route: "/settings" });
    const save = await screen.findByRole("button", { name: "Save changes" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("Full name"), "x");
    expect(save).toBeEnabled();
    await user.type(screen.getByLabelText("Full name"), "{Backspace}");
    expect(save).toBeDisabled();
  });
});
