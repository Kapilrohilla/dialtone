import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { cx } from "./util";
import styles from "./Toast.module.css";

export type ToastTone = "ok" | "bad" | "neutral";
export type ToastAction = { label: string; onClick: () => void };
type Item = { id: number; text: string; tone: ToastTone; action?: ToastAction };

const Ctx = createContext<{ show: (text: string, tone?: ToastTone, action?: ToastAction) => void } | null>(null);

export function useToast() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useToast needs a <Toast> provider above it.");
  return ctx;
}

const LIFETIME_MS = 5000;

/** Provider plus the page's single polite live region. */
export function Toast({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Item[]>([]);
  const next = useRef(0);
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>());

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach(clearTimeout);
  }, []);

  const show = useCallback((text: string, tone: ToastTone = "neutral", action?: ToastAction) => {
    const id = next.current++;
    setItems((list) => [...list, { id, text, tone, action }]);
    const timer = setTimeout(() => {
      timers.current.delete(timer);
      setItems((list) => list.filter((i) => i.id !== id));
    }, LIFETIME_MS);
    timers.current.add(timer);
  }, []);

  return (
    <Ctx.Provider value={{ show }}>
      {children}
      <div role="status" aria-live="polite" className={styles.region}>
        {items.map((i) => (
          <p key={i.id} className={cx(styles.toast, styles[i.tone])}>
            {i.text}
            {i.action && (
              <button type="button" className={styles.action} onClick={i.action.onClick}>{i.action.label}</button>
            )}
          </p>
        ))}
      </div>
    </Ctx.Provider>
  );
}
