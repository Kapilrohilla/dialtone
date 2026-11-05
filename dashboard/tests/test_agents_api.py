import pytest

from knowledge.models import KnowledgeDocument
from tests.helpers import assert_isolated
from tests.test_publish import BODY, make_agent, make_doc, make_workflow
from tests.test_workflow_graph import driver_graph, step
from voiceagents.models import Agent, AgentVersion
from voiceagents.tokens import BUILTIN_EXPRESSIONS

SCRIPT = [{"id": "s1", "title": "Opening", "body": BODY}]
CUSTOM = {"sigh": "let out a small, friendly sigh"}


def create(c, name="Driver lead qualifier", **kw):
    return c.post("/api/agents", {"name": name, **kw}, format="json")


def ready(c, name="Driver lead qualifier"):
    """Create an agent through the API that is ready to publish; returns its id."""
    r = create(c, name, script=SCRIPT, custom_expressions=CUSTOM)
    assert r.status_code == 201, r.content
    return r.json()["id"]


@pytest.mark.django_db
def test_create_and_list_shape(member):
    c = member("editor")
    c.user.first_name = "Kapil"
    c.user.save()
    r = create(c, description="Qualifies driver leads", phone_number="+911234567890")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["status"] == "draft" and body["language"] == "Hindi + Hinglish" and body["persona_name"] == "Priya"
    assert body["settings"] == {"mood_adaptation": True,
                                "dead_air": {"enabled": True, "nudge_s": 4, "second_nudge_s": 9, "hang_up_s": 15}}
    assert body["script"] == [] and body["custom_expressions"] == {} and body["knowledge"] == []
    assert body["workflow"] is None and body["published_version"] is None and body["is_outdated"] is False
    lst = c.get("/api/agents").json()
    assert len(lst) == 1
    assert set(lst[0]) == {"id", "name", "description", "status", "phone_number", "updated_at",
                           "updated_by_name", "is_outdated", "calls_this_week"}
    assert lst[0]["updated_by_name"] == "Kapil" and lst[0]["phone_number"] == "+911234567890"
    assert create(c, name="  ").status_code == 400


@pytest.mark.django_db
def test_patch_fields_and_links(member, workspace):
    c = member("editor")
    pk = ready(c)
    doc = make_doc(workspace, "Plans")
    wf = make_workflow(workspace)
    r = c.patch(f"/api/agents/{pk}", {
        "name": "Renamed", "knowledge": [doc.id], "workflow": wf.id,
        "settings": {"dead_air": {"nudge_s": 5}}, "voice_id": "Puck",
    }, format="json")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["name"] == "Renamed" and body["knowledge"] == [doc.id] and body["workflow"] == wf.id
    assert body["settings"]["dead_air"] == {"enabled": True, "nudge_s": 5, "second_nudge_s": 9, "hang_up_s": 15}
    assert body["settings"]["mood_adaptation"] is True and body["voice_id"] == "Puck"
    assert c.get(f"/api/agents/{pk}").json() == body
    r = c.patch(f"/api/agents/{pk}", {"workflow": None, "knowledge": []}, format="json")
    assert r.json()["workflow"] is None and r.json()["knowledge"] == []


@pytest.mark.django_db
def test_patch_validation(member, workspace, other_workspace):
    c = member("editor")
    pk = ready(c)
    foreign_doc = make_doc(other_workspace, "Theirs")
    foreign_wf = make_workflow(other_workspace)
    archived = make_doc(workspace, "Old")
    archived.archived = True
    archived.save()
    bad = [
        {"knowledge": [foreign_doc.id]},
        {"knowledge": [archived.id]},
        {"workflow": foreign_wf.id},
        {"script": "nope"},
        {"script": [{"id": "s1", "title": "A", "body": 3}]},
        {"script": [{"id": "s1", "title": "A", "body": ""}, {"id": "s1", "title": "B", "body": ""}]},
        {"custom_expressions": {"Bad Name": "x"}},
        {"custom_expressions": {"happy": "x"}},
        {"custom_expressions": {"sigh": ""}},
        {"settings": {"dead_air": {"nudge_s": 10, "second_nudge_s": 9}}},
        {"settings": {"mood_adaptation": "yes"}},
        {"name": ""},
    ]
    for payload in bad:
        r = c.patch(f"/api/agents/{pk}", payload, format="json")
        assert r.status_code == 400, (payload, r.content)
    agent = Agent.objects.get(pk=pk)
    assert agent.script == SCRIPT and agent.custom_expressions == CUSTOM and agent.workflow is None


@pytest.mark.django_db
def test_publish_endpoint(member):
    c = member("editor")
    pk = ready(c)
    r = c.post(f"/api/agents/{pk}/publish")
    assert r.status_code == 200 and r.json() == {"version": 1}
    got = c.get(f"/api/agents/{pk}").json()
    assert got["status"] == "published" and got["published_version"] == 1 and got["is_outdated"] is False
    c.patch(f"/api/agents/{pk}", {"persona_name": "Asha"}, format="json")
    assert c.get("/api/agents").json()[0]["is_outdated"] is True
    assert c.post(f"/api/agents/{pk}/publish").json() == {"version": 2}
    versions = c.get(f"/api/agents/{pk}/versions").json()
    assert [v["number"] for v in versions] == [2, 1]
    assert set(versions[0]) == {"number", "published_by_name", "published_at"}
    assert versions[0]["published_by_name"] == c.user.email


@pytest.mark.django_db
def test_publish_endpoint_errors(member, workspace):
    c = member("editor")
    pk = create(c).json()["id"]
    r = c.post(f"/api/agents/{pk}/publish")
    assert r.status_code == 400 and r.json() == {"errors": ["Write at least one script section before publishing."]}
    g = driver_graph()
    g["steps"].append(step("x", "Orphan", "end", outcome="NI"))
    wf = make_workflow(workspace, g)
    c.patch(f"/api/agents/{pk}", {"script": SCRIPT, "custom_expressions": CUSTOM, "workflow": wf.id}, format="json")
    r = c.post(f"/api/agents/{pk}/publish")
    assert r.status_code == 400 and any("Orphan" in e for e in r.json()["errors"])
    assert AgentVersion.objects.count() == 0


@pytest.mark.django_db
def test_publish_api_unpublishes_other(member):
    c = member("editor")
    a, b = ready(c, "A"), ready(c, "B")
    c.post(f"/api/agents/{a}/publish")
    c.post(f"/api/agents/{b}/publish")
    statuses = {x["id"]: x["status"] for x in c.get("/api/agents").json()}
    assert statuses == {a: "draft", b: "published"}


@pytest.mark.django_db
def test_unpublish_endpoint(member):
    c = member("editor")
    pk = ready(c)
    assert c.post(f"/api/agents/{pk}/unpublish").status_code == 400
    c.post(f"/api/agents/{pk}/publish")
    r = c.post(f"/api/agents/{pk}/unpublish")
    assert r.status_code == 200 and r.json()["status"] == "draft" and r.json()["published_version"] is None
    assert len(c.get(f"/api/agents/{pk}/versions").json()) == 1


@pytest.mark.django_db
def test_editing_draft_does_not_change_published_snapshot(member):
    c = member("editor")
    pk = ready(c)
    c.post(f"/api/agents/{pk}/publish")
    before = AgentVersion.objects.get(agent_id=pk).snapshot
    r = c.patch(f"/api/agents/{pk}", {"script": [{"id": "s1", "title": "Opening", "body": "Changed"}]},
                format="json")
    assert r.status_code == 200
    v = AgentVersion.objects.get(agent_id=pk)
    assert v.snapshot == before and "Changed" not in str(v.snapshot)
    agent = Agent.objects.get(pk=pk)
    assert agent.status == Agent.PUBLISHED and agent.published_version == v
    assert r.json()["is_outdated"] is True


@pytest.mark.django_db
def test_duplicate_is_draft(member, workspace):
    c = member("editor")
    pk = ready(c)
    doc = make_doc(workspace)
    wf = make_workflow(workspace)
    c.patch(f"/api/agents/{pk}", {"knowledge": [doc.id], "workflow": wf.id, "phone_number": "+91"}, format="json")
    c.post(f"/api/agents/{pk}/publish")
    r = c.post(f"/api/agents/{pk}/duplicate")
    assert r.status_code == 201, r.content
    copy = r.json()
    assert copy["id"] != pk and copy["name"] == "Copy of Driver lead qualifier"
    assert copy["status"] == "draft" and copy["published_version"] is None
    assert copy["script"] == SCRIPT and copy["custom_expressions"] == CUSTOM
    assert copy["knowledge"] == [doc.id] and copy["workflow"] == wf.id
    assert Agent.objects.get(pk=pk).status == Agent.PUBLISHED
    assert AgentVersion.objects.filter(agent_id=copy["id"]).count() == 0


@pytest.mark.django_db
def test_archive_published_is_refused(member):
    c = member("editor")
    pk = ready(c)
    c.post(f"/api/agents/{pk}/publish")
    r = c.post(f"/api/agents/{pk}/archive")
    assert r.status_code == 400 and r.json() == {"detail": "Unpublish it first."}
    assert Agent.objects.get(pk=pk).status == Agent.PUBLISHED


@pytest.mark.django_db
def test_archive_and_restore(member):
    c = member("editor")
    pk = ready(c)
    assert c.post(f"/api/agents/{pk}/restore").status_code == 400
    r = c.post(f"/api/agents/{pk}/archive")
    assert r.status_code == 200 and r.json()["status"] == "archived"
    assert c.post(f"/api/agents/{pk}/publish").status_code == 400
    assert c.get("/api/agents").json()[0]["status"] == "archived"
    r = c.post(f"/api/agents/{pk}/restore")
    assert r.status_code == 200 and r.json()["status"] == "draft"


@pytest.mark.django_db
def test_viewer_cannot_publish(member):
    e, v = member("editor"), member("viewer")
    pk = ready(e)
    assert v.post(f"/api/agents/{pk}/publish").status_code == 403
    assert Agent.objects.get(pk=pk).status == Agent.DRAFT
    e.post(f"/api/agents/{pk}/publish")
    for action in ("unpublish", "duplicate", "archive", "restore"):
        assert v.post(f"/api/agents/{pk}/{action}").status_code == 403, action
    assert v.patch(f"/api/agents/{pk}", {"name": "x"}, format="json").status_code == 403
    assert v.post("/api/agents", {"name": "x"}, format="json").status_code == 403
    assert Agent.objects.count() == 1 and Agent.objects.get(pk=pk).status == Agent.PUBLISHED
    assert v.get("/api/agents").status_code == 200
    assert v.get(f"/api/agents/{pk}").status_code == 200
    assert v.get(f"/api/agents/{pk}/versions").status_code == 200
    assert v.get("/api/expressions").status_code == 200


@pytest.mark.django_db
def test_agents_isolated(member, other_workspace):
    c = member("editor")
    theirs = make_agent(other_workspace, "Theirs")
    assert_isolated(c, f"/api/agents/{theirs.id}")
    assert_isolated(c, f"/api/agents/{theirs.id}/versions")
    for action in ("publish", "unpublish", "duplicate", "archive", "restore"):
        assert c.post(f"/api/agents/{theirs.id}/{action}").status_code == 404, action
    assert c.patch(f"/api/agents/{theirs.id}", {"name": "x"}, format="json").status_code == 404
    assert c.get("/api/agents").json() == []
    theirs.refresh_from_db()
    assert theirs.status == Agent.DRAFT and theirs.name == "Theirs"
    assert Agent.objects.filter(workspace=other_workspace).count() == 1


@pytest.mark.django_db
def test_expressions_endpoint(member):
    c = member("viewer")
    r = c.get("/api/expressions")
    assert r.status_code == 200
    assert r.json() == [{"name": n, "hint": h, "builtin": True} for n, h in BUILTIN_EXPRESSIONS.items()]
    assert {"name": "pause", "hint": "pause for about {seconds} seconds before this", "builtin": True} in r.json()


@pytest.mark.django_db
def test_knowledge_used_by_counts_agents(member, workspace):
    c = member("editor")
    doc = make_doc(workspace, "Plans")
    unused = make_doc(workspace, "Unused")
    a, b, archived = make_agent(workspace, "A"), make_agent(workspace, "B"), make_agent(workspace, "C")
    archived.status = Agent.ARCHIVED
    archived.save()
    for agent in (a, b, archived):
        agent.knowledge.add(doc)
    used = {d["id"]: d["used_by"] for d in c.get("/api/knowledge").json()}
    assert used == {doc.id: 2, unused.id: 0}
    assert KnowledgeDocument.objects.count() == 2


@pytest.mark.django_db
def test_nul_in_script_and_custom_expressions_is_stripped_not_500(member):
    c = member("editor")
    script = [{"id": "s1", "title": "Open\u0000ing", "body": "Hi\u0000 there"}]
    r = create(c, script=script, custom_expressions={"sigh": "a small\u0000 sigh"})
    assert r.status_code == 201, r.content
    assert r.json()["script"] == [{"id": "s1", "title": "Opening", "body": "Hi there"}]
    assert r.json()["custom_expressions"] == {"sigh": "a small sigh"}
    r = c.patch(f"/api/agents/{r.json()['id']}", {"script": [{"id": "s\u00001", "title": "T", "body": "\u0000"}],
                                                  "custom_expressions": {"si\u0000gh": "x"}}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["script"] == [{"id": "s1", "title": "T", "body": ""}]
    assert r.json()["custom_expressions"] == {"sigh": "x"}
