import type { ButtonHTMLAttributes } from "react";
import { Spinner } from "./Spinner";
import { cx } from "./util";
import styles from "./Button.module.css";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "outline" | "danger" | "text";
  /** md is the 40px control height; sm is 32px for dense rows. */
  size?: "md" | "sm";
  loading?: boolean;
};

export function Button({ variant = "outline", size = "md", loading = false, disabled, className, children, type = "button", ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      className={cx(styles.button, styles[variant], size === "sm" && styles.sm, className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading && <Spinner />}
      {children}
    </button>
  );
}
