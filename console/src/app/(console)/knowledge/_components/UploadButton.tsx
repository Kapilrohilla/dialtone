import { useRef } from "react";
import { Button } from "@/components/ui";
import { useUploadDoc } from "@/lib/queries";
import type { KnowledgeDoc } from "@/lib/types";
import styles from "../knowledge.module.css";

/** Outlined "Upload .md". The file goes to the API as is; its file errors are toasted by the hook. */
export function UploadButton({ onUploaded }: { onUploaded: (doc: KnowledgeDoc) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const upload = useUploadDoc();
  return (
    <>
      <Button loading={upload.isPending} onClick={() => input.current?.click()}>
        Upload .md
      </Button>
      <input
        ref={input}
        type="file"
        accept=".md,text/markdown"
        className={styles.srOnly}
        tabIndex={-1}
        aria-label="Markdown file"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) upload.mutate(file, { onSuccess: onUploaded });
        }}
      />
    </>
  );
}
