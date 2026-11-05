import { describe, expect, it } from "vitest";
import { applyAppearance, themeFromCookie } from "@/lib/theme";

describe("theme", () => {
  it("dark sets data-theme and the cookie; system clears both", () => {
    applyAppearance("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.cookie).toContain("cv_theme=dark");
    applyAppearance("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    applyAppearance("system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(document.cookie).not.toContain("cv_theme");
  });
  it("reads the cookie value", () => {
    expect(themeFromCookie("dark")).toBe("dark");
    expect(themeFromCookie("light")).toBe("light");
    expect(themeFromCookie("system")).toBeUndefined();
    expect(themeFromCookie(undefined)).toBeUndefined();
  });
});
