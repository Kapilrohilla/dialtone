import type { JSONContent } from "@tiptap/core";
import type { Node as PMNode } from "@tiptap/pm/model";
import { parse, tokenText, type Token } from "@/lib/tokens";

/** Script and line modes are plain text with chips: no Markdown. Each stored line is one paragraph and
 *  its text is kept byte for byte; only tokens become chips. */

function inline(line: string): JSONContent[] {
  return parse(line).flatMap((t): JSONContent[] => {
    if (t.kind === "text") return t.text ? [{ type: "text", text: t.text }] : [];
    if (t.kind === "var") return [{ type: "varChip", attrs: { path: t.path } }];
    return [{ type: "exprChip", attrs: { name: t.name, seconds: t.seconds ?? null } }];
  });
}

/** Stored text as editor content. `singleLine` keeps the whole value in one paragraph (line mode). */
export function textToDoc(value: string, singleLine: boolean): JSONContent {
  const lines = singleLine ? [value] : value.split("\n");
  return {
    type: "doc",
    content: lines.map((line) => {
      const content = inline(line);
      return content.length ? { type: "paragraph", content } : { type: "paragraph" };
    }),
  };
}

function nodeToken(node: PMNode): Token | null {
  if (node.isText) return { kind: "text", text: node.text ?? "" };
  if (node.type.name === "varChip") return { kind: "var", path: node.attrs.path };
  if (node.type.name === "exprChip") {
    const { name, seconds } = node.attrs;
    return seconds === null ? { kind: "expr", name } : { kind: "expr", name, seconds };
  }
  return null;
}

/** Editor content back to stored text: paragraphs joined with "\n", chips as their tokens. */
export function docToText(doc: PMNode): string {
  const lines: string[] = [];
  doc.forEach((paragraph) => {
    let line = "";
    paragraph.forEach((node) => {
      const t = nodeToken(node);
      if (t) line += tokenText(t);
    });
    lines.push(line);
  });
  return lines.join("\n");
}
