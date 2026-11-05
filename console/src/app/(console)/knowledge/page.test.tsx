import userEvent from "@testing-library/user-event";
import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { DocUpdate } from "@/lib/queries";
import type { KnowledgeDoc, KnowledgeListItem, Revision } from "@/lib/types";
import { knowledgeDoc, me } from "@/test/fixtures";
import { router, renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import KnowledgePage from "./page";

const second: KnowledgeDoc = { ...knowledgeDoc, id: 8, title: "Refund policy", used_by: 0, current_revision: 1, body_md: "Refunds take five days." };
const revisions: Revision[] = [
  { number: 1, edited_by: "Asha Rao", created_at: "2026-11-01T10:00:00Z" },
  { number: 2, edited_by: "Kapil Rohilla", created_at: "2026-11-03T12:00:00Z" },
];
const oldBody = "The weekly plan was cheaper.";

/** A small stateful knowledge API. */
function serve(initial: KnowledgeDoc[] = [knowledgeDoc, second]) {
  const docs = [...initial];
  const patches: DocUpdate[] = [];
  const toItem = (d: KnowledgeDoc): KnowledgeListItem => ({ id: d.id, title: d.title, updated_at: d.updated_at, current_revision: d.current_revision, used_by: d.used_by });
  server.use(
    http.get("*/api/knowledge", () => HttpResponse.json(docs.map(toItem))),
    http.post("*/api/knowledge", async ({ request }) => {
      const body = (await request.json()) as { title: string; body_md: string };
      const doc = { ...knowledgeDoc, id: 99, current_revision: 1, used_by: 0, ...body };
      docs.push(doc);
      return HttpResponse.json(doc, { status: 201 });
    }),
    http.get("*/api/knowledge/:id", ({ params }) => {
      const doc = docs.find((d) => d.id === Number(params.id));
      return doc ? HttpResponse.json(doc) : HttpResponse.json({ detail: "Not found." }, { status: 404 });
    }),
    http.patch("*/api/knowledge/:id", async ({ params, request }) => {
      const body = (await request.json()) as DocUpdate;
      patches.push(body);
      const i = docs.findIndex((d) => d.id === Number(params.id));
      docs[i] = { ...docs[i], ...body };
      return HttpResponse.json(docs[i]);
    }),
    http.get("*/api/knowledge/:id/revisions", () => HttpResponse.json(revisions)),
    http.get("*/api/knowledge/:id/revisions/:n", ({ params }) =>
      HttpResponse.json({ ...revisions[Number(params.n) - 1], body_md: Number(params.n) === 1 ? oldBody : knowledgeDoc.body_md }),
    ),
  );
  return { docs, patches };
}

async function typeAtEnd(box: HTMLElement, text: string) {
  const user = userEvent.setup();
  await user.click(box);
  await user.keyboard(text);
  return user;
}

describe("Knowledge base", () => {
  it("selects the first document and shows its body", async () => {
    serve();
    renderWithProviders(<KnowledgePage />, { route: "/knowledge" });
    expect(await screen.findByRole("textbox", { name: "Document title" })).toHaveValue("Pricing and plans, Pune");
    expect(await screen.findByText(/The weekly plan is for drivers/)).toBeInTheDocument();
    expect(screen.getByText("Used by 1 agent")).toBeInTheDocument();
    expect(screen.getByText("Not used by any agent")).toBeInTheDocument();
    expect(screen.getByText("The agent only quotes what is written here.")).toBeInTheDocument();
    expect(await screen.findByText("Kapil Rohilla")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("opens the document named in the URL", async () => {
    serve();
    renderWithProviders(<KnowledgePage />, { route: "/knowledge?doc=8" });
    expect(await screen.findByRole("textbox", { name: "Document title" })).toHaveValue("Refund policy");
  });

  it("save sends title and markdown and shows the republish hint", async () => {
    const { patches } = serve();
    renderWithProviders(<KnowledgePage />, { route: "/knowledge" });
    const user = userEvent.setup();
    const title = await screen.findByRole("textbox", { name: "Document title" });
    await user.type(title, " v2");
    await screen.findByText(/The weekly plan is for drivers/);
    await user.click(screen.getByRole("radio", { name: "Markdown" }));
    await user.type(screen.getByRole("textbox", { name: "Document Markdown" }), " Nothing else.");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("Saved. Agents using this document need republishing before callers hear the change."),
    ).toBeInTheDocument();
    expect(patches).toEqual([{ title: "Pricing and plans, Pune v2", body_md: `${knowledgeDoc.body_md} Nothing else.` }]);
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeDisabled());
  });

  it("saves only the changed field, plainly when no agent uses the document, with Ctrl+S", async () => {
    const { patches } = serve();
    renderWithProviders(<KnowledgePage />, { route: "/knowledge?doc=8" });
    const user = userEvent.setup();
    await user.type(await screen.findByRole("textbox", { name: "Document title" }), "!");
    await user.keyboard("{Control>}s{/Control}");
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(patches).toEqual([{ title: "Refund policy!" }]);
  });

  it("switching documents with unsaved changes asks first", async () => {
    serve();
    renderWithProviders(<KnowledgePage />, { route: "/knowledge" });
    const user = userEvent.setup();
    await user.type(await screen.findByRole("textbox", { name: "Document title" }), "x");
    await user.click(screen.getByRole("button", { name: /Refund policy/ }));
    const dialog = await screen.findByRole("dialog", { name: "Discard unsaved changes to Pricing and plans, Punex?" });
    await user.click(within(dialog).getByRole("button", { name: "Keep editing" }));
    expect(screen.getByRole("textbox", { name: "Document title" })).toHaveValue("Pricing and plans, Punex");
    expect(router.replace).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /Refund policy/ }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Discard" }));
    expect(await screen.findByDisplayValue("Refund policy")).toBeInTheDocument();
    expect(router.replace).toHaveBeenCalledWith("/knowledge?doc=8");
  });

  it("switches without asking when nothing changed, and warns before the tab closes only while dirty", async () => {
    serve();
    renderWithProviders(<KnowledgePage />, { route: "/knowledge" });
    const user = userEvent.setup();
    await screen.findByDisplayValue("Pricing and plans, Pune");
    const clean = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);
    await user.click(screen.getByRole("button", { name: /Refund policy/ }));
    expect(await screen.findByDisplayValue("Refund policy")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Document title" }), "x");
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
  });

  it("markdown mode edits the same text", async () => {
    const { patches } = serve();
    renderWithProviders(<KnowledgePage />, { route: "/knowledge" });
    const user = userEvent.setup();
    await screen.findByText(/The weekly plan is for drivers/);
    await user.click(screen.getByRole("radio", { name: "Markdown" }));
    const raw = screen.getByRole("textbox", { name: "Document Markdown" });
    expect(raw).toHaveValue(knowledgeDoc.body_md);
    await user.type(raw, " Extra.");
    await user.click(screen.getByRole("radio", { name: "Rich text" }));
    expect(await screen.findByText(/Extra\./)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText(/^Saved/);
    expect(patches).toEqual([{ body_md: `${knowledgeDoc.body_md} Extra.` }]);
  });

  it("rich text edits are saved as markdown", async () => {
    const { patches } = serve();
    renderWithProviders(<KnowledgePage />, { route: "/knowledge" });
    const box = await screen.findByRole("textbox", { name: "Document text" });
    await screen.findByText(/The weekly plan is for drivers/);
    const user = await typeAtEnd(box, " Typed.");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByText(/^Saved/);
    expect(patches[0].body_md).toContain("Typed.");
  });

  it("upload selects the new document", async () => {
    const { docs } = serve();
    server.use(
      http.post("*/api/knowledge/upload", async ({ request }) => {
        const file = (await request.formData()).get("file") as File;
        const doc = { ...knowledgeDoc, id: 55, title: "Fares", used_by: 0, body_md: await file.text() };
        docs.push(doc);
        return HttpResponse.json(doc, { status: 201 });
      }),
    );
    renderWithProviders(<KnowledgePage />, { route: "/knowledge" });
    await screen.findByDisplayValue("Pricing and plans, Pune");
    const file = new File(["# Fares\n\nAll fares include tax."], "Fares.md", { type: "text/markdown" });
    await userEvent.setup().upload(screen.getByLabelText("Markdown file"), file);
    expect(await screen.findByDisplayValue("Fares")).toBeInTheDocument();
    expect(await screen.findByText("All fares include tax.")).toBeInTheDocument();
    expect(router.replace).toHaveBeenCalledWith("/knowledge?doc=55");
  });

  it("upload shows the API's file error", async () => {
    serve();
    server.use(http.post("*/api/knowledge/upload", () => HttpResponse.json({ detail: "Only .md (Markdown) files are supported." }, { status: 400 })));
    renderWithProviders(<KnowledgePage />, { route: "/knowledge" });
    await screen.findByDisplayValue("Pricing and plans, Pune");
    await userEvent.setup({ applyAccept: false }).upload(screen.getByLabelText("Markdown file"), new File(["x"], "notes.txt", { type: "text/plain" }));
    expect(await screen.findByText("Only .md (Markdown) files are supported.")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Pricing and plans, Pune")).toBeInTheDocument();
  });

  it("restores an old version as an unsaved change", async () => {
    const { patches } = serve();
    renderWithProviders(<KnowledgePage />, { route: "/knowledge" });
    const user = userEvent.setup();
    await screen.findByText(/The weekly plan is for drivers/);
    await user.click(screen.getByRole("button", { name: "Version history" }));
    const panel = await screen.findByRole("dialog", { name: "Version history" });
    const buttons = await within(panel).findAllByRole("button", { name: /^Version \d/ });
    expect(buttons.map((b) => b.textContent)).toEqual([expect.stringContaining("Version 2"), expect.stringContaining("Version 1")]);
    expect(within(panel).getByRole("button", { name: "Restore this version" })).toBeDisabled();
    await user.click(buttons[1]);
    expect(await within(panel).findByText(oldBody)).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Restore this version" }));
    expect(screen.queryByRole("dialog", { name: "Version history" })).not.toBeInTheDocument();
    expect(await screen.findByText(oldBody)).toBeInTheDocument();
    expect(patches).toEqual([]);
    const saveButton = screen.getByRole("button", { name: "Save" });
    expect(saveButton).toBeEnabled();
    await user.click(saveButton);
    await screen.findByText(/^Saved/);
    expect(patches).toEqual([{ body_md: oldBody }]);
  });

  it("new document is created and selected", async () => {
    serve();
    renderWithProviders(<KnowledgePage />, { route: "/knowledge" });
    await screen.findByDisplayValue("Pricing and plans, Pune");
    await userEvent.setup().click(screen.getByRole("button", { name: "New document" }));
    expect(await screen.findByDisplayValue("Untitled document")).toBeInTheDocument();
    expect(router.replace).toHaveBeenCalledWith("/knowledge?doc=99");
  });

  it('empty workspace shows "No documents yet" with New document', async () => {
    serve([]);
    renderWithProviders(<KnowledgePage />, { route: "/knowledge" });
    expect(await screen.findByText("No documents yet")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "New document" }));
    expect(await screen.findByDisplayValue("Untitled document")).toBeInTheDocument();
  });

  it("viewers can read but not edit", async () => {
    serve();
    server.use(http.get("*/api/me", () => HttpResponse.json({ ...me, role: "viewer" })));
    renderWithProviders(<KnowledgePage />, { route: "/knowledge" });
    expect(await screen.findByRole("textbox", { name: "Document title" })).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Upload .md" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New document" })).not.toBeInTheDocument();
  });
});
