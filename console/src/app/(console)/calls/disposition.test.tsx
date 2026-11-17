import userEvent from "@testing-library/user-event";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { CallDetail, DispositionChangeInput } from "@/lib/types";
import { callDetail, dispositionItems, me } from "@/test/fixtures";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";
import { CallSlideOver } from "./_components/CallSlideOver";

const withList: CallDetail = {
  ...callDetail,
  disposition: {
    code: "CBR",
    name: "Call back requested",
    group: "Call back",
    source: "ai",
    reason: "Driver is driving now, asked to call after 6 pm.",
    fields: [{ key: "callback_time", label: "Callback time", type: "datetime", value: "2026-11-05T18:00" }],
    set_at: "2026-11-05T09:02:00Z",
    set_by: null,
  },
  disposition_history: [
    { code: "CBR", name: "Call back requested", group: "Call back", source: "ai", by: null, note: "", at: "2026-11-05T09:02:00Z" },
    { code: "INTERESTED", name: "Interested", group: "Interested", source: "user", by: "Priya", note: "Agreed to visit the office", at: "2026-11-05T12:40:00Z" },
  ],
  disposition_options: { list_name: "Driver hiring", items: dispositionItems },
};

function show(call: CallDetail, role: "owner" | "viewer" = "owner") {
  server.use(http.get("*/api/calls/:room", () => HttpResponse.json(call)));
  if (role !== "owner") server.use(http.get("*/api/me", () => HttpResponse.json({ ...me, role })));
  const user = userEvent.setup();
  renderWithProviders(<CallSlideOver room={call.room} timeZone="Asia/Kolkata" onClose={() => {}} />, { route: `/calls?room=${call.room}` });
  return user;
}

const card = () => screen.getByRole("region", { name: "Disposition" });

describe("call disposition", () => {
  it("shows who set it, the reason, captured fields and the history", async () => {
    const user = show(withList);
    await screen.findByText("Set by AI at 14:32");
    expect(within(card()).getByText("Call back requested")).toBeInTheDocument();
    expect(within(card()).getByText("CBR")).toBeInTheDocument();
    expect(within(card()).getByText("Reason: Driver is driving now, asked to call after 6 pm.")).toBeInTheDocument();
    expect(within(card()).getByText("Callback time")).toBeInTheDocument();
    expect(within(card()).getByText("5 Nov 2026, 18:00")).toBeInTheDocument();
    await user.click(within(card()).getByRole("button", { name: "History" }));
    const history = within(card()).getByRole("list", { name: "Disposition history" });
    expect(history).toHaveTextContent("AI set CBR");
    expect(history).toHaveTextContent("Priya changed to INTERESTED: “Agreed to visit the office”");
  });

  it("changes it with the captured fields and a note", async () => {
    let body: DispositionChangeInput | undefined;
    server.use(
      http.post("*/api/calls/:room/disposition", async ({ request }) => {
        body = (await request.json()) as DispositionChangeInput;
        return HttpResponse.json(withList);
      }),
    );
    const user = show(withList);
    await user.click(await within(await screen.findByRole("region", { name: "Disposition" })).findByRole("button", { name: "Change" }));
    const dialog = screen.getByRole("dialog", { name: "Change disposition" });
    const select = within(dialog).getByRole("combobox", { name: "Disposition" });
    expect(select).toHaveValue("CBR");
    expect(within(dialog).getByLabelText("Callback time (required)")).toHaveValue("2026-11-05T18:00");

    await user.selectOptions(select, "Interested (INTERESTED)");
    expect(within(dialog).queryByLabelText("Callback time (required)")).not.toBeInTheDocument();
    await user.selectOptions(select, "Call back requested (CBR)");
    // Back on the call's own code, its captured value returns; a required field left empty isn't sent.
    expect(within(dialog).getByLabelText("Callback time (required)")).toHaveValue("2026-11-05T18:00");
    fireEvent.change(within(dialog).getByLabelText("Callback time (required)"), { target: { value: "" } });
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Required.")).toBeInTheDocument();
    expect(body).toBeUndefined();

    fireEvent.change(within(dialog).getByLabelText("Callback time (required)"), { target: { value: "2026-11-06T10:30" } });
    await user.type(within(dialog).getByRole("textbox", { name: "Note" }), "Asked again for tomorrow");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(body).toEqual({ code: "CBR", note: "Asked again for tomorrow", fields: { callback_time: "2026-11-06T10:30" } }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Change disposition" })).not.toBeInTheDocument());
  });

  it("shows the server's errors in the dialog", async () => {
    server.use(http.post("*/api/calls/:room/disposition", () => HttpResponse.json({ code: ["Not in this agent's list."] }, { status: 400 })));
    const user = show(withList);
    await user.click(await within(await screen.findByRole("region", { name: "Disposition" })).findByRole("button", { name: "Change" }));
    const dialog = screen.getByRole("dialog", { name: "Change disposition" });
    await user.selectOptions(within(dialog).getByRole("combobox", { name: "Disposition" }), "Interested (INTERESTED)");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByText("Not in this agent's list.")).toBeInTheDocument();
  });

  it("says there's none when the agent has no list, with no Change", async () => {
    show({ ...callDetail, disposition: null, disposition_history: [], disposition_options: null });
    expect(await screen.findByText("No disposition — this agent has no disposition list.")).toBeInTheDocument();
    expect(within(card()).queryByRole("button", { name: "Change" })).not.toBeInTheDocument();
  });

  it("viewers can't change it", async () => {
    show(withList, "viewer");
    await screen.findByText("Set by AI at 14:32");
    expect(within(card()).queryByRole("button", { name: "Change" })).not.toBeInTheDocument();
  });
});
