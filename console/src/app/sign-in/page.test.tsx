import userEvent from "@testing-library/user-event";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { me } from "@/test/fixtures";
import { renderWithProviders, router } from "@/test/render";
import { server } from "@/test/server";
import SignInPage from "./page";

async function signIn(route = "/sign-in") {
  const user = userEvent.setup();
  const view = renderWithProviders(<SignInPage />, { route });
  await user.type(await screen.findByLabelText("Work email"), "kapil@carrum.example");
  await user.type(screen.getByLabelText("Password"), "pw12345678");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  return view;
}

describe("sign in", () => {
  it("signs in and goes to the next page", async () => {
    let body: unknown;
    server.use(http.post("*/api/auth/login", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ ...me, preferences: { ...me.preferences, appearance: "dark" } });
    }));
    const { queryClient } = await signIn("/sign-in?next=/agents");
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/agents"));
    expect(body).toEqual({ email: "kapil@carrum.example", password: "pw12345678" });
    expect(queryClient.getQueryData(["me"])).toMatchObject({ email: me.email });
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.cookie).toContain("cv_theme=dark");
  });

  it("refuses an off-site next", async () => {
    server.use(http.post("*/api/auth/login", () => HttpResponse.json(me)));
    await signIn("/sign-in?next=//evil.example");
    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/"));
  });

  it("shows the API's wrong-password message", async () => {
    server.use(http.post("*/api/auth/login", () => HttpResponse.json({ detail: "Wrong email or password." }, { status: 400 })));
    await signIn();
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong email or password.");
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("shows the throttle message on 429", async () => {
    server.use(http.post("*/api/auth/login", () => HttpResponse.json({ detail: "Request was throttled." }, { status: 429 })));
    await signIn();
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts. Wait a minute and try again.");
  });

  it("explains the invite route under Forgot password", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SignInPage />, { route: "/sign-in" });
    await user.click(await screen.findByRole("button", { name: "Forgot password?" }));
    expect(screen.getByText("Ask your workspace admin for a new invite link.")).toBeInTheDocument();
  });

  it("toggles password visibility and renders no Google button", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SignInPage />, { route: "/sign-in" });
    const field = await screen.findByLabelText("Password");
    expect(field).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(field).toHaveAttribute("type", "text");
    expect(screen.queryByText(/google/i)).toBeNull();
  });
});
