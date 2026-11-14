import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { scoreRangeOf, scoreTone, transcriptIndex } from "@/lib/audit";
import type { CallAudit, Me, Role } from "@/lib/types";
import { callDetail, callPage, callRow, me } from "@/test/fixtures";
import { renderWithProviders, router } from "@/test/render";
import { server } from "@/test/server";
import CallsPage from "./page";

const RANGE = "from=2026-10-30&to=2026-11-05";
const OPEN = `/calls?${RANGE}&room=call-7f3a`;

const evidence = (line: number, at: string, quote: string, kind: "good" | "problem" = "good") => ({
  line, at, at_s: 3, step_id: "s1", step_name: "Greeting", speaker: line === 1 ? "caller" : "agent", quote, event: "", kind, note: "note",
});

const ready: Extract<CallAudit, { id: number }> = {
  id: 1,
  status: "ready",
  enabled: true,
  error: "",
  skipped_reason: "",
  skipped_label: "",
  overall_score: 72,
  summary: "Warm opening; the licence question sounded scripted.",
  areas: [
    { key: "naturalness", label: "Sounds human", weight: 25, score: 3, summary: "Some stiff lines.",
      evidence: [evidence(0, "2026-11-05T09:02:03Z", "Priya बोल रही हूँ", "problem")] },
    { key: "listening", label: "Listening", weight: 20, score: 4, summary: "", evidence: [] },
    { key: "empathy", label: "Empathy and tone", weight: 15, score: 5, summary: "", evidence: [] },
    { key: "pacing", label: "Pacing and turn-taking", weight: 15, score: null, summary: "", evidence: [] },
    { key: "flow", label: "Flow and goal", weight: 15, score: 4, summary: "", evidence: [] },
    { key: "accuracy", label: "Accuracy", weight: 10, score: 5, summary: "", evidence: [] },
  ],
  moments: [
    { ...evidence(1, "2026-11-05T09:02:09Z", "बोलिए"), area: "listening", note: "Caller ready to talk" },
    { ...evidence(0, "2026-11-05T09:02:03Z", "नमस्ते", "problem"), area: "naturalness", note: "Opening is too long" },
  ],
  rubric_version: "2026-11-v1",
  model: "gemini-test",
  used_audio: false,
  quotes_purged: false,
  automatic: true,
  created_at: "2026-11-05T09:05:00Z",
  finished_at: "2026-11-05T09:05:20Z",
};

function serveAudit(audit: CallAudit, role: Role = "editor") {
  const posts: string[] = [];
  let current = audit;
  server.use(
    http.get("*/api/me", () => HttpResponse.json({ ...me, role } satisfies Me)),
    http.get("*/api/calls/:room/audit", () => HttpResponse.json(current)),
    http.post("*/api/calls/:room/audit", ({ params }) => {
      posts.push(String(params.room));
      current = { ...ready, status: "running" };
      return HttpResponse.json(current, { status: 202 });
    }),
  );
  return { posts };
}

describe("call audit", () => {
  it("shows the score, the areas and the moments", async () => {
    serveAudit(ready);
    renderWithProviders(<CallsPage />, { route: OPEN });
    const panel = await screen.findByRole("dialog");
    expect(await within(panel).findByLabelText("Score 72 out of 100")).toBeInTheDocument();
    expect(within(panel).getByText(ready.summary)).toBeInTheDocument();
    const areas = within(panel).getByRole("list", { name: "Scores by area" });
    expect(within(areas).getByRole("img", { name: "3 out of 5" })).toBeInTheDocument();
    expect(within(areas).getByRole("img", { name: "No score" })).toBeInTheDocument();
    expect(within(panel).getByText("To fix")).toBeInTheDocument();
    expect(within(panel).getByText("Opening is too long")).toBeInTheDocument();

    // Evidence opens under its area.
    await userEvent.setup().click(within(areas).getByRole("button", { name: /Sounds human/ }));
    expect(within(areas).getByText("Priya बोल रही हूँ")).toBeInTheDocument();
  });

  it("clicking a moment highlights its transcript line", async () => {
    serveAudit(ready);
    renderWithProviders(<CallsPage />, { route: OPEN });
    const panel = await screen.findByRole("dialog");
    await within(panel).findByText("Caller ready to talk");
    const chip = within(panel).getAllByRole("button", { name: /Show line at .* in the transcript/ })[0];
    await userEvent.setup().click(chip);
    const log = within(panel).getByRole("log", { name: "Call transcript" });
    const lines = log.querySelectorAll("[data-line]");
    await waitFor(() => expect(lines[0]).toHaveAttribute("class", expect.stringMatching(/active/)));
    expect(lines[1].className).not.toMatch(/active/);
  });

  it("editors can audit a call that has none; viewers can't", async () => {
    const { posts } = serveAudit({ status: "none", enabled: false });
    const view = renderWithProviders(<CallsPage />, { route: OPEN });
    const panel = await screen.findByRole("dialog");
    expect(await within(panel).findByText("Call audits are off. Turn them on in Settings, Call handling.")).toBeInTheDocument();
    await userEvent.setup().click(within(panel).getByRole("button", { name: "Audit this call" }));
    expect(await within(panel).findByText("Auditing this call…")).toBeInTheDocument();
    expect(posts).toEqual(["call-7f3a"]);
    view.unmount();

    serveAudit({ status: "none", enabled: true }, "viewer");
    renderWithProviders(<CallsPage />, { route: OPEN });
    const second = await screen.findByRole("dialog");
    expect(await within(second).findByText("This call hasn't been audited.")).toBeInTheDocument();
    expect(within(second).queryByRole("button", { name: "Audit this call" })).toBeNull();
  });

  it("says why a call has no score", async () => {
    serveAudit({ ...ready, status: "skipped", skipped_reason: "too_short", skipped_label: "Too short to audit" });
    const view = renderWithProviders(<CallsPage />, { route: OPEN });
    expect(await screen.findByText("Too short to audit")).toBeInTheDocument();
    view.unmount();

    serveAudit({ ...ready, status: "error", error: "Couldn't audit this call. Try again." });
    renderWithProviders(<CallsPage />, { route: OPEN });
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't audit this call. Try again.");
  });

  it("shows a Score column and filters by score", async () => {
    server.use(
      http.get("*/api/calls", () =>
        HttpResponse.json({ ...callPage, results: [{ ...callRow, audit_score: 54 }, { ...callRow, room: "b", audit_score: null }] }),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<CallsPage />, { route: `/calls?${RANGE}` });
    const table = await screen.findByRole("table", { name: "Calls" });
    expect(within(table).getByRole("columnheader", { name: "Score" })).toBeInTheDocument();
    expect(within(table).getByText("54")).toBeInTheDocument();
    expect(within(table).getByLabelText("Not audited")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Score"), "Below 60");
    expect(router.push).toHaveBeenLastCalledWith(`/calls?${RANGE}&score_max=59`, { scroll: false });
  });
});

describe("audit helpers", () => {
  it("bands scores like the call list", () => {
    expect([scoreTone(null), scoreTone(59), scoreTone(60), scoreTone(79), scoreTone(80)]).toEqual(["neutral", "bad", "amber", "amber", "ok"]);
  });

  it("reads the score filter back from the URL", () => {
    expect([scoreRangeOf("", ""), scoreRangeOf("", "59"), scoreRangeOf("80", ""), scoreRangeOf("10", "20")]).toEqual(["", "low", "high", "custom"]);
  });

  it("finds the transcript line an audit item points at", () => {
    const at = callDetail.transcript[1].at;
    expect(transcriptIndex(callDetail.transcript, { at, speaker: "caller" })).toBe(1);
    expect(transcriptIndex(callDetail.transcript, { at: "2026-11-05T10:00:00Z", speaker: "" })).toBe(-1);
    expect(transcriptIndex(callDetail.transcript, { at: null, speaker: "" })).toBe(-1);
  });
});
