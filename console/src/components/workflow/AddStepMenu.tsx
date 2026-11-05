"use client";

import { Plus } from "lucide-react";
import { useId } from "react";
import { usePopover } from "@/components/editor/usePopover";
import type { StepType } from "@/lib/types";
import styles from "./workflow.module.css";

const CHOICES: { type: StepType; label: string }[] = [
  { type: "prompt", label: "Say something" },
  { type: "collect", label: "Collect an answer" },
  { type: "knowledge", label: "Answer from knowledge" },
  { type: "transfer", label: "Transfer to a telecaller" },
  { type: "end", label: "End the call" },
];

export function AddStepMenu({ onAdd }: { onAdd: (type: StepType) => void }) {
  const { open, setOpen, close, root, trigger, onKeyDown } = usePopover();
  const menuId = useId();
  return (
    <div ref={root} className={styles.addMenu}>
      <button
        ref={trigger}
        type="button"
        className={styles.addButton}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((o) => !o)}
      >
        <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
        Add step
      </button>
      {open && (
        <div id={menuId} role="menu" aria-label="Add step" className={styles.menu} onKeyDown={onKeyDown}>
          {CHOICES.map((c) => (
            <button
              key={c.type}
              type="button"
              role="menuitem"
              tabIndex={-1}
              className={styles.menuItem}
              onClick={() => {
                close(true);
                onAdd(c.type);
              }}
            >
              {c.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
