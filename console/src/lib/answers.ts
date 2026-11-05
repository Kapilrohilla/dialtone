/** Plain-words labels for the details the agent captures during a call (`captured` live, `answers` in history). */
export const ANSWER_LABELS: Record<string, string> = {
  callback_time: "Call back at",
  city: "City",
  licence: "Licence",
  experience: "Experience",
  uber_id: "Uber ID",
  preferred_plan: "Preferred plan",
  main_question: "Main question",
};

/** The label for a captured key; unknown keys become sentence case ("driving_years" → "Driving years"). */
export function answerLabel(key: string): string {
  if (Object.hasOwn(ANSWER_LABELS, key)) return ANSWER_LABELS[key];
  const words = key.replace(/[_\s]+/g, " ").trim().toLowerCase();
  return words ? words[0].toUpperCase() + words.slice(1) : key;
}
