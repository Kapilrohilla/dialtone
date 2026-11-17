import { describe, expect, it } from "vitest";
import { dispositionItems } from "@/test/fixtures";
import { aiLine, cleanCode, codesOf, draftErrors, formatCaptured, hasErrors, keyFromLabel } from "./dispositions";

describe("dispositions helpers", () => {
  it("cleans codes and derives field keys", () => {
    expect(cleanCode("call back-later!")).toBe("CALL_BACK_LATER");
    expect(keyFromLabel("Callback time")).toBe("callback_time");
    expect(keyFromLabel("1st visit")).toBe("f_1st_visit");
    expect(keyFromLabel("  ")).toBe("");
  });

  it("writes the line the AI reads", () => {
    expect(aiLine(dispositionItems[1])).toBe(
      "CBR: Call back requested. Driver asked to be called at another time. Capture the time they gave. Capture: Callback time (required).",
    );
    expect(aiLine({ code: "X", name: "Thing.", description: "", group: "Dropped", fields: [] })).toBe("X: Thing.");
  });

  it("checks a draft list like the server", () => {
    const ok = { name: "Driver hiring", items: dispositionItems, fallback_code: "UNRESOLVED" };
    expect(hasErrors(draftErrors(ok))).toBe(false);
    expect(draftErrors({ ...ok, fallback_code: "GONE" }).list).toBe("Choose a fallback disposition.");
    expect(draftErrors({ ...ok, name: " " }).name).toBe("Give the list a name.");
    const dup = draftErrors({ ...ok, items: [...dispositionItems, dispositionItems[0]] });
    expect(dup.items[14]).toBe("The code INTERESTED is used twice.");
    const badKey = { ...dispositionItems[1], fields: [{ key: "Bad Key", label: "Time", type: "text" as const, required: false }] };
    expect(draftErrors({ ...ok, items: [badKey] }).items[0]).toMatch(/must start with a letter/);
  });

  it("dedupes codes across lists", () => {
    const list = { id: 1, name: "A", items: dispositionItems, fallback_code: "UNRESOLVED", used_by: [], updated_at: "" };
    expect(codesOf([list, { ...list, id: 2 }])).toHaveLength(14);
  });

  it("formats captured dates and leaves the rest as typed", () => {
    expect(formatCaptured("2026-11-05T18:00", "datetime", "Asia/Kolkata")).toBe("5 Nov 2026, 18:00");
    expect(formatCaptured("2026-11-05T12:30:00Z", "datetime", "Asia/Kolkata")).toBe("5 Nov 2026, 18:00");
    expect(formatCaptured("after 6 pm", "datetime", "Asia/Kolkata")).toBe("after 6 pm");
    expect(formatCaptured("42", "number", "Asia/Kolkata")).toBe("42");
  });
});
