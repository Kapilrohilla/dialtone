from calls.models import Call, CallFeedback
from tests.helpers import assert_isolated

URL = "/api/calls/web-3-abc/feedback"


def make_call(workspace, room="web-3-abc"):
    return Call.objects.create(room=room, workspace=workspace, caller="Web test")


def test_save_and_replace_my_feedback(member, workspace):
    make_call(workspace)
    c = member("editor")
    body = {"ratings": {"pacing": 2, "listening": 4}, "overall": 3, "remarks": "  Cut in while I gave my number.  "}
    r = c.put(URL, body, format="json")
    assert r.status_code == 200, r.content
    saved = r.json()
    assert saved["ratings"] == {"pacing": 2, "listening": 4} and saved["overall"] == 3
    assert saved["remarks"] == "Cut in while I gave my number." and saved["mine"] is True
    # Saving again replaces it: one per person per call.
    r = c.put(URL, {"ratings": {"pacing": 3}}, format="json")
    assert r.status_code == 200
    assert CallFeedback.objects.count() == 1
    fb = CallFeedback.objects.get()
    assert fb.ratings == {"pacing": 3} and fb.overall is None and fb.remarks == ""


def test_everyone_sees_all_feedback_mine_first(member, workspace):
    make_call(workspace)
    a, b = member("editor"), member("viewer")
    assert a.put(URL, {"overall": 4}, format="json").status_code == 200
    assert b.put(URL, {"overall": 2, "remarks": "too slow"}, format="json").status_code == 200  # viewers may rate
    rows = b.get(URL).json()
    assert [(r["overall"], r["mine"]) for r in rows] == [(2, True), (4, False)]
    assert all(r["author"] for r in rows)


def test_validation(member, workspace):
    make_call(workspace)
    c = member("editor")
    bad = [
        {},
        {"ratings": {}, "remarks": "   "},
        {"ratings": {"speed": 3}},
        {"ratings": {"pacing": 6}},
        {"ratings": {"pacing": 0}},
        {"ratings": {"pacing": True}},
        {"ratings": {"pacing": "3"}},
        {"ratings": ["pacing"]},
        {"overall": 9},
        {"remarks": 5},
        {"remarks": "x" * 2001},
    ]
    for body in bad:
        r = c.put(URL, body, format="json")
        assert r.status_code == 400, (body, r.content)
    assert CallFeedback.objects.count() == 0
    # An area sent as null is just unrated.
    r = c.put(URL, {"ratings": {"pacing": None, "flow": 5}}, format="json")
    assert r.status_code == 200 and r.json()["ratings"] == {"flow": 5}


def test_delete_my_feedback(member, workspace):
    make_call(workspace)
    c = member("editor")
    c.put(URL, {"overall": 4}, format="json")
    assert c.delete(URL).status_code == 204
    assert c.get(URL).json() == []


def test_other_workspace_and_missing_call(member, workspace, other_workspace):
    make_call(other_workspace)
    c = member("editor")
    assert_isolated(c, URL)
    assert c.put(URL, {"overall": 3}, format="json").status_code == 404
    assert c.put("/api/calls/nope/feedback", {"overall": 3}, format="json").status_code == 404


def test_requires_login(client, workspace):
    make_call(workspace)
    assert client.get(URL).status_code in (401, 403)
