import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Editor } from "@tiptap/core";
import { fromEditor } from "./markdown";
import { TokenEditor, type TokenEditorProps } from "./TokenEditor";

/** The SCRIPT section bodies seeded by dashboard/voiceagents/management/commands/seed_carrum.py (tests run from console/). */
const SEED_BODIES = [
  ...readFileSync(resolve(process.cwd(), "../dashboard/voiceagents/management/commands/seed_carrum.py"), "utf-8")
    .split("\nSCRIPT = [")[1]
    .split("\n]\n")[0]
    .matchAll(/"body": """([\s\S]*?)"""/g),
].map((m) => m[1]);

const PLAIN_CASES = [
  "5 * 2 [approx]",
  "पूछिए * और [यह]",
  "- a leading dash",
  "1. a leading number",
  "# a leading hash",
  "aapne <the time they gave> bataya hai",
  "A & B &amp; C",
  "call `record_outcome`, then `end_call`",
  "[[expr:Laugh]] stays text",
  "  indented\n\n\ttab and _x_ and *y*  ",
];

const DOCUMENT_CASES = [
  "A & B < C",
  "Rent is 5 * 2\n\n- one\n- two",
  "Plain text\nwrapped\n\n## End",
  "1. first\n2. second",
  "Call `record_outcome` first",
  "# Title\n\nBody",
  "Price [approx] is ₹—",
];

const HINDI = "[[expr:happy]]नमस्ते! [[expr:pause:1.2]]क्या मेरी बात {{lead.name}} जी से हो रही है?";

function setup(props: Partial<TokenEditorProps> = {}) {
  const onChange = vi.fn<(value: string) => void>();
  const user = userEvent.setup();
  render(<TokenEditor value="" onChange={onChange} mode="script" aria-label="Script" {...props} />);
  return { onChange, user };
}

/** Tiptap keeps its editor on the ProseMirror root element. */
const serializedFrom = (box: HTMLElement) => fromEditor((box as HTMLElement & { editor: Editor }).editor);

const lastChange = (fn: ReturnType<typeof vi.fn>) => fn.mock.calls.at(-1)?.[0] as string;

describe("TokenEditor", () => {
  it("found the seeded script sections", () => {
    expect(SEED_BODIES.length).toBeGreaterThanOrEqual(7);
    expect(SEED_BODIES[1]).toMatch(/^1\. Opening/);
  });

  it("round-trips Devanagari around chips", async () => {
    const { onChange } = setup({ value: HINDI });
    const box = await screen.findByRole("textbox", { name: "Script" });
    expect(box).toHaveTextContent("[happy]नमस्ते! [pause 1.2s]क्या मेरी बात {{lead.name}} जी से हो रही है?");
    expect(serializedFrom(box)).toBe(HINDI);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("inserts an expression from the menu at the cursor", async () => {
    const { onChange, user } = setup({ value: "नमस्ते" });
    await screen.findByRole("textbox", { name: "Script" });
    await user.click(screen.getByRole("button", { name: "Expression" }));
    await user.click(screen.getByRole("menuitem", { name: /^laugh/ }));
    expect(lastChange(onChange)).toBe("[[expr:laugh]]नमस्ते");
  });

  it("shows built-in hints in the menu", async () => {
    const { user } = setup({ value: "" });
    await screen.findByRole("textbox", { name: "Script" });
    await user.click(screen.getByRole("button", { name: "Expression" }));
    expect(screen.getByRole("menuitem", { name: /^laugh/ })).toHaveTextContent("Say this with a light, warm laugh");
    expect(screen.getByRole("menuitem", { name: /^pause/ })).not.toHaveTextContent("{seconds}");
    expect(screen.queryByRole("menuitem", { name: "New expression…" })).not.toBeInTheDocument();
  });

  it("inserts pause with one second", async () => {
    const { onChange, user } = setup({ value: "" });
    await screen.findByRole("textbox", { name: "Script" });
    await user.click(screen.getByRole("button", { name: "Expression" }));
    await user.click(screen.getByRole("menuitem", { name: /^pause/ }));
    expect(lastChange(onChange)).toBe("[[expr:pause:1]]");
  });

  it("changes a pause from its popover", async () => {
    const { onChange, user } = setup({ value: "[[expr:pause:1.2]]रुकिए" });
    const box = await screen.findByRole("textbox", { name: "Script" });
    await user.click(box.querySelector<HTMLElement>('[data-expr="pause"]')!);
    const seconds = screen.getByRole("spinbutton", { name: "Seconds" });
    await user.clear(seconds);
    await user.type(seconds, "2.5");
    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect(lastChange(onChange)).toBe("[[expr:pause:2.5]]रुकिए");
  });

  it("lists the agent's custom expressions", async () => {
    const { onChange, user } = setup({ value: "", customExpressions: { calm: "say this slowly and calmly" } });
    await screen.findByRole("textbox", { name: "Script" });
    await user.click(screen.getByRole("button", { name: "Expression" }));
    await user.click(screen.getByRole("menuitem", { name: /^calm/ }));
    expect(lastChange(onChange)).toBe("[[expr:calm]]");
  });

  it("creates a custom expression", async () => {
    const onCreateExpression = vi.fn();
    const { onChange, user } = setup({ value: "", onCreateExpression });
    const box = await screen.findByRole("textbox", { name: "Script" });
    await user.click(screen.getByRole("button", { name: "Expression" }));
    await user.click(screen.getByRole("menuitem", { name: "New expression…" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "calm");
    await user.type(screen.getByRole("textbox", { name: "How to say it" }), "say this slowly and calmly");
    await user.click(screen.getByRole("button", { name: "Add expression" }));
    expect(onCreateExpression).toHaveBeenCalledWith("calm", "say this slowly and calmly");
    expect(lastChange(onChange)).toBe("[[expr:calm]]");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(box).toHaveTextContent("[calm]");
  });

  it("rejects a built-in name for a custom expression", async () => {
    const onCreateExpression = vi.fn();
    const { user } = setup({ value: "", onCreateExpression });
    await screen.findByRole("textbox", { name: "Script" });
    await user.click(screen.getByRole("button", { name: "Expression" }));
    await user.click(screen.getByRole("menuitem", { name: "New expression…" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "laugh");
    await user.type(screen.getByRole("textbox", { name: "How to say it" }), "laugh a lot");
    await user.click(screen.getByRole("button", { name: "Add expression" }));
    expect(screen.getByText('"laugh" is a built-in expression; pick another name.')).toBeInTheDocument();
    expect(onCreateExpression).not.toHaveBeenCalled();
  });

  it("marks unknown expressions", async () => {
    const { onChange } = setup({ value: "[[expr:sing]] और [[expr:calm]]", customExpressions: { calm: "say this calmly" } });
    const box = await screen.findByRole("textbox", { name: "Script" });
    await waitFor(() => expect(box.querySelector('[data-expr="sing"]')).toHaveAttribute("title", "Unknown expression"));
    expect(box.querySelector('[data-expr="calm"]')).not.toHaveAttribute("title");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("inserts a variable from the menu", async () => {
    const { onChange, user } = setup({ value: "" });
    await screen.findByRole("textbox", { name: "Script" });
    await user.click(screen.getByRole("button", { name: "Variable" }));
    expect(screen.getByText("Filled from the lead when the call has one; otherwise the agent says it without the name.")).toBeInTheDocument();
    await user.click(screen.getByRole("menuitem", { name: /Lead city/ }));
    expect(lastChange(onChange)).toBe("{{lead.city}}");
  });

  it("inserts another lead field", async () => {
    const { onChange, user } = setup({ value: "" });
    await screen.findByRole("textbox", { name: "Script" });
    await user.click(screen.getByRole("button", { name: "Variable" }));
    await user.click(screen.getByRole("menuitem", { name: "Other…" }));
    await user.type(screen.getByRole("textbox", { name: "Lead field" }), "vehicle_type");
    await user.click(screen.getByRole("button", { name: "Insert" }));
    expect(lastChange(onChange)).toBe("{{lead.vehicle_type}}");
  });

  it("has only chip tools in script mode", async () => {
    setup({ value: "" });
    await screen.findByRole("textbox", { name: "Script" });
    for (const name of ["Bold", "Italic", "List", "Heading", "Table"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Variable" })).toBeInTheDocument();
  });

  describe("seeded script sections", () => {
    it.each(SEED_BODIES.map((body, i) => [i + 1, body] as const))("section %i round-trips untouched", async (_, body) => {
      const { onChange } = setup({ value: body });
      const box = await screen.findByRole("textbox", { name: "Script" });
      expect(serializedFrom(box)).toBe(body);
      expect(onChange).not.toHaveBeenCalled();
    });

    it.each(SEED_BODIES.map((body, i) => [i + 1, body] as const))("section %i changes only by an inserted chip", async (_, body) => {
      const { onChange, user } = setup({ value: body });
      await screen.findByRole("textbox", { name: "Script" });
      await user.click(screen.getByRole("button", { name: "Expression" }));
      await user.click(screen.getByRole("menuitem", { name: /^laugh/ }));
      expect(onChange).toHaveBeenCalledTimes(1);
      expect(lastChange(onChange)).toBe(`[[expr:laugh]]${body}`);
    });
  });

  describe.each(["script", "line"] as const)("%s mode keeps text byte for byte", (mode) => {
    it.each(PLAIN_CASES)("%j", async (value) => {
      const { onChange, user } = setup({ value, mode });
      const box = await screen.findByRole("textbox", { name: "Script" });
      expect(serializedFrom(box)).toBe(value);
      expect(onChange).not.toHaveBeenCalled();
      await user.click(screen.getByRole("button", { name: "Variable" }));
      await user.click(screen.getByRole("menuitem", { name: /Lead name/ }));
      expect(lastChange(onChange)).toBe(`{{lead.name}}${value}`);
    });
  });

  describe("document mode", () => {
    it.each(DOCUMENT_CASES)("round-trips %j untouched", async (value) => {
      const { onChange } = setup({ value, mode: "document" });
      const box = await screen.findByRole("textbox", { name: "Script" });
      expect(serializedFrom(box)).toBe(value);
      expect(onChange).not.toHaveBeenCalled();
    });

    it.each([
      ["A & B < C", "{{lead.name}}A & B < C"],
      ["Rent is 5 * 2\n\n- one\n- two", "{{lead.name}}Rent is 5 * 2\n\n- one\n- two"],
      ["Plain text\nwrapped\n\n## End", "{{lead.name}}Plain text\nwrapped\n\n## End"],
      ["1. first\n2. second", "1. {{lead.name}}first\n2. second"],
      ["# Title\n\nBody", "# {{lead.name}}Title\n\nBody"],
    ])("changes %j only by an inserted chip", async (value, expected) => {
      const { onChange, user } = setup({ value, mode: "document" });
      await screen.findByRole("textbox", { name: "Script" });
      await user.click(screen.getByRole("button", { name: "Variable" }));
      await user.click(screen.getByRole("menuitem", { name: /Lead name/ }));
      expect(lastChange(onChange)).toBe(expected);
    });

    it("never reads text as HTML", async () => {
      setup({ value: "A & B < C <the time they gave>", mode: "document" });
      const box = await screen.findByRole("textbox", { name: "Script" });
      expect(box).toHaveTextContent("A & B < C <the time they gave>");
    });

    it("turns tokens into chips but not inside code", async () => {
      setup({ value: "[[expr:laugh]]Hi {{lead.name}} `[[expr:sad]]`", mode: "document" });
      const box = await screen.findByRole("textbox", { name: "Script" });
      expect(box.querySelector('[data-expr="laugh"]')).toBeInTheDocument();
      expect(box.querySelector('[data-var="lead.name"]')).toBeInTheDocument();
      expect(box.querySelector('[data-expr="sad"]')).not.toBeInTheDocument();
      expect(serializedFrom(box)).toBe("[[expr:laugh]]Hi {{lead.name}} `[[expr:sad]]`");
    });
  });

  it("round-trips a knowledge table", async () => {
    const value = "## Prices\n\n| Plan | Weekly rent |\n| --- | --- |\n| Starter | ₹— |\n| Pro | ₹— |";
    const { onChange } = setup({ value, mode: "document" });
    const box = await screen.findByRole("textbox", { name: "Script" });
    expect(serializedFrom(box)).toBe(value);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Heading" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Table" })).toBeInTheDocument();
  });

  it("keeps line mode to one paragraph with no formatting", async () => {
    const { onChange, user } = setup({ value: "पूछिए", mode: "line" });
    const box = await screen.findByRole("textbox", { name: "Script" });
    expect(screen.queryByRole("button", { name: "Bold" })).not.toBeInTheDocument();
    await user.click(box);
    await user.keyboard("{Enter}ok");
    expect(lastChange(onChange)).toMatch(/^[^\n]*ok[^\n]*$/);
    expect(lastChange(onChange).replace("ok", "")).toBe("पूछिए");
  });

  it("hides the toolbar when read only", async () => {
    setup({ value: HINDI, readOnly: true });
    const box = await screen.findByRole("textbox", { name: "Script" });
    expect(box).toHaveAttribute("contenteditable", "false");
    expect(screen.queryByRole("button", { name: "Expression" })).not.toBeInTheDocument();
  });
});
