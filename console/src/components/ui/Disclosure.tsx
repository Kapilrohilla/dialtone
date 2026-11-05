import { ChevronDown, ChevronRight } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import styles from "./Disclosure.module.css";

export type DisclosureProps = { title?: string; defaultOpen?: boolean; children: ReactNode };

export function Disclosure({ title = "Advanced", defaultOpen = false, children }: DisclosureProps) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <div>
      <button type="button" className={styles.toggle} aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        <Icon size={18} strokeWidth={1.75} aria-hidden="true" />
        {title}
      </button>
      {open && (
        <div id={id} className={styles.body}>
          {children}
        </div>
      )}
    </div>
  );
}
