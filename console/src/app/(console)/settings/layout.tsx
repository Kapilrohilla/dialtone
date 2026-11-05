import type { ReactNode } from "react";
import { SettingsNav } from "./_components/SettingsNav";
import styles from "./settings.module.css";

export default function SettingsLayout({ children }: { children: ReactNode }) {
  return (
    <div className={styles.layout}>
      <SettingsNav />
      <div className={styles.content}>{children}</div>
    </div>
  );
}
