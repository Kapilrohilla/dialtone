import userEvent from "@testing-library/user-event";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { DispositionList, DispositionListUpdate } from "@/lib/types";
import { dispositionList, me } from "@/test/fixtures";
import { setParams } from "@/test/navigation";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import DispositionListPage from "./page";

/** A short list: one Interested item and the fallback. */
const small: DispositionList = {
  ...dispositionList,
  items: [dispositionList.items[0], dispositionList.items.find((i) => i.code === "UNRESOLVED")!],
};

function serve(list: DispositionList = small, respond?: (body: DispositionListUpdate) => Response | undefined) {
  const patches: DispositionListUpdate[] = [];
  server.use(
    http.get("*/api/dispositions/5", () => HttpResponse.json(list)),
    http.patch("*/api/dispositions/5", async ({ request }) => {
      const body = (await request.json()) as DispositionListUpdate;
      patches.push(body);
      return respond?.(body) ?? HttpResponse.json({ ...list, ...body });
    }),
  );
  return patches;
}

function open(role: "owner" | "viewer" = "owner") {
  if (role !== "owner") server.use(http.get("*/api/me", () => HttpResponse.json({ ...me, role })));
  setParams({ id: "5" });
  const user = userEvent.setup();
  renderWithProviders(<DispositionListPage />, { route: "/dispositions/5" });
  return user;
}

const rowOf = (code: string) => within(screen.getByRole("table", { name: "Dispositions" })).getByText(code, { selector: "span" }).closest("tr")!;

describe("disposition list editor", () => {
  it("shows the items, the fallback and what the AI reads", async () => {
    serve(dispositionList);
    open();
    expect(await screen.findByRole("textbox", { name: "List name" })).toHaveValue("Driver hiring");
    expect(screen.getByRole("heading", { name: "Dispositions (14)" })).toBeInTheDocument();
    expect(within(rowOf("UNRESOLVED")).getByText("Fallback")).toBeInTheDocument();
    const preview = screen.getByLabelText("Instructions preview");
    expect(preview).toHaveTextContent("CBR: Call back requested. Driver asked to be called at another time. Capture the time they gave. Capture: Callback time (required).");
    expect(screen.getByText("Has Not reached and Dropped codes")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Driver lead qualifier" })).toHaveAttribute("href", "/agents/3");
    expect(screen.getByRole("button", { name: "Save list" })).toBeDisabled();
  });

  it("warns when there's no Not reached code", async () => {
    serve();
    open();
    expect(await screen.findByText("No Not reached code: unanswered calls get the fallback UNRESOLVED.")).toBeInTheDocument();
  });

  it("saves the whole list: name, items in order and the fallback", async () => {
    const patches = serve();
    const user = open();
    const name = await screen.findByRole("textbox", { name: "List name" });
    await user.clear(name);
    await user.type(name, "Driver hiring v2");

    await user.click(screen.getByRole("button", { name: "Add disposition" }));
    const editor = screen.getByRole("group", { name: "Edit new disposition" });
    await user.type(within(editor).getByRole("textbox", { name: /Code/ }), "cbr later");
    await user.type(within(editor).getByRole("textbox", { name: "Name" }), "Call back");
    await user.selectOptions(within(editor).getByRole("combobox", { name: "Report group" }), "Call back");
    await user.click(within(editor).getByRole("button", { name: "Add field to capture" }));
    await user.type(within(editor).getByRole("textbox", { name: "Label" }), "Callback time");
    expect(within(editor).getByRole("textbox", { name: "Key" })).toHaveValue("callback_time");
    await user.selectOptions(within(editor).getByRole("combobox", { name: "Type" }), "Date and time");
    await user.click(within(editor).getByRole("switch", { name: "Required" }));
    await user.click(within(editor).getByRole("button", { name: "Done" }));

    await user.click(screen.getByRole("button", { name: "Save list" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toEqual({
      name: "Driver hiring v2",
      fallback_code: "UNRESOLVED",
      items: [
        small.items[0],
        small.items[1],
        { code: "CBR_LATER", name: "Call back", description: "", group: "Call back", fields: [{ key: "callback_time", label: "Callback time", type: "datetime", required: true }] },
      ],
    });
    await waitFor(() => expect(screen.getByRole("button", { name: "Save list" })).toBeDisabled());
  });

  it("can't remove the fallback; another item can become it", async () => {
    const patches = serve();
    const user = open();
    await screen.findByRole("textbox", { name: "List name" });
    await user.click(within(rowOf("UNRESOLVED")).getByRole("button", { name: "Actions for UNRESOLVED" }));
    expect(screen.getByRole("menuitem", { name: "Remove" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Set as fallback" })).toBeDisabled();
    await user.keyboard("{Escape}");

    await user.click(within(rowOf("INTERESTED")).getByRole("button", { name: "Actions for INTERESTED" }));
    await user.click(screen.getByRole("menuitem", { name: "Set as fallback" }));
    await user.click(within(rowOf("UNRESOLVED")).getByRole("button", { name: "Actions for UNRESOLVED" }));
    await user.click(screen.getByRole("menuitem", { name: "Remove" }));
    expect(screen.getByRole("heading", { name: "Dispositions (1)" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "s", ctrlKey: true });
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({ fallback_code: "INTERESTED", items: [small.items[0]] });
  });

  it("moves items and shows the server's errors", async () => {
    const patches = serve(small, () => HttpResponse.json({ items: ["Codes must be unique: INTERESTED."] }, { status: 400 }));
    const user = open();
    await screen.findByRole("textbox", { name: "List name" });
    await user.click(within(rowOf("UNRESOLVED")).getByRole("button", { name: "Actions for UNRESOLVED" }));
    await user.click(screen.getByRole("menuitem", { name: "Move up" }));
    await user.click(screen.getByRole("button", { name: "Save list" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0].items!.map((i) => i.code)).toEqual(["UNRESOLVED", "INTERESTED"]);
    expect(await screen.findAllByText("Codes must be unique: INTERESTED.")).not.toHaveLength(0);
  });

  it("checks codes before saving", async () => {
    const patches = serve();
    const user = open();
    await screen.findByRole("textbox", { name: "List name" });
    await user.click(screen.getByRole("button", { name: "Add disposition" }));
    await user.type(within(screen.getByRole("group", { name: "Edit new disposition" })).getByRole("textbox", { name: /Code/ }), "INTERESTED");
    await user.click(screen.getByRole("button", { name: "Save list" }));
    expect(await screen.findByText("The code INTERESTED is used twice.")).toBeInTheDocument();
    expect(patches).toHaveLength(0);
  });

  it("is read-only for viewers", async () => {
    serve();
    open("viewer");
    expect(await screen.findByRole("textbox", { name: "List name" })).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "Save list" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add disposition" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Actions for/ })).not.toBeInTheDocument();
  });
});
