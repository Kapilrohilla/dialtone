import { useEffect, useRef, useState, type KeyboardEvent } from "react";

/** Open state for a toolbar dropdown: closes on outside press and Escape (focus back to the trigger),
 *  and moves focus between its `[role=menuitem]`s with the arrow keys, Home and End. */
export function usePopover() {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  const items = () => Array.from(root.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);

  useEffect(() => {
    if (!open) return;
    items()[0]?.focus();
    function outside(e: MouseEvent) {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [open]);

  function close(refocus = false) {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  }

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      close(true);
      return;
    }
    const list = items();
    const at = list.indexOf(document.activeElement as HTMLElement);
    if (at === -1) return; // focus is in a form inside the popover: leave its keys alone
    const go = (i: number) => {
      e.preventDefault();
      list[(i + list.length) % list.length]?.focus();
    };
    if (e.key === "ArrowDown") go(at + 1);
    else if (e.key === "ArrowUp") go(at - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(list.length - 1);
    else if (e.key === "Tab") close();
  }

  return { open, setOpen, close, root, trigger, onKeyDown };
}
