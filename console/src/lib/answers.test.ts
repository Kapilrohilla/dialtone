import { describe, expect, it } from "vitest";
import { ANSWER_LABELS, answerLabel } from "./answers";

describe("answerLabel", () => {
  it("uses the known labels", () => {
    expect(ANSWER_LABELS.callback_time).toBe("Call back at");
    expect(answerLabel("uber_id")).toBe("Uber ID");
    expect(answerLabel("main_question")).toBe("Main question");
  });

  it("sentence-cases unknown keys", () => {
    expect(answerLabel("driving_years")).toBe("Driving years");
    expect(answerLabel("EXTRA_NOTES")).toBe("Extra notes");
    expect(answerLabel("")).toBe("");
  });

  it("does not treat object prototype names as known", () => {
    expect(answerLabel("constructor")).toBe("Constructor");
  });
});
