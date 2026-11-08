import { Ellipsis } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { cx } from "./util";
import styles from "./Menu.module.css";

export type MenuItem = { label: string; onSelect: () => void; danger?: boolean; disabled?: boolean };

export type MenuProps = {
  /** Accessible name of the "…" trigger. */
  label?: string;
  items: MenuItem[];
  className?: string;
  /** Where the popup opens. `"right"` pins it beside the trigger, bottom-aligned, so it never extends below it. */
  placement?: "bottom" | "right";
};

export function Menu({ label = "More actions", items, className, placement = "bottom" }: MenuProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const menuId = useId();

  const enabled = () => itemRefs.current.filter((el): el is HTMLButtonElement => !!el && !el.disabled);

  useEffect(() => {
    if (!open) return;
    enabled()[0]?.focus();
    function outside(e: MouseEvent) {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, [open]);

  function close(refocus: boolean) {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  }

  function onKeyDown(e: KeyboardEvent) {
    const list = enabled();
    const at = list.indexOf(document.activeElement as HTMLButtonElement);
    const go = (i: number) => {
      e.preventDefault();
      list[(i + list.length) % list.length]?.focus();
    };
    if (e.key === "ArrowDown") go(at + 1);
    else if (e.key === "ArrowUp") go(at - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(list.length - 1);
    else if (e.key === "Escape") {
      e.preventDefault();
      close(true);
    } else if (e.key === "Tab") close(false);
  }

  return (
    <div ref={root} className={cx(styles.root, className)}>
      <button
        ref={trigger}
        type="button"
        className={styles.trigger}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((o) => !o)}
      >
        <Ellipsis size={20} strokeWidth={1.75} aria-hidden="true" />
      </button>
      {open && (
        <div id={menuId} role="menu" aria-label={label} className={cx(styles.menu, placement === "right" && styles.right)} onKeyDown={onKeyDown}>
          {items.map((item, i) => (
            <button
              key={item.label}
              ref={(el) => {
                itemRefs.current[i] = el;
              }}
              type="button"
              role="menuitem"
              tabIndex={-1}
              disabled={item.disabled}
              className={cx(styles.item, item.danger && styles.danger)}
              onClick={() => {
                close(true);
                item.onSelect();
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
