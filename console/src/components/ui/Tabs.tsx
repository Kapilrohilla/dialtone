import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import styles from "./Tabs.module.css";

export type TabsProps<T extends string> = {
  label: string;
  tabs: { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
  /** The content of the selected tab. */
  children?: ReactNode;
};

export function Tabs<T extends string>({ label, tabs, value, onChange, children }: TabsProps<T>) {
  const base = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(e: KeyboardEvent, index: number) {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    const target = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : step ? (index + step + tabs.length) % tabs.length : -1;
    if (target < 0) return;
    e.preventDefault();
    onChange(tabs[target].id);
    refs.current[target]?.focus();
  }

  return (
    <div>
      <div role="tablist" aria-label={label} className={styles.list}>
        {tabs.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            id={`${base}-tab-${t.id}`}
            type="button"
            role="tab"
            aria-selected={t.id === value}
            aria-controls={`${base}-panel`}
            tabIndex={t.id === value ? 0 : -1}
            className={styles.tab}
            onClick={() => onChange(t.id)}
            onKeyDown={(e) => onKeyDown(e, i)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {children !== undefined && (
        <div id={`${base}-panel`} role="tabpanel" aria-labelledby={`${base}-tab-${value}`} className={styles.panel}>
          {children}
        </div>
      )}
    </div>
  );
}
