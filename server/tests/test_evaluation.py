import pytest
from django.core.management import call_command

from calls.evaluation import align_predictions, score
from calls.models import CallReport, TurnLabel

TURNS = [
    {"role": "assistant", "text": "Namaste, main Carrum se bol rahi hoon.", "at_s": 0.5},
    {"role": "user", "text": "haan boliye", "at_s": 3.0},
    {"role": "assistant", "text": "Aapki gaadi ke baare mein...", "at_s": 4.0},
    {"role": "user", "text": "kitni baar call karoge", "at_s": 10.0},
]


def reading(at_s, emotion, source="text"):
    return {"at_s": at_s, "emotion": emotion, "confidence": 0.9, "source": source}


def test_align_picks_first_reading_after_turn():
    timeline = [
        reading(2.0, "angry"),  # before the first user turn: ignored
        reading(3.5, "disengaged", source="behavior"),  # behaviour, not text: ignored
        reading(4.2, "interested"),
        reading(5.0, "confused"),  # second reading for the same turn: ignored
        reading(11.0, "frustrated"),
    ]
    assert align_predictions(TURNS, timeline) == [
        {"at_s": 3.0, "caller_text": "haan boliye", "predicted": "interested"},
        {"at_s": 10.0, "caller_text": "kitni baar call karoge", "predicted": "frustrated"},
    ]


def test_align_falls_back_to_neutral():
    # The only text reading after turn 1 lands after turn 2 starts, so turn 1 has none.
    timeline = [reading(10.5, "angry")]
    assert [p["predicted"] for p in align_predictions(TURNS, timeline)] == ["neutral", "angry"]
    assert [p["predicted"] for p in align_predictions(TURNS, [])] == ["neutral", "neutral"]


def test_score_precision_recall():
    labels = ["angry", "angry", "neutral", "confused", "confused", "neutral"]
    predicted = ["angry", "neutral", "neutral", "confused", "angry", "neutral"]
    result = score(list(zip(labels, predicted)))

    assert result["accuracy"] == pytest.approx(4 / 6)
    assert result["per_emotion"]["angry"]["precision"] == pytest.approx(0.5)
    assert result["per_emotion"]["angry"]["recall"] == pytest.approx(0.5)
    assert result["per_emotion"]["angry"]["support"] == 2
    assert result["per_emotion"]["confused"]["precision"] == pytest.approx(1.0)
    assert result["per_emotion"]["confused"]["recall"] == pytest.approx(0.5)
    assert result["confusion"]["confused"] == {"confused": 1, "angry": 1}
    assert result["confusion"]["angry"] == {"angry": 1, "neutral": 1}


def test_score_skips_unclear():
    with_unclear = score([("angry", "angry"), ("unclear", "neutral"), ("neutral", "angry")])
    without = score([("angry", "angry"), ("neutral", "angry")])
    assert with_unclear == without
    assert with_unclear["accuracy"] == pytest.approx(0.5)
    assert "unclear" not in with_unclear["confusion"]


def eval_report(room="call-eval"):
    return {
        "room": room,
        "disposition": "interested",
        "outcome": {},
        "mood": {"final": "frustrated", "worst": "frustrated", "avg_sentiment": -0.5, "changes": 1},
        "timeline": [reading(4.2, "interested"), reading(11.0, "frustrated")],
        "dead_air": [],
        "latency": {},
        "behavior": {},
        "turns": TURNS,
    }


@pytest.mark.django_db
def test_store_creates_turn_labels_and_keeps_labels():
    report = CallReport.store(eval_report())
    rows = list(report.turns.order_by("at_s"))
    assert [(r.at_s, r.predicted, r.label) for r in rows] == [(3.0, "interested", ""), (10.0, "frustrated", "")]

    rows[1].label = "angry"
    rows[1].save()

    CallReport.store(eval_report())
    assert TurnLabel.objects.count() == 2
    assert TurnLabel.objects.get(at_s=10.0).label == "angry"


@pytest.mark.django_db
def test_store_without_turns_creates_no_labels():
    body = eval_report()
    del body["turns"]
    CallReport.store(body)
    assert not TurnLabel.objects.exists()


@pytest.mark.django_db
def test_purge_turns():
    CallReport.store(eval_report())
    call_command("purge_turns")
    assert not TurnLabel.objects.exists()
    report = CallReport.objects.get()
    assert "turns" not in report.data
    assert report.data["mood"]["final"] == "frustrated"


@pytest.mark.django_db
def test_mood_eval_prints_gate(capsys):
    report = CallReport.store(eval_report())
    for row in report.turns.all():
        row.label = row.predicted
        row.save()
    call_command("mood_eval")
    out = capsys.readouterr().out
    assert "Accuracy: 1.00 (2 labelled turns" in out
    assert "FAIL" in out  # angry and confused were never predicted, so the gate can't pass yet
