import { useId, useState, type FormEvent } from "react";
import { Button, Dialog, Field } from "@/components/ui";
import { MAX_HINT_LENGTH, validateExpressionName, validateHint } from "@/lib/tokens";
import styles from "./editor.module.css";

export type NewExpressionDialogProps = {
  open: boolean;
  /** The agent's existing custom names, which a new one may not repeat. */
  customNames: string[];
  onClose: () => void;
  onCreate: (name: string, hint: string) => void;
};

export function NewExpressionDialog({ open, ...rest }: NewExpressionDialogProps) {
  return open ? <NewExpressionForm {...rest} /> : null;
}

function NewExpressionForm({ customNames, onClose, onCreate }: Omit<NewExpressionDialogProps, "open">) {
  const formId = useId();
  const [name, setName] = useState("");
  const [hint, setHint] = useState("");
  const [errors, setErrors] = useState<{ name?: string | null; hint?: string | null }>({});

  function submit(e: FormEvent) {
    e.preventDefault();
    const nameError = customNames.includes(name)
      ? `You already have an expression called "${name}".`
      : validateExpressionName(name);
    const hintError = validateHint(name, hint);
    setErrors({ name: nameError, hint: hintError });
    if (!nameError && !hintError) onCreate(name, hint.trim());
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="New expression"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form={formId}>Add expression</Button>
        </>
      }
    >
      <form id={formId} className={styles.form} onSubmit={submit} noValidate>
        <Field
          label="Name"
          hint="Lowercase letters and underscores, up to 32."
          error={errors.name}
          value={name}
          maxLength={32}
          autoComplete="off"
          autoFocus
          onChange={(e) => setName(e.target.value)}
        />
        <Field
          label="How to say it"
          control="textarea"
          hint={`Up to ${MAX_HINT_LENGTH} characters, for example "say this slowly and calmly".`}
          error={errors.hint}
          value={hint}
          maxLength={MAX_HINT_LENGTH}
          onChange={(e) => setHint(e.target.value)}
        />
      </form>
    </Dialog>
  );
}
