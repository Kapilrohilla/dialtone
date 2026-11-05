import { Fragment } from "react";
import { cx } from "@/components/ui/util";
import { exprLabel, isBuiltin, parse } from "@/lib/tokens";
import styles from "./editor.module.css";

export type ChipTextProps = {
  /** Plain text that may hold `[[expr:…]]` and `{{lead.…}}` tokens. */
  text: string;
  /** The agent's custom expression names; any other non built-in name gets the unknown tint. Omit to tint every
   *  non built-in name as custom (when the speaker's expressions aren't known). */
  customExpressions?: Record<string, string>;
};

/** Read-only text with tokens shown as the editor's chips. */
export function ChipText({ text, customExpressions }: ChipTextProps) {
  return (
    <>
      {parse(text).map((t, i) => {
        if (t.kind === "text") return <Fragment key={i}>{t.text}</Fragment>;
        if (t.kind === "var") return <span key={i} className={cx(styles.chip, styles.variable)}>{`{{${t.path}}}`}</span>;
        const known = isBuiltin(t.name);
        const custom = !known && (!customExpressions || t.name in customExpressions);
        return (
          <span
            key={i}
            data-expr={t.name}
            title={!known && !custom ? "Unknown expression" : undefined}
            className={cx(styles.chip, styles.expr, custom && styles.custom, !known && !custom && styles.unknown)}
          >
            [{exprLabel(t)}]
          </span>
        );
      })}
    </>
  );
}
