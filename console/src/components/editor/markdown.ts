import type { Editor } from "@tiptap/core";
import type { MarkdownStorage } from "tiptap-markdown";
import { parse } from "@/lib/tokens";

const attr = (v: string) => v.replace(/&/g, "&amp;").replace(/"/g, "&quot;");

/** Stored Markdown with each token swapped for the span its chip node parses, ready for tiptap-markdown (`html: true`). */
export function toEditorHtml(markdown: string): string {
  return parse(markdown)
    .map((t) => {
      if (t.kind === "text") return t.text;
      if (t.kind === "var") return `<span data-var="${attr(t.path)}"></span>`;
      const seconds = t.seconds === undefined ? "" : ` data-seconds="${t.seconds}"`;
      return `<span data-expr="${attr(t.name)}"${seconds}></span>`;
    })
    .join("");
}

/** The editor's content as stored token text (Markdown, chips back to `[[expr:…]]` / `{{lead.…}}`).
 *  The serializer ends a document that closes with a table in a newline; stored bodies never end in one. */
export function fromEditor(editor: Editor): string {
  const storage = (editor.storage as unknown as { markdown: MarkdownStorage }).markdown;
  return storage.getMarkdown().replace(/\n+$/, "");
}
