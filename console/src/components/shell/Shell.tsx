"use client";

import { useEffect, useState, type ReactNode } from "react";
import { StateBlock } from "@/components/ui";
import { useMe } from "@/lib/queries";
import { applyAppearance } from "@/lib/theme";
import { VoiceTestProvider } from "@/components/sim/VoiceTest";
import { Sidebar } from "./Sidebar";
import styles from "./Shell.module.css";

/** Renders `children` only after `ms`, so a quick load never flashes a skeleton. */
function Delayed({ ms, children }: { ms: number; children: ReactNode }) {
  const [show, setShow] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setShow(true), ms);
    return () => clearTimeout(t);
  }, [ms]);
  return show ? children : null;
}

export function Shell({ children }: { children: ReactNode }) {
  const { data: me, isError, error, refetch } = useMe();
  const appearance = me?.preferences.appearance;

  // Keeps the cv_theme cookie in step with the preference saved on another device.
  useEffect(() => {
    if (appearance) applyAppearance(appearance);
  }, [appearance]);

  if (!me) {
    if (isError) {
      return (
        <div className={styles.center}>
          <StateBlock state="error" title="Could not load your workspace" body={error.message} onRetry={() => void refetch()} />
        </div>
      );
    }
    return (
      <Delayed ms={300}>
        <div className={styles.skeleton} aria-busy="true" role="status">
          <span className="sr-only">Loading</span>
          <div className={styles.skSide} />
          <div className={styles.skMain}>
            <div className={styles.skBar} />
            <div className={styles.skRow} />
            <div className={styles.skRow} />
          </div>
        </div>
      </Delayed>
    );
  }

  return (
    // The voice test call lives here, so it carries on while you move between console pages.
    <VoiceTestProvider>
      <div className={styles.shell}>
        <Sidebar />
        <main className={styles.main}>{children}</main>
      </div>
    </VoiceTestProvider>
  );
}
