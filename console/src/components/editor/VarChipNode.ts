import { Node, mergeAttributes } from "@tiptap/core";
import type { MarkdownNodeSpec } from "tiptap-markdown";
import { tokenText } from "@/lib/tokens";
import styles from "./editor.module.css";

/** `{{lead.city}}` as an inline chip. */
export const VarChipNode = Node.create({
  name: "varChip",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  addAttributes() {
    return {
      path: { default: "", parseHTML: (el) => el.getAttribute("data-var") ?? "", renderHTML: (a) => ({ "data-var": a.path }) },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-var]" }];
  },

  renderHTML({ node, HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes, { class: `${styles.chip} ${styles.variable}` }), `{{${node.attrs.path}}}`];
  },

  renderText({ node }) {
    return `{{${node.attrs.path}}}`;
  },

  addStorage() {
    return {
      markdown: {
        serialize(state, node) {
          state.write(tokenText({ kind: "var", path: node.attrs.path }));
        },
      } satisfies MarkdownNodeSpec,
    };
  },
});
