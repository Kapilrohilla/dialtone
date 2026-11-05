import { Braces } from "lucide-react";
import { useId, useState, type FormEvent } from "react";
import { Button } from "@/components/ui";
import { VAR_PATH_RE } from "@/lib/tokens";
import { usePopover } from "./usePopover";
import styles from "./editor.module.css";

export type VariableMenuProps = { onInsert: (path: string) => void };

const COMMON = [
  { label: "Lead name", path: "lead.name" },
  { label: "Lead city", path: "lead.city" },
];

export function VariableMenu({ onInsert }: VariableMenuProps) {
  const { open, setOpen, close, root, trigger, onKeyDown } = usePopover();
  const [other, setOther] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const menuId = useId();

  function toggle() {
    setOther(null);
    setError(null);
    setOpen((o) => !o);
  }

  function choose(path: string) {
    close();
    onInsert(path);
  }

  function submitOther(e: FormEvent) {
    e.preventDefault();
    const path = `lead.${other ?? ""}`;
    if (!VAR_PATH_RE.test(path)) setError("Use lowercase letters and underscores.");
    else choose(path);
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
        onClick={toggle}
      >
        <Braces size={16} strokeWidth={1.75} aria-hidden="true" />
        Variable
      </button>
      {open && (
        <div id={menuId} className={styles.menu} onKeyDown={onKeyDown}>
          {other === null ? (
            <div role="menu" aria-label="Variables" className={styles.menuList}>
              {COMMON.map((v) => (
                <button key={v.path} type="button" role="menuitem" tabIndex={-1} className={styles.menuItem} onClick={() => choose(v.path)}>
                  <span>{v.label}</span>
                  <span className={styles.menuHint}>{v.path}</span>
                </button>
              ))}
              <button type="button" role="menuitem" tabIndex={-1} className={styles.menuItem} onClick={() => setOther("")}>
                Other…
              </button>
            </div>
          ) : (
            <form className={styles.otherForm} onSubmit={submitOther} noValidate>
              <label htmlFor={`${menuId}-field`} className={styles.otherLabel}>Lead field</label>
              <div className={styles.otherRow}>
                <span className={styles.prefix} aria-hidden="true">lead.</span>
                <input
                  id={`${menuId}-field`}
                  className={styles.otherInput}
                  value={other}
                  autoFocus
                  autoComplete="off"
                  aria-invalid={error ? true : undefined}
                  aria-describedby={error ? `${menuId}-error` : undefined}
                  onChange={(e) => setOther(e.target.value)}
                />
                <Button size="sm" type="submit">Insert</Button>
              </div>
              {error && <p id={`${menuId}-error`} className={styles.error}>{error}</p>}
            </form>
          )}
          <p className={styles.menuNote}>Filled from the lead when the call has one; otherwise the agent says it without the name.</p>
        </div>
      )}
    </div>
  );
}
