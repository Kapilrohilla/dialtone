import { Extension, Node, type AnyExtension } from "@tiptap/core";
import { Table, TableCell, TableHeader, TableRow } from "@tiptap/extension-table";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "tiptap-markdown";
import { ExprChipNode } from "./ExprChipNode";
import { MarkdownChips, MarkdownHardBreak, MarkdownText } from "./markdown";
import { VarChipNode } from "./VarChipNode";

export type TokenEditorMode = "script" | "document" | "line";

/** Script and line modes are plain text: paragraphs (one per stored line), text and chips, nothing else. */
const PLAIN = {
  blockquote: false,
  bold: false,
  bulletList: false,
  code: false,
  codeBlock: false,
  hardBreak: false,
  heading: false,
  horizontalRule: false,
  italic: false,
  link: false,
  listItem: false,
  listKeymap: false,
  orderedList: false,
  strike: false,
  underline: false,
  trailingNode: false,
} as const;

/** A workflow prompt is one paragraph: the document holds exactly one, and Enter does nothing. */
const LineDocument = Node.create({ name: "doc", topNode: true, content: "paragraph" });

const SingleLine = Extension.create({
  name: "singleLine",
  priority: 1000,
  addKeyboardShortcuts() {
    return { Enter: () => true, "Shift-Enter": () => true, "Mod-Enter": () => true };
  },
});

export function editorExtensions(mode: TokenEditorMode, isCustom: (name: string) => boolean): AnyExtension[] {
  const chips = [ExprChipNode.configure({ isCustom }), VarChipNode];

  if (mode === "line") return [StarterKit.configure({ ...PLAIN, document: false }), LineDocument, SingleLine, ...chips];
  if (mode === "script") return [StarterKit.configure(PLAIN), ...chips];

  // Knowledge documents: Markdown, keeping whatever it arrives with; the toolbar offers H2/H3 and tables.
  return [
    StarterKit.configure({ text: false, hardBreak: false, link: { openOnClick: false } }),
    MarkdownText,
    MarkdownHardBreak,
    Table.configure({ resizable: false }),
    TableRow,
    TableHeader,
    TableCell,
    ...chips,
    MarkdownChips,
    Markdown.configure({ html: false, tightLists: true, bulletListMarker: "-", linkify: false, breaks: true }),
  ];
}
