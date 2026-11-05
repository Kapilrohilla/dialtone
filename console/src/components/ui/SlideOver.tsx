import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { focusables } from "./util";
import styles from "./SlideOver.module.css";

export type SlideOverProps = { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode };

export function SlideOver({ open, ...rest }: SlideOverProps) {
  return open ? <OpenSlideOver {...rest} /> : null;
}

function OpenSlideOver({ onClose, title, children, footer }: Omit<SlideOverProps, "open">) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const panel = ref.current;
    if (panel) (focusables(panel).find((el) => el.dataset.close === undefined) ?? focusables(panel)[0] ?? panel).focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close.current();
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus();
    };
  }, []);

  return (
    <div ref={ref} role="dialog" aria-labelledby={titleId} tabIndex={-1} className={styles.panel}>
      <header className={styles.header}>
        <h2 id={titleId}>{title}</h2>
        <button type="button" data-close className={styles.close} aria-label="Close" onClick={onClose}>
          <X size={20} strokeWidth={1.75} aria-hidden="true" />
        </button>
      </header>
      <div className={styles.body}>{children}</div>
      {footer && <footer className={styles.footer}>{footer}</footer>}
    </div>
  );
}
