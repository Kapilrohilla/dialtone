import { ChevronDown } from "lucide-react";
import { useId, useState } from "react";
import type { Expression } from "@/lib/types";
import { BUILTIN_EXPRESSIONS, BUILTIN_HINTS } from "@/lib/tokens";
import { NewExpressionDialog } from "./NewExpressionDialog";
import { usePopover } from "./usePopover";
import styles from "./editor.module.css";

/** Return false (or a promise of false) when the expression wasn't created; the chip is inserted only otherwise. */
export type CreateExpression = (name: string, hint: string) => void | boolean | Promise<void | boolean>;

export type ExpressionMenuProps = {
  /** Built-ins from GET /api/expressions; falls back to the server's constant list. */
  builtins?: Expression[];
  customExpressions: Record<string, string>;
  onInsert: (name: string) => void;
  /** Without it there is no "New expression…" item. */
  onCreateExpression?: CreateExpression;
};

const FALLBACK: Expression[] = BUILTIN_EXPRESSIONS.map((name) => ({ name, hint: BUILTIN_HINTS[name], builtin: true }));

/** Menu text for a hint: sentence case, and the pause placeholder replaced by plain words. */
function menuHint(name: string, hint: string): string {
  const text = name === "pause" || hint.includes("{seconds}") ? "pause before this, 1 second unless you change it" : hint;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function ExpressionMenu({ builtins = FALLBACK, customExpressions, onInsert, onCreateExpression }: ExpressionMenuProps) {
  const { open, setOpen, close, root, trigger, onKeyDown } = usePopover();
  const [creating, setCreating] = useState(false);
  const menuId = useId();
  const items = [
    ...builtins.map((e) => ({ name: e.name, hint: menuHint(e.name, e.hint) })),
    ...Object.entries(customExpressions).map(([name, hint]) => ({ name, hint })),
  ];

  function choose(name: string) {
    close();
    onInsert(name);
  }

  return (
    <div ref={root} className={styles.dropdown}>
      <button
        ref={trigger}
        type="button"
        className={styles.toolButton}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((o) => !o)}
      >
        Expression
        <ChevronDown size={16} strokeWidth={1.75} aria-hidden="true" />
      </button>
      {open && (
        <div id={menuId} role="menu" aria-label="Expressions" className={styles.menu} onKeyDown={onKeyDown}>
          {items.map((item) => (
            <button
              key={item.name}
              type="button"
              role="menuitem"
              tabIndex={-1}
              className={styles.menuItem}
              aria-describedby={`${menuId}-${item.name}`}
              onClick={() => choose(item.name)}
            >
              <span>{item.name}</span>
              <span id={`${menuId}-${item.name}`} className={styles.menuHint}>{item.hint}</span>
            </button>
          ))}
          {onCreateExpression && (
            <button
              type="button"
              role="menuitem"
              tabIndex={-1}
              className={styles.menuItem}
              onClick={() => {
                close();
                setCreating(true);
              }}
            >
              New expression…
            </button>
          )}
        </div>
      )}
      {onCreateExpression && (
        <NewExpressionDialog
          open={creating}
          customNames={Object.keys(customExpressions)}
          onClose={() => setCreating(false)}
          onCreate={(name, hint) => {
            setCreating(false);
            const created = onCreateExpression(name, hint);
            if (created instanceof Promise) {
              void created.then((ok) => {
                if (ok !== false) onInsert(name);
              });
            } else if (created !== false) onInsert(name);
          }}
        />
      )}
    </div>
  );
}
