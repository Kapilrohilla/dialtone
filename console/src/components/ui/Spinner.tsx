import { LoaderCircle } from "lucide-react";
import styles from "./Spinner.module.css";

export function Spinner({ size = 16 }: { size?: number }) {
  return <LoaderCircle className={styles.spin} size={size} strokeWidth={1.75} aria-hidden="true" />;
}
