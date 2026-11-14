"""The fixed rubric a call audit scores against. Change RUBRIC_VERSION whenever the wording or areas change,
so scores from different rubrics are never compared as if they were the same."""

RUBRIC_VERSION = "2026-11-v1"

# (key, label, default weight %, what it checks, level descriptions 1..5)
AREAS = [
    (
        "naturalness", "Sounds human", 25,
        "Natural spoken phrasing for an Indian telecaller (Hindi, Hinglish or English, as the caller speaks), short "
        "spoken sentences, fitting fillers and acknowledgements, no robotic or written-style lines, no repeated "
        "phrasing. Latin-script Hinglish is normal, not a defect.",
        {1: "reads like a script or a form; robotic, stiff, repetitive",
         2: "mostly scripted; several stiff or written-style lines, noticeable repetition",
         3: "understandable and polite but clearly a bot in places",
         4: "mostly natural; one or two stiff or repeated lines",
         5: "sounds like a good human telecaller throughout"},
    ),
    (
        "listening", "Listening", 20,
        "Answers what the caller actually said, doesn't ask again for details already given, handles off-script "
        "questions, doesn't reply to background voices (lines clearly said to someone else near the phone), and "
        "doesn't ignore the real caller.",
        {1: "ignores or misreads the caller most of the time",
         2: "often misses what the caller said or re-asks known details",
         3: "follows the caller but misses some answers or questions",
         4: "listens well; a minor miss",
         5: "every reply fits what the caller just said"},
    ),
    (
        "empathy", "Empathy and tone", 15,
        "Matches the caller's mood (see the mood timeline), acknowledges confusion or frustration, stays respectful, "
        "isn't pushy when the caller is busy or not interested.",
        {1: "rude, cold or pushy against the caller's wishes",
         2: "ignores clear frustration or pushes on",
         3: "neutral; doesn't react to the caller's mood",
         4: "warm and respectful; mostly adapts to the mood",
         5: "consistently warm, adapts tone to the caller's mood"},
    ),
    (
        "pacing", "Pacing and turn-taking", 15,
        "Line length suited to a phone call, no long monologues, doesn't talk over the caller (interruptions), "
        "handles silences well (dead-air nudges), response latency.",
        {1: "long monologues, constant talking over, or long silences",
         2: "frequent long lines or interruptions",
         3: "some lines too long or a few awkward gaps",
         4: "good rhythm; one or two long lines",
         5: "short, well-timed turns like a natural conversation"},
    ),
    (
        "flow", "Flow and goal", 15,
        "Follows the workflow sensibly, moves the call toward the right outcome, no loops, no getting stuck, ends "
        "politely at the right time.",
        {1: "stuck, looping, or ends the call wrongly",
         2: "loses the thread or repeats steps",
         3: "reaches an outcome with some detours",
         4: "clear progress; minor detour",
         5: "smooth path to the right outcome"},
    ),
    (
        "accuracy", "Accuracy", 10,
        "No made-up facts against the script, knowledge and workflow; no promises the business can't keep; "
        "correct use of the caller's details.",
        {1: "states wrong facts or makes false promises",
         2: "one clear wrong fact or risky promise",
         3: "vague or unsupported claims",
         4: "accurate; slight vagueness",
         5: "everything said is supported by the script and knowledge"},
    ),
]

AREA_KEYS = [a[0] for a in AREAS]
LABELS = {a[0]: a[1] for a in AREAS}
DEFAULT_WEIGHTS = {a[0]: a[2] for a in AREAS}

# Call signals an evidence item may point at instead of a transcript line.
EVENTS = ["interruption", "dead_air", "latency", "mood", "call_end"]


def weights_for(workspace) -> dict[str, int]:
    """The workspace's weights with defaults filled in; ints from 0 to 100."""
    custom = getattr(workspace, "audit_weights", None)
    out = dict(DEFAULT_WEIGHTS)
    if isinstance(custom, dict):
        for k, v in custom.items():
            if k in out and isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100:
                out[k] = v
    if not any(out.values()):
        return dict(DEFAULT_WEIGHTS)
    return out


def overall(scores: dict[str, int | None], weights: dict[str, int]) -> int | None:
    """0–100 weighted average of the 1–5 area scores (1 → 0, 5 → 100). Areas without a score are left out and
    the remaining weights are renormalised. None when nothing is scored."""
    parts = [(weights.get(k, 0), s) for k, s in scores.items() if isinstance(s, int)]
    total = sum(w for w, _ in parts)
    if not parts or total <= 0:
        return None
    return round(sum(w * (s - 1) / 4 * 100 for w, s in parts) / total)


def rubric_text() -> str:
    lines = []
    for key, label, _w, what, levels in AREAS:
        lines.append(f'"{key}" ({label}): {what}')
        lines += [f"  {n}: {levels[n]}" for n in sorted(levels)]
    return "\n".join(lines)
