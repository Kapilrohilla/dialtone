import { Node, mergeAttributes } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import type { MarkdownNodeSpec } from "tiptap-markdown";
import { exprLabel, isBuiltin, tokenText } from "@/lib/tokens";
import styles from "./editor.module.css";

export type ExprChipOptions = {
  /** Read on every render, so the editor can follow the agent's custom expressions as they change. */
  isCustom: (name: string) => boolean;
};

/** Dispatch a transaction with this meta to re-mark chips after the custom expressions change. */
export const exprChipRefresh = new PluginKey("exprChipRefresh");

type Attrs = { name: string; seconds: number | null };

/** `[[expr:laugh]]` / `[[expr:pause:1.2]]` as an inline chip showing `[laugh]` / `[pause 1.2s]`. */
export const ExprChipNode = Node.create<ExprChipOptions>({
  name: "exprChip",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  addOptions() {
    return { isCustom: () => false };
  },

  addAttributes() {
    return {
      name: { default: "", parseHTML: (el) => el.getAttribute("data-expr") ?? "", renderHTML: (a) => ({ "data-expr": a.name }) },
      seconds: {
        default: null,
        parseHTML: (el) => {
          const v = el.getAttribute("data-seconds");
          return v === null || v === "" ? null : Number(v);
        },
        renderHTML: (a) => (a.seconds === null ? {} : { "data-seconds": String(a.seconds) }),
      },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-expr]" }];
  },

  renderHTML({ node, HTMLAttributes }) {
    const { name, seconds } = node.attrs as Attrs;
    return ["span", mergeAttributes(HTMLAttributes, { class: `${styles.chip} ${styles.expr}` }), `[${exprLabel({ name, seconds: seconds ?? undefined })}]`];
  },

  renderText({ node }) {
    return `[${exprLabel({ name: node.attrs.name, seconds: node.attrs.seconds ?? undefined })}]`;
  },

  addStorage() {
    return {
      markdown: {
        serialize(state, node) {
          const { name, seconds } = node.attrs as Attrs;
          state.write(tokenText({ kind: "expr", name, ...(seconds === null ? {} : { seconds }) }));
        },
      } satisfies MarkdownNodeSpec,
    };
  },

  addProseMirrorPlugins() {
    const { isCustom } = this.options;
    return [
      new Plugin({
        key: exprChipRefresh,
        props: {
          // Custom expressions get the dashed whisper tint; names the agent doesn't know get the bad tint.
          decorations(state) {
            const marks: Decoration[] = [];
            state.doc.descendants((node, pos) => {
              if (node.type.name !== "exprChip" || isBuiltin(node.attrs.name)) return;
              const attrs = isCustom(node.attrs.name)
                ? { class: styles.custom }
                : { class: styles.unknown, title: "Unknown expression" };
              marks.push(Decoration.node(pos, pos + node.nodeSize, attrs));
            });
            return DecorationSet.create(state.doc, marks);
          },
        },
      }),
    ];
  },
});
