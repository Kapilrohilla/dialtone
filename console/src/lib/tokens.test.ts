import { describe, expect, it } from "vitest";
import { BUILTIN_EXPRESSIONS, BUILTIN_HINTS, MAX_PAUSE_S, exprLabel, parse, serialize, validateExpressionName } from "./tokens";

describe("tokens", () => {
  it("parses and serializes every token kind", () => {
    const s = "[[expr:happy]]नमस्ते! [[expr:pause:1.2]]क्या मेरी बात {{lead.name}} जी से हो रही है?";
    expect(serialize(parse(s))).toBe(s);
    expect(parse(s).filter((t) => t.kind !== "text")).toEqual([
      { kind: "expr", name: "happy" },
      { kind: "expr", name: "pause", seconds: 1.2 },
      { kind: "var", path: "lead.name" },
    ]);
  });

  it("treats malformed tokens as text", () =>
    expect(parse("[[expr:Laugh]] {{lead}}")).toEqual([{ kind: "text", text: "[[expr:Laugh]] {{lead}}" }]));

  it("normalises spaces inside variables", () => expect(serialize(parse("{{ lead.city }}"))).toBe("{{lead.city}}"));

  it("parses repeatedly without regex state leaking", () => {
    expect(parse("{{lead.city}}")).toEqual([{ kind: "var", path: "lead.city" }]);
    expect(parse("{{lead.city}}")).toEqual([{ kind: "var", path: "lead.city" }]);
  });

  it("labels expressions the way chips show them", () => {
    expect(exprLabel({ kind: "expr", name: "pause", seconds: 1.2 })).toBe("pause 1.2s");
    expect(exprLabel({ kind: "expr", name: "pause" })).toBe("pause 1s");
    expect(exprLabel({ kind: "expr", name: "laugh" })).toBe("laugh");
  });

  it("mirrors the server's built-ins and pause limit", () => {
    expect(BUILTIN_EXPRESSIONS).toEqual(["happy", "laugh", "sad", "fear", "angry", "whisper", "pause", "excited"]);
    expect(Object.keys(BUILTIN_HINTS)).toEqual([...BUILTIN_EXPRESSIONS]);
    expect(BUILTIN_HINTS.pause).toBe("pause for about {seconds} seconds before this");
    expect(MAX_PAUSE_S).toBe(10);
  });

  it("validates custom expression names with the server's wording", () => {
    expect(validateExpressionName("calm")).toBeNull();
    expect(validateExpressionName("laugh")).toBe('"laugh" is a built-in expression; pick another name.');
    expect(validateExpressionName("Calm")).toBe('"Calm" is not a valid expression name: use lowercase letters and underscores.');
    expect(validateExpressionName("a".repeat(33))).toMatch(/is not a valid expression name/);
  });
});
