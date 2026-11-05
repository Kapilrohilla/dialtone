import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Editor } from "@tiptap/core";
import { fromEditor } from "./markdown";
import { TokenEditor, type TokenEditorProps } from "./TokenEditor";

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

  it("keeps bold and lists as Markdown in script mode", async () => {
    const value = "**Pune** only\n\n- one";
    const { onChange } = setup({ value });
    const box = await screen.findByRole("textbox", { name: "Script" });
    expect(serializedFrom(box)).toBe(value);
    expect(screen.getByRole("button", { name: "Bold" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "List" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Heading" })).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
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
