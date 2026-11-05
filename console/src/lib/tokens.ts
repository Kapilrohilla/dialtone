/** Script tokens, mirroring dashboard/voiceagents/tokens.py: `[[expr:name(:seconds)]]` expressions and
 *  `{{lead.field}}` variables. Everything else in a body is plain text. */

export const TOKEN_SOURCE = String.raw`\[\[expr:([a-z_]+)(?::(\d+(?:\.\d+)?))?\]\]|\{\{\s*(lead\.[a-z_]+)\s*\}\}`;

/** The server's token pattern (global). Use `new RegExp(TOKEN_RE)` when you need your own lastIndex. */
export const TOKEN_RE = new RegExp(TOKEN_SOURCE, "g");

export const BUILTIN_EXPRESSIONS = ["happy", "laugh", "sad", "fear", "angry", "whisper", "pause", "excited"] as const;
export type BuiltinExpression = (typeof BUILTIN_EXPRESSIONS)[number];

/** Verbatim from tokens.py. The pause hint keeps the server's `{seconds}` placeholder. */
export const BUILTIN_HINTS: Record<BuiltinExpression, string> = {
  happy: "say this warmly and cheerfully",
  laugh: "say this with a light, warm laugh",
  sad: "say this gently, with sympathy",
  fear: "say this with a careful, concerned tone",
  angry: "say this firmly but calmly, never rude",
  whisper: "say this softly, as if sharing something personal",
  pause: "pause for about {seconds} seconds before this",
  excited: "say this with energy and enthusiasm",
};

/** tokens.py MAX_PAUSE_SECONDS: longer pauses fail publish (long_pause_errors). */
export const MAX_PAUSE_S = 10;
export const MIN_PAUSE_S = 0.2;

/** serializers.py EXPR_NAME_RE and the hint limit for custom expressions. */
export const EXPR_NAME_RE = /^[a-z_]{1,32}$/;
export const MAX_HINT_LENGTH = 200;

/** Lead field paths accepted inside `{{ }}`. */
export const VAR_PATH_RE = /^lead\.[a-z_]+$/;

export type Token =
  | { kind: "text"; text: string }
  | { kind: "expr"; name: string; seconds?: number }
  | { kind: "var"; path: string };
export type ExprToken = Extract<Token, { kind: "expr" }>;

export const isBuiltin = (name: string): name is BuiltinExpression =>
  (BUILTIN_EXPRESSIONS as readonly string[]).includes(name);

export function parse(body: string): Token[] {
  const tokens: Token[] = [];
  let pos = 0;
  for (const m of body.matchAll(new RegExp(TOKEN_SOURCE, "g"))) {
    if (m.index > pos) tokens.push({ kind: "text", text: body.slice(pos, m.index) });
    if (m[1] !== undefined) {
      tokens.push(m[2] !== undefined ? { kind: "expr", name: m[1], seconds: Number(m[2]) } : { kind: "expr", name: m[1] });
    } else {
      tokens.push({ kind: "var", path: m[3] });
    }
    pos = m.index + m[0].length;
  }
  if (pos < body.length) tokens.push({ kind: "text", text: body.slice(pos) });
  return tokens;
}

/** One token's stored text: `[[expr:laugh]]`, `[[expr:pause:1.2]]`, `{{lead.city}}`. */
export function tokenText(t: Token): string {
  if (t.kind === "text") return t.text;
  if (t.kind === "var") return `{{${t.path}}}`;
  return t.seconds === undefined ? `[[expr:${t.name}]]` : `[[expr:${t.name}:${formatSeconds(t.seconds)}]]`;
}

export const serialize = (tokens: Token[]): string => tokens.map(tokenText).join("");

/** What a chip shows between its brackets: "pause 1.2s" or "laugh". A bare pause lasts 1 second on calls. */
export function exprLabel(t: Omit<ExprToken, "kind"> & { kind?: "expr" }): string {
  if (t.name === "pause") return `pause ${formatSeconds(t.seconds ?? 1)}s`;
  return t.name;
}

/** Shortest decimal for a seconds value, like Python's `:g` for the values we allow. */
export function formatSeconds(seconds: number): string {
  return String(Math.round(seconds * 1000) / 1000);
}

/** The server's error for a custom expression name, or null when it is acceptable. */
export function validateExpressionName(name: string): string | null {
  if (!EXPR_NAME_RE.test(name)) return `"${name}" is not a valid expression name: use lowercase letters and underscores.`;
  if (isBuiltin(name)) return `"${name}" is a built-in expression; pick another name.`;
  return null;
}

/** The server's error for a custom expression hint, or null when it is acceptable. */
export function validateHint(name: string, hint: string): string | null {
  if (!hint.trim() || hint.length > MAX_HINT_LENGTH) return `Expression "${name}" needs a hint of up to ${MAX_HINT_LENGTH} characters.`;
  return null;
}
