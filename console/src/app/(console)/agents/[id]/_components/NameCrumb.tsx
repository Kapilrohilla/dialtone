"use client";

import { useRef, useState } from "react";
import styles from "./editor.module.css";

export type NameCrumbProps = { name: string; editable: boolean; onSave: (name: string) => void };

/** The agent's name in the breadcrumb: a text button that turns into an input. Enter or blur saves, Escape cancels. */
export function NameCrumb({ name, editable, onSave }: NameCrumbProps) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(name);
  const done = useRef(false);

  if (!editable) return <span>{name}</span>;
  if (!editing) {
    return (
      <button
        type="button"
        className={styles.nameButton}
        aria-label={`Rename ${name}`}
        onClick={() => {
          done.current = false;
          setValue(name);
          setEditing(true);
        }}
      >
        {name}
      </button>
    );
  }

  function finish(save: boolean) {
    if (done.current) return;
    done.current = true;
    setEditing(false);
    const next = value.trim();
    if (save && next && next !== name) onSave(next);
  }

  return (
    <input
      className={styles.nameInput}
      aria-label="Agent name"
      value={value}
      maxLength={200}
      autoFocus
      onChange={(e) => setValue(e.target.value)}
      onBlur={() => finish(true)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          finish(true);
        } else if (e.key === "Escape") {
          e.preventDefault();
          finish(false);
        }
      }}
    />
  );
}
