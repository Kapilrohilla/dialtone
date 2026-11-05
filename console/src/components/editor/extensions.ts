import { Extension, Node, type AnyExtension } from "@tiptap/core";
import { Table, TableCell, TableHeader, TableRow } from "@tiptap/extension-table";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "tiptap-markdown";
import { ExprChipNode } from "./ExprChipNode";
import { VarChipNode } from "./VarChipNode";

export type TokenEditorMode = "script" | "document" | "line";

/** Nothing beyond what a spoken line needs: no code, links, quotes, rules or strike. */
const SPOKEN = {
  blockquote: false,
  code: false,
  codeBlock: false,
  horizontalRule: false,
  link: false,
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
  const markdown = Markdown.configure({ html: true, tightLists: true, bulletListMarker: "-", linkify: false, breaks: false });

  if (mode === "line") {
    return [
      StarterKit.configure({
        ...SPOKEN,
        document: false,
        bold: false,
        italic: false,
        bulletList: false,
        orderedList: false,
        listItem: false,
        listKeymap: false,
        heading: false,
        hardBreak: false,
      }),
      LineDocument,
      SingleLine,
      ...chips,
      markdown,
    ];
  }
  if (mode === "script") {
    return [StarterKit.configure({ ...SPOKEN, heading: false, orderedList: false }), ...chips, markdown];
  }
  // Knowledge documents keep whatever Markdown they arrive with; the toolbar offers H2/H3 and tables.
  return [
    StarterKit.configure({ heading: { levels: [1, 2, 3] }, link: { openOnClick: false } }),
    Table.configure({ resizable: false }),
    TableRow,
    TableHeader,
    TableCell,
    ...chips,
    markdown,
  ];
}
