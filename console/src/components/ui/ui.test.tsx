import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { Dialog, StateBlock, Switch, Menu, Toast, useToast, Button } from "@/components/ui";

function DialogHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>Open it</button>
      <Dialog open={open} onClose={() => setOpen(false)} title="Remove step">
        <button>Confirm</button>
      </Dialog>
    </>
  );
}

function SwitchHarness() {
  const [on, setOn] = useState(false);
  return <Switch checked={on} onChange={setOn} label="Adjust to caller's mood" />;
}

describe("ui", () => {
  it("Dialog closes on Escape and returns focus to the opener", async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    const opener = screen.getByRole("button", { name: "Open it" });
    await user.click(opener);
    expect(screen.getByRole("dialog", { name: "Remove step" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("Switch toggles aria-checked with Space", async () => {
    const user = userEvent.setup();
    render(<SwitchHarness />);
    const sw = screen.getByRole("switch", { name: "Adjust to caller's mood" });
    expect(sw).toHaveAttribute("aria-checked", "false");
    await user.tab();
    expect(sw).toHaveFocus();
    await user.keyboard(" ");
    expect(sw).toHaveAttribute("aria-checked", "true");
  });

  it("StateBlock error calls onRetry", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<StateBlock state="error" title="Couldn't load calls" body="The server is down." onRetry={onRetry} />);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("Button with loading is disabled", () => {
    render(<Button loading>Save</Button>);
    expect(screen.getByRole("button", { name: /Save/ })).toBeDisabled();
  });

  it("Menu opens, moves with arrows, and closes on Escape", async () => {
    const user = userEvent.setup();
    const onRename = vi.fn();
    render(
      <Menu label="Row actions" items={[{ label: "Rename", onSelect: onRename }, { label: "Delete", onSelect: () => {}, danger: true }]} />,
    );
    const trigger = screen.getByRole("button", { name: "Row actions" });
    await user.click(trigger);
    expect(screen.getByRole("menuitem", { name: "Rename" })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "Delete" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    await user.click(trigger);
    await user.keyboard("{Enter}");
    expect(onRename).toHaveBeenCalledOnce();
  });

  it("Toast announces through one polite live region", async () => {
    const user = userEvent.setup();
    function Harness() {
      const toast = useToast();
      return <button onClick={() => toast.show("Saved", "ok")}>Go</button>;
    }
    render(
      <Toast>
        <Harness />
      </Toast>,
    );
    await user.click(screen.getByRole("button", { name: "Go" }));
    expect(screen.getByRole("status")).toHaveTextContent("Saved");
  });
});
