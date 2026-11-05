import { Extension, Node, type Editor, type JSONContent } from "@tiptap/core";
import type { MarkdownNodeSpec, MarkdownStorage } from "tiptap-markdown";
import { TOKEN_SOURCE, parse } from "@/lib/tokens";
import { docToText, textToDoc } from "./plainText";
import type { TokenEditorMode } from "./extensions";

/** Document (knowledge) mode keeps Markdown. Three rules keep what the agent reads intact:
 *  - markdown-it runs with `html: false`, so user text is never taken for HTML; chips come from an inline
 *    rule that turns each token into the span its chip node parses;
 *  - text is written back unescaped unless writing it raw would parse differently;
 *  - single newlines are hard breaks and come back as "\n". */

type MarkdownIt = {
  parse: (src: string, env: object) => MdToken[];
  parseInline: (src: string, env: object) => MdToken[];
  inline: { ruler: { before: (name: string, rule: string, fn: InlineRule) => void; getRules: (chain: string) => unknown[] } };
};
type MdToken = { type: string; content: string; children: MdToken[] | null };
type InlineState = { src: string; pos: number; push: (type: string, tag: string, nesting: number) => MdToken };
type InlineRule = (state: InlineState, silent: boolean) => boolean;
type SerializerState = {
  text: (text: string, escape?: boolean) => void;
  write: (content?: string) => void;
  esc: (str: string, startOfLine?: boolean) => string;
  atBlockStart: boolean;
  inTable?: boolean;
};

const attr = (v: string) => v.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
const TOKEN_AT = new RegExp(`^(?:${TOKEN_SOURCE})`);
const installed = new WeakSet<object>();

const chipRule: InlineRule = (state, silent) => {
  const first = state.src[state.pos];
  if (first !== "[" && first !== "{") return false;
  const m = TOKEN_AT.exec(state.src.slice(state.pos));
  if (!m) return false;
  if (!silent) {
    const [t] = parse(m[0]);
    const token = state.push("html_inline", "", 0);
    token.content =
      t.kind === "var"
        ? `<span data-var="${attr(t.path)}"></span>`
        : t.kind === "expr"
          ? `<span data-expr="${attr(t.name)}"${t.seconds === undefined ? "" : ` data-seconds="${t.seconds}"`}></span>`
          : "";
  }
  state.pos += m[0].length;
  return true;
};

/** Registers the chip rule with tiptap-markdown's markdown-it instance (once per instance). */
export const MarkdownChips = Extension.create({
  name: "markdownChips",
  addStorage() {
    return {
      markdown: {
        parse: {
          setup(md: MarkdownIt) {
            if (installed.has(md)) return;
            installed.add(md);
            md.inline.ruler.before("link", "carrum_chip", chipRule);
          },
        },
      },
    };
  },
});

const markdownIt = (editor: Editor) =>
  (editor.storage as unknown as { markdown: MarkdownStorage & { parser: { md: MarkdownIt } } }).markdown.parser.md;

/** True when `text` written raw would read back as exactly this plain text. */
function readsBackAsIs(md: MarkdownIt, text: string, atBlockStart: boolean): boolean {
  let inlineToken: MdToken | undefined;
  if (atBlockStart) {
    const blocks = md.parse(text, {});
    if (blocks.length !== 3 || blocks[0].type !== "paragraph_open") return false;
    inlineToken = blocks[1];
  } else {
    inlineToken = md.parseInline(text, {})[0];
  }
  const children = inlineToken?.children ?? [];
  return children.every((c) => c.type === "text") && children.map((c) => c.content).join("") === text;
}

/** Plain text, escaped only where Markdown would otherwise misread it. */
export const MarkdownText = Node.create({
  name: "text",
  group: "inline",
  addStorage() {
    return {
      markdown: {
        serialize(state, node) {
          const s = state as unknown as SerializerState;
          const text = node.text ?? "";
          const pipe = s.inTable && text.includes("|");
          if (!pipe && readsBackAsIs(markdownIt(this.editor), text, s.atBlockStart)) {
            s.text(text, false);
            return;
          }
          let escaped = s.esc(text, s.atBlockStart).replace(/&(?=#?\w+;)/g, "\\&").replace(/</g, "\\<");
          if (s.inTable) escaped = escaped.replace(/\|/g, "\\|");
          s.text(escaped, false);
        },
      } satisfies MarkdownNodeSpec,
    };
  },
});

/** A line break inside a paragraph, stored as a plain "\n" (Shift-Enter). */
export const MarkdownHardBreak = Node.create({
  name: "hardBreak",
  inline: true,
  group: "inline",
  selectable: false,
  linebreakReplacement: true,
  parseHTML() {
    return [{ tag: "br" }];
  },
  renderHTML() {
    return ["br"];
  },
  renderText() {
    return "\n";
  },
  addKeyboardShortcuts() {
    return { "Shift-Enter": () => this.editor.commands.insertContent({ type: this.name }) };
  },
  addStorage() {
    return {
      markdown: {
        serialize(state, node, parent, index) {
          const s = state as unknown as SerializerState;
          // A break at the end of a paragraph writes nothing; inside a table cell a newline would end the row.
          for (let i = index + 1; i < parent.childCount; i++) {
            if (parent.child(i).type !== node.type) {
              s.write(s.inTable ? " " : "\n");
              return;
            }
          }
        },
      } satisfies MarkdownNodeSpec,
    };
  },
});

/** Stored text as editor content for `mode`: Markdown for documents, paragraphs of chips otherwise. */
export function toEditorContent(value: string, mode: TokenEditorMode): string | JSONContent {
  return mode === "document" ? value : textToDoc(value, mode === "line");
}

/** The editor's content as stored token text. Documents serialize as Markdown (minus the trailing newline
 *  the serializer leaves after a closing table); script and line modes as plain lines. */
export function fromEditor(editor: Editor): string {
  const storage = (editor.storage as unknown as { markdown?: MarkdownStorage }).markdown;
  return storage ? storage.getMarkdown().replace(/\n+$/, "") : docToText(editor.state.doc);
}
