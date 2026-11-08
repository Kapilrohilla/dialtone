"use client";

import { Plus, X } from "lucide-react";
import { useState } from "react";
import styles from "./workflow.module.css";

export const MAX_PHRASES = 5;
export const MAX_PHRASE_CHARS = 40;

export type PhraseChipsProps = {
  /** Names the list for screen readers, e.g. "Caller phrases for Has licence". */
  label: string;
  value: string[];
  readOnly?: boolean;
  onChange: (next: string[]) => void;
};

/** Caller phrases as removable chips with an "Add phrase" input: at most 5, 40 characters each, no repeats. */
export function PhraseChips({ label, value, readOnly, onChange }: PhraseChipsProps) {
  const [adding, setAdding] = useState(false);
  const [text, setText] = useState("");
  const full = value.length >= MAX_PHRASES;

  function commit() {
    const phrase = text.trim();
    if (phrase && !value.includes(phrase) && !full) onChange([...value, phrase]);
    setText("");
    setAdding(false);
  }

  if (readOnly && value.length === 0) return null;
  return (
    <div className={styles.phrases}>
      <ul className={styles.phraseList} aria-label={label}>
        {value.map((p) => (
          <li key={p} className={styles.phrase}>
            <span>&ldquo;{p}&rdquo;</span>
            {!readOnly && (
              <button type="button" className={styles.phraseRemove} aria-label={`Remove phrase ${p}`} onClick={() => onChange(value.filter((x) => x !== p))}>
                <X size={14} strokeWidth={1.75} aria-hidden="true" />
              </button>
            )}
          </li>
        ))}
      </ul>
      {!readOnly && adding && (
        <input
          className={styles.input}
          aria-label={`New phrase for ${label}`}
          autoFocus
          value={text}
          maxLength={MAX_PHRASE_CHARS}
          placeholder="What a caller might say"
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              commit();
            } else if (e.key === "Escape") {
              e.preventDefault();
              setText("");
              setAdding(false);
            }
          }}
        />
      )}
      {!readOnly && !adding && !full && (
        <button type="button" className={styles.linkButton} onClick={() => setAdding(true)}>
          <Plus size={14} strokeWidth={1.75} aria-hidden="true" />
          Add phrase
        </button>
      )}
    </div>
  );
}
