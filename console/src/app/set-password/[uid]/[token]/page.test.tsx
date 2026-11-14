import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { setParams } from "@/test/navigation";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import SetPasswordPage from "./page";

async function fill(a: string, b: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("New password"), a);
  await user.type(screen.getByLabelText("Confirm password"), b);
  await user.click(screen.getByRole("button", { name: "Set password" }));
}

function open() {
  setParams({ uid: "Mw", token: "abc" });
  renderWithProviders(<SetPasswordPage />, { route: "/set-password/Mw/abc" });
}

describe("set password", () => {
  it("posts uid and token from the URL", async () => {
    let body: unknown;
    server.use(http.post("*/api/auth/set-password", async ({ request }) => {
      body = await request.json();
      return new HttpResponse(null, { status: 204 });
    }));
    open();
    await fill("a-long-passphrase", "a-long-passphrase");
    expect(await screen.findByText("Password set.")).toBeInTheDocument();
    expect(body).toEqual({ uid: "Mw", token: "abc", new_password: "a-long-passphrase" });
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in");
  });

  it("shows the invalid-link message", async () => {
    server.use(http.post("*/api/auth/set-password", () => HttpResponse.json({ detail: "This link is invalid or has expired." }, { status: 400 })));
    open();
    await fill("a-long-passphrase", "a-long-passphrase");
    expect(await screen.findByRole("alert")).toHaveTextContent("This link is invalid or has expired.");
  });

  it("shows the first password error", async () => {
    server.use(http.post("*/api/auth/set-password", () => HttpResponse.json({ new_password: ["This password is too short."] }, { status: 400 })));
    open();
    await fill("short", "short");
    expect(await screen.findByRole("alert")).toHaveTextContent("This password is too short.");
  });

  it("does not post when the two passwords differ", async () => {
    open();
    await fill("one-passphrase", "other-passphrase");
    expect(await screen.findByRole("alert")).toHaveTextContent("The two passwords do not match.");
  });

  it("shows the install's project name", async () => {
    open();
    expect(await screen.findByText("Northwind Voice")).toBeInTheDocument();
  });
});
