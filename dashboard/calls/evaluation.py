"""Score the agent's mood readings against telecaller labels. Pure functions, no Django."""

from collections import Counter, defaultdict

# Copied from agent/mood.py (Emotion); the dashboard must not import the agent.
EMOTIONS = ("neutral", "interested", "confused", "frustrated", "rushed", "suspicious", "angry", "disengaged")
UNCLEAR = "unclear"
GATE_EMOTIONS = ("angry", "frustrated", "confused")
GATE_PRECISION = 0.7


def align_predictions(turns: list[dict], timeline: list[dict]) -> list[dict]:
    """Pair each caller turn with the first text reading at or after it, before the next caller turn."""
    user_turns = sorted((t for t in turns if t.get("role") == "user"), key=lambda t: t["at_s"])
    readings = sorted((r for r in timeline if r.get("source") == "text"), key=lambda r: r["at_s"])
    aligned = []
    for i, turn in enumerate(user_turns):
        start = turn["at_s"]
        end = user_turns[i + 1]["at_s"] if i + 1 < len(user_turns) else float("inf")
        predicted = next((r["emotion"] for r in readings if start <= r["at_s"] < end), "neutral")
        aligned.append({"at_s": start, "caller_text": turn.get("text", ""), "predicted": predicted})
    return aligned


def score(pairs: list[tuple[str, str]]) -> dict:
    """Accuracy, per-emotion precision/recall and a confusion matrix over (label, predicted) pairs.

    Pairs labelled "unclear" are skipped. Precision or recall with nothing to divide by is 0.0.
    """
    pairs = [(label, pred) for label, pred in pairs if label != UNCLEAR]
    confusion: dict[str, Counter] = defaultdict(Counter)
    for label, pred in pairs:
        confusion[label][pred] += 1

    predicted_counts = Counter(pred for _, pred in pairs)
    per_emotion = {}
    for e in EMOTIONS:
        row = confusion.get(e, Counter())
        support = sum(row.values())
        per_emotion[e] = {
            "precision": row[e] / predicted_counts[e] if predicted_counts[e] else 0.0,
            "recall": row[e] / support if support else 0.0,
            "support": support,
        }

    correct = sum(1 for label, pred in pairs if label == pred)
    return {
        "accuracy": correct / len(pairs) if pairs else 0.0,
        "per_emotion": per_emotion,
        "confusion": {label: dict(row) for label, row in confusion.items()},
    }


def gate_passes(result: dict) -> bool:
    """Go-live gate: precision >= 0.7 for angry, frustrated and confused."""
    return all(result["per_emotion"][e]["precision"] >= GATE_PRECISION for e in GATE_EMOTIONS)
