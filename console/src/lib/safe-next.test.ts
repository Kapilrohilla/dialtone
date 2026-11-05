import { describe, expect, it } from "vitest";
import { safeNext } from "./safe-next";

describe("safeNext", () => {
  it("keeps same-site paths, including a query", () => {
    expect(safeNext("/agents")).toBe("/agents");
    expect(safeNext("/agents?x=1")).toBe("/agents?x=1");
  });
  it.each([["/\\evil"], ["https://x"], ["//x"], [""], [null], ["agents"]])("falls back to / for %j", (v) => {
    expect(safeNext(v)).toBe("/");
  });
});
