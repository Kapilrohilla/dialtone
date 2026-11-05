import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { focusables } from "./util";
import styles from "./Dialog.module.css";

export type DialogProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  /** Buttons at the bottom right. A dialog may have its own amber primary. */
  footer?: ReactNode;
};

export function Dialog({ open, ...rest }: DialogProps) {
  return open ? <OpenDialog {...rest} /> : null;
}

function OpenDialog({ onClose, title, children, footer }: Omit<DialogProps, "open">) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const opener = document.activeElement as HTMLElement | null;
    if (!dialog.open) dialog.showModal();
    (dialog.querySelector<HTMLElement>("[autofocus]") ?? focusables(dialog)[0] ?? dialog).focus();
    return () => {
      if (dialog.open) dialog.close();
      opener?.focus();
    };
  }, []);

  function onKeyDown(e: KeyboardEvent<HTMLDialogElement>) {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "Tab") {
      const items = focusables(e.currentTarget);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  return (
    <dialog
      ref={ref}
      className={styles.dialog}
      aria-labelledby={titleId}
      onKeyDown={onKeyDown}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <h2 id={titleId} className={styles.title}>{title}</h2>
      <div className={styles.body}>{children}</div>
      {footer && <div className={styles.footer}>{footer}</div>}
    </dialog>
  );
}
