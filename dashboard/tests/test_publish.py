import threading

import pytest
from django.contrib.auth import get_user_model
from django.db import connection

from knowledge.models import KnowledgeDocument, KnowledgeRevision
from tests.test_workflow_graph import driver_graph, path, step
from voiceagents.models import Agent, AgentVersion
from voiceagents.publish import PublishError, is_outdated, publish, unpublish
from workflows.models import Workflow, WorkflowRevision

BODY = "Namaste! [[expr:happy]] Aap {{lead.city}} se hain? [[expr:pause:1.5]] [[expr:sigh]] Theek hai."


def make_user(email="pub@example.com"):
    return get_user_model().objects.create_user(username=email, email=email, password="pw-test-12345")


def make_agent(workspace, name="Driver lead qualifier", **kw):
    fields = {
        "script": [{"id": "s1", "title": "Opening", "body": BODY}],
        "custom_expressions": {"sigh": "let out a small, friendly sigh"},
    }
    fields.update(kw)
    return Agent.objects.create(workspace=workspace, name=name, **fields)


def make_doc(workspace, title="Plans", *bodies):
    doc = KnowledgeDocument.objects.create(workspace=workspace, title=title)
    for i, body in enumerate(bodies or ("v1",), start=1):
        KnowledgeRevision.objects.create(document=doc, number=i, body_md=body)
    return doc


def make_workflow(workspace, graph=None, name="Onboarding"):
    wf = Workflow.objects.create(workspace=workspace, name=name)
    WorkflowRevision.objects.create(workflow=wf, number=1, graph=graph if graph is not None else driver_graph())
    return wf


def published_count(workspace):
    return Agent.objects.filter(workspace=workspace, status=Agent.PUBLISHED).count()


@pytest.mark.django_db
def test_publish_snapshot_contents(workspace):
    user = make_user()
    doc = make_doc(workspace, "Plans", "old text", "Plan A details")
    g = driver_graph()
    g["steps"][3]["prompt"] = "Here is the plan for {{lead.name}}. [[expr:whisper]] Only for you."
    wf = make_workflow(workspace, g)
    agent = make_agent(workspace, workflow=wf, phone_number="+911234567890", voice_id="v-1")
    agent.knowledge.add(doc)

    v = publish(agent, user)

    agent.refresh_from_db()
    assert v.number == 1 and v.published_by == user and v.agent == agent
    assert agent.status == Agent.PUBLISHED and agent.published_version == v
    s = v.snapshot
    assert s["agent_id"] == agent.id and s["version"] == 1
    assert s["name"] == "Driver lead qualifier" and s["persona_name"] == "Priya"
    assert s["language"] == "Hindi + Hinglish" and s["voice_id"] == "v-1" and s["phone_number"] == "+911234567890"
    assert s["settings"]["dead_air"] == {"enabled": True, "nudge_s": 4, "second_nudge_s": 9, "hang_up_s": 15}
    rendered = s["script"][0]["body_rendered"]
    assert s["script"][0]["title"] == "Opening"
    assert "(say this warmly and cheerfully)" in rendered
    assert "(pause for about 1.5 seconds before this)" in rendered
    assert "(let out a small, friendly sigh)" in rendered
    assert "{{lead.city}}" in rendered and "[[expr:" not in rendered
    assert s["variables"] == ["lead.city", "lead.name"]
    assert s["knowledge"] == [{"id": doc.id, "title": "Plans", "revision": 2, "body_md": "Plan A details",
                            "body_rendered": "Plan A details"}]
    assert s["workflow"]["id"] == wf.id and s["workflow"]["revision"] == 1
    prompts = {st["id"]: st["prompt"] for st in s["workflow"]["graph"]["steps"]}
    assert prompts["s1"] == "Namaste! (say this warmly and cheerfully) I am calling from Carrum."
    assert "(say this softly, as if sharing something personal)" in prompts["s4"]
    assert "{{lead.name}}" in prompts["s4"]
    # The stored workflow revision itself is untouched.
    assert "[[expr:happy]]" in WorkflowRevision.objects.get(workflow=wf).graph["steps"][0]["prompt"]

    v2 = publish(agent, user)
    assert v2.number == 2 and agent.versions.count() == 2


@pytest.mark.django_db
def test_script_only_agent_publishes(workspace):
    v = publish(make_agent(workspace), make_user())
    assert v.snapshot["workflow"] is None and v.snapshot["knowledge"] == []


@pytest.mark.django_db
def test_publish_unpublishes_other(workspace):
    user = make_user()
    a, b = make_agent(workspace, "A"), make_agent(workspace, "B")
    va = publish(a, user)
    publish(b, user)
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.status == Agent.DRAFT and a.published_version is None
    assert list(a.versions.all()) == [va]
    assert b.status == Agent.PUBLISHED
    assert published_count(workspace) == 1


@pytest.mark.django_db
def test_publish_invariant_sequential(workspace, other_workspace):
    user = make_user()
    a, b = make_agent(workspace, "A"), make_agent(workspace, "B")
    theirs = make_agent(other_workspace, "Theirs")
    publish(theirs, user)
    for agent in (a, b, a, b, a):
        publish(agent, user)
        assert published_count(workspace) == 1
        assert published_count(other_workspace) == 1
    assert Agent.objects.get(pk=a.pk).status == Agent.PUBLISHED


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_publish_one_wins(workspace):
    user = make_user()
    a, b = make_agent(workspace, "A"), make_agent(workspace, "B")
    barrier = threading.Barrier(2)
    errors = []

    def run(pk):
        try:
            barrier.wait(timeout=10)
            publish(Agent.objects.get(pk=pk), user)
        except Exception as e:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(e)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(pk,)) for pk in (a.pk, b.pk)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    assert published_count(workspace) == 1
    winner = Agent.objects.get(workspace=workspace, status=Agent.PUBLISHED)
    assert winner.published_version is not None
    loser = Agent.objects.exclude(pk=winner.pk).get(workspace=workspace)
    assert loser.status == Agent.DRAFT and loser.published_version is None
    assert AgentVersion.objects.count() == 2


@pytest.mark.django_db
def test_publish_rejects_broken_workflow(workspace):
    g = driver_graph()
    g["steps"].append(step("x", "Orphan", "end", outcome="NI"))
    archived = make_doc(workspace, "Old")
    archived.archived = True
    archived.save()
    g["steps"].append(step("k1", "Look up FAQ", "knowledge", knowledge_id=archived.id))
    g["paths"] += [path("p9", "s4", "k1", "q"), path("p10", "k1", "e3", "done")]
    agent = make_agent(workspace, workflow=make_workflow(workspace, g))
    with pytest.raises(PublishError) as exc:
        publish(agent, make_user())
    errs = exc.value.errors
    assert any("Orphan" in e for e in errs)
    assert any("Look up FAQ" in e and "does not exist" in e for e in errs)
    agent.refresh_from_db()
    assert agent.status == Agent.DRAFT and agent.published_version is None
    assert AgentVersion.objects.count() == 0


@pytest.mark.django_db
def test_publish_rejects_workflow_unknown_expression_using_agent_custom(workspace):
    g = driver_graph()
    g["steps"][3]["prompt"] = "[[expr:sigh]] [[expr:grumble]]"
    agent = make_agent(workspace, workflow=make_workflow(workspace, g))
    with pytest.raises(PublishError) as exc:
        publish(agent, make_user())
    assert exc.value.errors == ['Step "Explain the plan" uses an unknown expression "grumble".']


@pytest.mark.django_db
def test_publish_rejects_empty_script(workspace):
    user = make_user()
    for script in ([], [{"id": "s1", "title": "Opening", "body": "   "}]):
        agent = make_agent(workspace, script=script)
        with pytest.raises(PublishError) as exc:
            publish(agent, user)
        assert exc.value.errors == ["Write at least one script section before publishing."]
    assert published_count(workspace) == 0


@pytest.mark.django_db
def test_publish_rejects_unknown_script_expression(workspace):
    agent = make_agent(workspace, script=[{"id": "s1", "title": "Opening", "body": "Hi [[expr:grumble]]"}])
    with pytest.raises(PublishError) as exc:
        publish(agent, make_user())
    assert exc.value.errors == ['Section "Opening" uses an unknown expression "grumble".']


@pytest.mark.django_db
def test_failed_publish_keeps_current_published(workspace):
    user = make_user()
    good, bad = make_agent(workspace, "Good"), make_agent(workspace, "Bad", script=[])
    publish(good, user)
    with pytest.raises(PublishError):
        publish(bad, user)
    assert Agent.objects.get(pk=good.pk).status == Agent.PUBLISHED


@pytest.mark.django_db
def test_archived_agent_cannot_publish(workspace):
    agent = make_agent(workspace, status=Agent.ARCHIVED)
    with pytest.raises(PublishError):
        publish(agent, make_user())


@pytest.mark.django_db
def test_unpublish(workspace):
    agent = make_agent(workspace)
    publish(agent, make_user())
    unpublish(agent)
    agent.refresh_from_db()
    assert agent.status == Agent.DRAFT and agent.published_version is None
    assert agent.versions.count() == 1
    assert is_outdated(agent) is False


@pytest.mark.django_db
def test_is_outdated_after_knowledge_save(workspace, member):
    c = member("editor")
    doc = make_doc(workspace, "Plans", "v1")
    agent = make_agent(workspace)
    agent.knowledge.add(doc)
    publish(agent, c.user)
    assert is_outdated(agent) is False
    c.patch(f"/api/knowledge/{doc.id}", {"title": "Renamed plans"}, format="json")
    assert is_outdated(agent) is False
    c.patch(f"/api/knowledge/{doc.id}", {"body_md": "v2"}, format="json")
    assert is_outdated(agent) is True
    publish(agent, c.user)
    assert is_outdated(agent) is False
    agent.knowledge.add(make_doc(workspace, "FAQ"))
    assert is_outdated(agent) is True


@pytest.mark.django_db
def test_is_outdated_after_workflow_save(workspace, member):
    c = member("editor")
    wf = make_workflow(workspace)
    agent = make_agent(workspace, workflow=wf)
    publish(agent, c.user)
    assert is_outdated(agent) is False
    c.patch(f"/api/workflows/{wf.id}", {"name": "Renamed"}, format="json")
    assert is_outdated(agent) is False
    g = driver_graph()
    g["steps"][3]["prompt"] = "A new plan."
    c.patch(f"/api/workflows/{wf.id}", {"graph": g}, format="json")
    assert is_outdated(agent) is True
    publish(agent, c.user)
    assert is_outdated(agent) is False
    agent.workflow = None
    agent.save()
    assert is_outdated(agent) is True


@pytest.mark.django_db
def test_is_outdated_after_agent_field_changes(workspace):
    user = make_user()
    agent = make_agent(workspace)
    changes = [
        ("script", [{"id": "s1", "title": "Opening", "body": "Hello"}]),
        ("settings", {"mood_adaptation": False, "dead_air": {"enabled": True, "nudge_s": 4,
                                                           "second_nudge_s": 9, "hang_up_s": 15}}),
        ("persona_name", "Asha"),
        ("language", "Hindi"),
        ("voice_id", "v-2"),
        ("phone_number", "+910000000000"),
        ("custom_expressions", {"sigh": "a different sigh"}),
    ]
    for field, value in changes:
        publish(agent, user)
        agent.refresh_from_db()
        assert is_outdated(agent) is False, field
        setattr(agent, field, value)
        agent.save()
        assert is_outdated(agent) is True, field
    publish(agent, user)
    agent.name = "Renamed"
    agent.description = "New description"
    agent.save()
    assert is_outdated(agent) is False


def _graph_with_knowledge_step(doc_id):
    g = driver_graph()
    g["steps"].append(step("k1", "Look up FAQ", "knowledge", knowledge_id=doc_id))
    g["paths"] += [path("p9", "s4", "k1", "q"), path("p10", "k1", "e3", "done")]
    return g


@pytest.mark.django_db
def test_snapshot_includes_workflow_step_knowledge(workspace):
    linked = make_doc(workspace, "Linked", "linked text")
    x = make_doc(workspace, "FAQ", "faq v1", "faq v2")
    agent = make_agent(workspace, workflow=make_workflow(workspace, _graph_with_knowledge_step(x.id)))
    agent.knowledge.add(linked, x)  # linked twice over (directly and via the step): listed once
    agent.knowledge.remove(x)
    v = publish(agent, make_user())
    assert v.snapshot["knowledge"] == [
        {"id": linked.id, "title": "Linked", "revision": 1, "body_md": "linked text", "body_rendered": "linked text"},
        {"id": x.id, "title": "FAQ", "revision": 2, "body_md": "faq v2", "body_rendered": "faq v2"},
    ]
    agent.knowledge.add(x)
    v2 = publish(agent, make_user("pub2@example.com"))
    assert [k["id"] for k in v2.snapshot["knowledge"]] == [linked.id, x.id]


@pytest.mark.django_db
def test_is_outdated_after_editing_workflow_step_knowledge(workspace, member):
    c = member("editor")
    x = make_doc(workspace, "FAQ", "faq v1")
    agent = make_agent(workspace, workflow=make_workflow(workspace, _graph_with_knowledge_step(x.id)))
    publish(agent, c.user)
    assert is_outdated(agent) is False
    c.patch(f"/api/knowledge/{x.id}", {"title": "Renamed FAQ"}, format="json")
    assert is_outdated(agent) is False
    c.patch(f"/api/knowledge/{x.id}", {"body_md": "faq v2"}, format="json")
    assert is_outdated(agent) is True


@pytest.mark.django_db
def test_publish_snapshots_the_validated_revision(workspace, monkeypatch):
    """A workflow save landing between validation and snapshot must not reach callers."""
    import voiceagents.publish as pub

    wf = make_workflow(workspace)
    agent = make_agent(workspace, workflow=wf)
    original = pub.validation_errors

    def validate_then_save_broken(a, resolved=None):
        errors = original(a, resolved)
        broken = driver_graph()
        broken["steps"].append(step("x", "Orphan", "end", outcome="NI"))
        WorkflowRevision.objects.create(workflow=wf, number=2, graph=broken)
        return errors

    monkeypatch.setattr(pub, "validation_errors", validate_then_save_broken)
    v = publish(agent, make_user())
    assert v.snapshot["workflow"]["revision"] == 1
    assert "Orphan" not in str(v.snapshot["workflow"]["graph"])
    assert is_outdated(agent) is True  # the newer (broken) revision is not what callers get


def test_agent_version_admin_is_read_only():
    from django.contrib import admin
    from django.test import RequestFactory

    ma = admin.site._registry[AgentVersion]
    req = RequestFactory().get("/")
    assert not ma.has_add_permission(req)
    assert not ma.has_change_permission(req)
    assert not ma.has_delete_permission(req)
    assert set(ma.readonly_fields) == {"agent", "number", "snapshot", "published_by", "published_at"}


@pytest.mark.django_db
def test_snapshot_knowledge_body_rendered(workspace):
    doc = make_doc(workspace, "Tone", "[[expr:excited]] Welcome [[expr:sigh]]")
    agent = make_agent(workspace)
    agent.knowledge.add(doc)
    v = publish(agent, make_user())
    (k,) = v.snapshot["knowledge"]
    assert k["body_md"] == "[[expr:excited]] Welcome [[expr:sigh]]"
    assert k["body_rendered"] == "(say this with energy and enthusiasm) Welcome (let out a small, friendly sigh)"


@pytest.mark.django_db
def test_publish_rejects_long_pause(workspace):
    agent = make_agent(workspace, script=[{"id": "s1", "title": "Opening", "body": "Hi [[expr:pause:10.5]]"}])
    with pytest.raises(PublishError) as exc:
        publish(agent, make_user())
    assert exc.value.errors == ['Section "Opening": Pause is too long (10.5 s). Use at most 10 seconds.']
    ok = make_agent(workspace, name="B", script=[{"id": "s1", "title": "Opening", "body": "Hi [[expr:pause:10]]"}])
    publish(ok, make_user("pub3@example.com"))
