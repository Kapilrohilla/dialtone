import { useId, type ComponentProps, type ReactNode } from "react";
import { cx } from "./util";
import styles from "./Field.module.css";

type Common = { label: string; hint?: ReactNode; error?: string | null; className?: string };

export type FieldProps =
  | (Common & { control?: "input" } & Omit<ComponentProps<"input">, "className">)
  | (Common & { control: "textarea" } & Omit<ComponentProps<"textarea">, "className">)
  | (Common & { control: "select" } & Omit<ComponentProps<"select">, "className">);

/** A labelled input, textarea or select with an optional hint and an error in plain words. */
export function Field(props: FieldProps) {
  const { label, hint, error, className, control = "input", ...rest } = props;
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const shared = {
    id,
    className: cx(styles.control, control === "textarea" && styles.textarea, error && styles.invalid),
    "aria-invalid": error ? true : undefined,
    "aria-describedby": [hint ? hintId : "", error ? errorId : ""].filter(Boolean).join(" ") || undefined,
  };
  return (
    <div className={cx(styles.field, className)}>
      <label htmlFor={id} className={styles.label}>{label}</label>
      {control === "select" ? (
        <select {...shared} {...(rest as ComponentProps<"select">)} />
      ) : control === "textarea" ? (
        <textarea {...shared} {...(rest as ComponentProps<"textarea">)} />
      ) : (
        <input {...shared} {...(rest as ComponentProps<"input">)} />
      )}
      {hint && <p id={hintId} className={styles.hint}>{hint}</p>}
      {error && <p id={errorId} className={styles.error}>{error}</p>}
    </div>
  );
}
