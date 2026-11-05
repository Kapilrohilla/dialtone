import { expect, test, type Browser, type Page } from "@playwright/test";

// Smoke run of every screen against a real Django + Postgres (scripts/console-e2e.sh starts both).
// LiveKit and the agent simulator are not running, so live calls and test calls must say so.
// The tests share one database and run in order (workers: 1); later ones rely on earlier edits only
// where noted.

const EMAIL = process.env.E2E_EMAIL ?? "e2e@carrum.test";
const PASSWORD = process.env.E2E_PASSWORD ?? "";
const LIGHT = "test-results/light";
const DARK = "test-results/dark";

test.beforeAll(() => {
  if (!PASSWORD) throw new Error("E2E_PASSWORD is not set; run through scripts/console-e2e.sh");
});

/** Signs in through the API (the first test covers the form): the session cookie lands in the page's context. */
async function signIn(page: Page) {
  await page.request.get("/api/auth/csrf");
  const csrf = (await page.context().cookies()).find((c) => c.name === "csrftoken")?.value ?? "";
  const res = await page.request.post("/api/auth/login", {
    data: { email: EMAIL, password: PASSWORD },
    headers: { "X-CSRFToken": csrf },
  });
  expect(res.ok(), `sign in: ${res.status()}`).toBeTruthy();
}

function baseURL() {
  return process.env.E2E_BASE_URL ?? "http://localhost:3100";
}

/** Collects uncaught page errors (crashes); call the returned check at the end of a test to fail on any. */
function watchErrors(page: Page) {
  const crashes: string[] = [];
  page.on("pageerror", (e) => crashes.push(e.message));
  return () => expect(crashes, "uncaught errors in the page").toEqual([]);
}

async function shot(page: Page, dir: string, name: string) {
  // Let fonts and the canvas fit settle so the picture matches what a person sees.
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: `${dir}/${name}.png`, fullPage: true });
}

async function openAgent(page: Page) {
  await page.goto("/agents");
  await page.getByRole("table").getByRole("link", { name: "Driver lead qualifier" }).click();
  await expect(page).toHaveURL(/\/agents\/\d+$/);
  await expect(page.getByRole("region", { name: "Opening" })).toBeVisible();
  // The side panel loads the attached knowledge separately; wait so screenshots show it.
  await expect(page.getByText("Approved pricing and rules", { exact: true })).toBeVisible();
}

async function openWorkflow(page: Page) {
  await page.goto("/workflows");
  await page.getByRole("link", { name: "Driver onboarding" }).click();
  await expect(page).toHaveURL(/\/workflows\/\d+$/);
  await expect(page.locator(".react-flow__node").first()).toBeVisible();
}

test("1. sign in lands on Today with empty readings", async ({ page }) => {
  const noCrash = watchErrors(page);
  await page.goto("/sign-in");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await shot(page, LIGHT, "01-sign-in");
  await page.getByLabel("Work email").fill(EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("heading", { name: "Today", level: 1 })).toBeVisible();
  await expect(page).toHaveURL(`${baseURL()}/`);
  const readings = page.locator("main");
  for (const [label, value] of [["Calls today", "0"], ["Connected", "—"], ["Interested", "0"], ["Average call", "—"]]) {
    await expect(readings.getByText(label, { exact: true })).toBeVisible();
    await expect(readings.getByText(label, { exact: true }).locator("..")).toContainText(value);
  }
  await expect(page.getByText("No one is waiting for a call back.")).toBeVisible();
  // The primary is a link styled as a button: no underline.
  await expect(page.getByRole("link", { name: "Open live calls" })).toHaveCSS("text-decoration-line", "none");
  await shot(page, LIGHT, "02-today");
  noCrash();
});

test("2. agents: the live agent's script autosaves an expression", async ({ page }) => {
  const noCrash = watchErrors(page);
  await signIn(page);
  await page.goto("/agents");
  const row = page.getByRole("row", { name: /Driver lead qualifier/ });
  await expect(row).toBeVisible();
  await expect(row.getByText("Live", { exact: true })).toBeVisible();
  await shot(page, LIGHT, "03-agents");

  await openAgent(page);
  const opening = page.getByRole("region", { name: "Opening" });
  await expect(opening).toContainText("you speak first");
  const body = opening.getByRole("textbox", { name: "Opening" });
  await body.locator("p").last().click();
  await page.keyboard.press("End");
  await opening.getByRole("button", { name: "Expression" }).click();
  await page.getByRole("menu", { name: "Expressions" }).getByRole("menuitem", { name: /^laugh/ }).click();
  await expect(opening.locator('[data-expr="laugh"]')).toHaveCount(1);
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();

  await page.reload();
  await expect(page.getByRole("region", { name: "Opening" }).locator('[data-expr="laugh"]')).toHaveCount(1);
  await shot(page, LIGHT, "04-script-editor");
  noCrash();
});

test("3. test call says the simulator isn't running", async ({ page }) => {
  const noCrash = watchErrors(page);
  await signIn(page);
  await openAgent(page);
  await page.getByRole("button", { name: "Test call" }).click();
  const sim = page.getByRole("dialog", { name: "Test call" });
  await expect(sim).toBeVisible();
  await sim.getByRole("textbox").first().fill("Hello");
  await sim.getByRole("textbox").first().press("Enter");
  await expect(sim.getByText("The test simulator isn't running.")).toBeVisible({ timeout: 15_000 });
  noCrash();
});

test("4. knowledge: saving a document adds a version", async ({ page }) => {
  const noCrash = watchErrors(page);
  await signIn(page);
  await page.goto("/knowledge");
  await expect(page.getByRole("textbox", { name: "Document title" })).toHaveValue("Approved pricing and rules");
  await shot(page, LIGHT, "06-knowledge");

  await page.getByRole("radio", { name: "Markdown" }).click();
  const md = page.getByRole("textbox", { name: "Document Markdown" });
  await md.fill(`${await md.inputValue()}\nOffice hours are 10:00 to 18:00, Monday to Saturday.\n`);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("status").getByText(/^Saved\./)).toBeVisible();

  await page.getByRole("button", { name: "Version history" }).click();
  const history = page.getByRole("dialog", { name: "Version history" });
  await expect(history.getByRole("button", { name: /^Version \d+/ })).toHaveCount(2);
  noCrash();
});

test("5. workflows: the seeded flow fits, shows its chips and saves cleanly", async ({ page }) => {
  const noCrash = watchErrors(page);
  await signIn(page);
  await openWorkflow(page);

  const canvas = page.locator(".react-flow");
  const titles = ["Greeting", "Ask city", "Ask licence and experience", "Explain the plan", "End: interested",
    "Schedule a call back", "Transfer to a telecaller", "End: not in your city", "End: not eligible"];
  await expect(page.locator(".react-flow__node")).toHaveCount(titles.length);
  // Wait for the fit animation to finish before measuring.
  await page.waitForTimeout(800);
  const box = (await canvas.boundingBox())!;
  for (const title of titles) {
    const el = canvas.locator(".react-flow__node").filter({ has: page.getByText(title, { exact: true }) });
    const b = (await el.boundingBox())!;
    expect(b.x >= box.x && b.y >= box.y && b.x + b.width <= box.x + box.width && b.y + b.height <= box.y + box.height,
      `${title} inside the canvas`).toBeTruthy();
  }

  // Devanagari prompts render in the panel.
  await canvas.locator(".react-flow__node").filter({ hasText: "Greeting" }).click();
  const panel = page.getByRole("complementary", { name: "Step" });
  await expect(panel.getByRole("textbox", { name: "What the agent says" })).toContainText("नमस्ते, मैं Carrum से बोल रही हूँ।");

  await canvas.locator(".react-flow__node").filter({ hasText: "Explain the plan" }).click();
  await expect(panel.getByLabel("Step name")).toHaveValue("Explain the plan");
  await expect(panel.locator('[data-expr="excited"]')).toHaveCount(1);
  // Each path's target gets the panel's full width, so "Transfer to a telecaller" isn't cut off.
  const target = panel.getByRole("combobox", { name: "Where path 3 goes" });
  expect((await target.boundingBox())!.width).toBeGreaterThan(250);
  await shot(page, LIGHT, "05-workflow-builder");

  await panel.getByLabel("Step name").fill("Explain the plan briefly");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  await expect(page.getByRole("region", { name: "Problems with this workflow" })).toHaveCount(0);
  await page.reload();
  await expect(page.locator(".react-flow__node").filter({ hasText: "Explain the plan briefly" })).toBeVisible();
  noCrash();
});

test("6. live calls copes with the call server being down", async ({ page }) => {
  const noCrash = watchErrors(page);
  await signIn(page);
  await page.goto("/live");
  await expect(page.getByText(/Couldn't reach the call server\.|No calls right now\./).first()).toBeVisible();
  await shot(page, LIGHT, "07-live-calls");
  noCrash();
});

test("7. call history is empty and exports a date range", async ({ page }) => {
  const noCrash = watchErrors(page);
  await signIn(page);
  await page.goto("/calls");
  await expect(page.getByText("No calls yet.")).toBeVisible();
  const exportLink = page.getByRole("link", { name: "Export" });
  // A link styled as a button: no underline.
  await expect(exportLink).toHaveCSS("text-decoration-line", "none");
  const href = await exportLink.getAttribute("href");
  expect(href).toMatch(/from=\d{4}-\d{2}-\d{2}/);
  expect(href).toMatch(/to=\d{4}-\d{2}-\d{2}/);
  await shot(page, LIGHT, "08-call-history");
  noCrash();
});

/** The ten screens, for the dark pass. */
async function darkPass(page: Page, browser: Browser) {
  const screens: [string, string][] = [
    ["02-today", "/"], ["03-agents", "/agents"], ["06-knowledge", "/knowledge"], ["07-live-calls", "/live"],
    ["08-call-history", "/calls"], ["09-settings", "/settings"], ["10-integrations", "/integrations"],
  ];
  for (const [name, path] of screens) {
    await page.goto(path);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.waitForLoadState("networkidle");
    await shot(page, DARK, name);
  }
  await openAgent(page);
  await shot(page, DARK, "04-script-editor");
  await openWorkflow(page);
  await page.waitForTimeout(800);
  await page.locator(".react-flow__node").filter({ hasText: "Explain the plan" }).click();
  await shot(page, DARK, "05-workflow-builder");

  // Signed out, the theme cookie still applies.
  const url = new URL(baseURL());
  const context = await browser.newContext({ colorScheme: "light", viewport: { width: 1440, height: 900 } });
  await context.addCookies([{ name: "cv_theme", value: "dark", domain: url.hostname, path: "/" }]);
  const signedOut = await context.newPage();
  await signedOut.goto(`${baseURL()}/sign-in`);
  await expect(signedOut.locator("html")).toHaveAttribute("data-theme", "dark");
  await shot(signedOut, DARK, "01-sign-in");
  await context.close();
}

test("8. settings: dark appearance is saved and kept", async ({ page, browser }) => {
  const noCrash = watchErrors(page);
  await signIn(page);
  await page.goto("/settings");
  await expect(page.getByRole("textbox", { name: "Full name" })).toHaveValue("E2E Owner");
  await expect(page.getByRole("link", { name: "Team" })).toHaveCSS("text-decoration-line", "none");
  await shot(page, LIGHT, "09-settings");

  await page.getByRole("radio", { name: "Dark" }).click();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("status").getByText("Saved.")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByRole("radio", { name: "Dark" })).toHaveAttribute("aria-checked", "true");

  await darkPass(page, browser);

  // Back to light for the remaining test and its screenshot.
  await page.goto("/settings");
  await page.getByRole("radio", { name: "Light" }).click();
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  noCrash();
});

test("9. integrations, sign out and the sign-in redirect", async ({ page }) => {
  const noCrash = watchErrors(page);
  await signIn(page);
  await page.goto("/integrations");
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(9); // header + eight
  await shot(page, LIGHT, "10-integrations");

  await page.getByRole("button", { name: "User menu" }).click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

  await page.goto("/agents");
  await expect(page).toHaveURL(`${baseURL()}/sign-in?next=%2Fagents`);
  noCrash();
});
