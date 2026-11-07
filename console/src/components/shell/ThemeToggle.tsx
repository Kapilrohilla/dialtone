"use client";

import { Moon } from "lucide-react";
import { useToast } from "@/components/ui";
import { useMe, useUpdateMe } from "@/lib/queries";
import { applyAppearance } from "@/lib/theme";
import type { Appearance } from "@/lib/types";
import styles from "./ThemeToggle.module.css";

/** What the page looks like right now: "system" follows the OS. */
function effective(a: Appearance): "light" | "dark" {
  if (a !== "system") return a;
  return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function ThemeToggle() {
  const { data: me } = useMe();
  const update = useUpdateMe();
  const toast = useToast();
  if (!me) return null;
  const current = effective(me.preferences.appearance);
  const next = current === "dark" ? "light" : "dark";

  function flip() {
    const previous = me!.preferences.appearance;
    applyAppearance(next);
    update.mutate(
      { preferences: { appearance: next } },
      {
        onError: () => {
          applyAppearance(previous);
          toast.show("Could not save your appearance. Try again.", "bad");
        },
      },
    );
  }

  return (
    <button type="button" role="switch" aria-checked={current === "dark"} className={styles.toggle} onClick={flip}>
      <Moon size={18} strokeWidth={1.75} aria-hidden="true" />
      <span className={styles.label}>Dark mode</span>
      <span className={styles.track} aria-hidden="true">
        <span className={styles.thumb} />
      </span>
    </button>
  );
}
