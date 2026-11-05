"use client";

import { Moon, Sun } from "lucide-react";
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
  const Icon = current === "dark" ? Sun : Moon;

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
    <button type="button" className={styles.toggle} aria-label={`Switch to ${next}`} onClick={flip}>
      <Icon size={20} strokeWidth={1.75} aria-hidden="true" />
    </button>
  );
}
