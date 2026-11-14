import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from knowledge.models import KnowledgeDocument, KnowledgeRevision
from tests.helpers import assert_isolated


def _create(client, title="FAQ", body="hello"):
    return client.post("/api/knowledge", {"title": title, "body_md": body}, format="json")


@pytest.mark.django_db
def test_create_makes_revision_1(member):
    c = member("editor")
    r = _create(c)
    assert r.status_code == 201
    assert r.json()["current_revision"] == 1
    rev = KnowledgeRevision.objects.get(document_id=r.json()["id"])
    assert rev.number == 1 and rev.body_md == "hello" and rev.edited_by == c.user
    lst = c.get("/api/knowledge").json()
    assert set(lst[0]) == {"id", "title", "updated_at", "current_revision", "used_by"}


@pytest.mark.django_db
def test_save_same_body_no_new_revision(member):
    c = member("editor")
    pk = _create(c).json()["id"]
    r = c.patch(f"/api/knowledge/{pk}", {"body_md": "hello"}, format="json")
    assert r.status_code == 200 and r.json()["current_revision"] == 1
    c.patch(f"/api/knowledge/{pk}", {"title": "New title"}, format="json")
    assert KnowledgeRevision.objects.filter(document_id=pk).count() == 1
    assert c.get(f"/api/knowledge/{pk}").json()["title"] == "New title"


@pytest.mark.django_db
def test_save_changed_body_increments(member):
    c = member("editor")
    pk = _create(c).json()["id"]
    r = c.patch(f"/api/knowledge/{pk}", {"body_md": "v2"}, format="json")
    assert r.json()["current_revision"] == 2 and r.json()["body_md"] == "v2"
    revs = c.get(f"/api/knowledge/{pk}/revisions").json()
    assert [x["number"] for x in revs] == [2, 1]
    one = c.get(f"/api/knowledge/{pk}/revisions/1").json()
    assert one["body_md"] == "hello" and one["number"] == 1
    assert c.get(f"/api/knowledge/{pk}/revisions/9").status_code == 404


@pytest.mark.django_db
def test_upload_md_utf8_devanagari(member):
    c = member("editor")
    text = "नमस्ते दुनिया"
    f = SimpleUploadedFile("मार्गदर्शिका.md", text.encode("utf-8"))
    r = c.post("/api/knowledge/upload", {"file": f}, format="multipart")
    assert r.status_code == 201, r.content
    assert r.json()["title"] == "मार्गदर्शिका"
    assert c.get(f"/api/knowledge/{r.json()['id']}").json()["body_md"] == text


@pytest.mark.django_db
def test_upload_rejects_non_md_and_too_big(member):
    c = member("editor")
    bad = [
        SimpleUploadedFile("a.txt", b"x"),
        SimpleUploadedFile("a.md", b"x" * (1024 * 1024 + 1)),
        SimpleUploadedFile("a.md", b"\xff\xfe\x00bad"),
    ]
    for f in bad:
        r = c.post("/api/knowledge/upload", {"file": f}, format="multipart")
        assert r.status_code == 400 and r.json()["detail"]
    assert c.post("/api/knowledge/upload", {}, format="multipart").status_code == 400
    assert KnowledgeDocument.objects.count() == 0


@pytest.mark.django_db
def test_viewer_cannot_save(member):
    e, v = member("editor"), member("viewer")
    pk = _create(e).json()["id"]
    assert v.patch(f"/api/knowledge/{pk}", {"body_md": "x"}, format="json").status_code == 403
    assert v.post("/api/knowledge", {"title": "t", "body_md": ""}, format="json").status_code == 403
    assert v.get(f"/api/knowledge/{pk}").status_code == 200
    assert v.get("/api/knowledge").status_code == 200
    assert v.get(f"/api/knowledge/{pk}/revisions").status_code == 200


@pytest.mark.django_db
def test_knowledge_isolated(member, other_workspace):
    doc = KnowledgeDocument.objects.create(workspace=other_workspace, title="x")
    KnowledgeRevision.objects.create(document=doc, number=1, body_md="s")
    c = member("editor")
    assert_isolated(c, f"/api/knowledge/{doc.id}")
    assert_isolated(c, f"/api/knowledge/{doc.id}/revisions")
    assert_isolated(c, f"/api/knowledge/{doc.id}/revisions/1")
    assert c.patch(f"/api/knowledge/{doc.id}", {"title": "y"}, format="json").status_code == 404
    assert c.get("/api/knowledge").json() == []


@pytest.mark.django_db
def test_save_locks_the_document_row_before_numbering(member):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    c = member("editor")
    pk = _create(c).json()["id"]
    with CaptureQueriesContext(connection) as ctx:
        assert c.patch(f"/api/knowledge/{pk}", {"body_md": "v2"}, format="json").status_code == 200
    table = KnowledgeDocument._meta.db_table
    assert any(f'FROM "{table}"' in q["sql"] and "FOR UPDATE" in q["sql"] for q in ctx.captured_queries)


@pytest.mark.django_db
def test_nul_in_json_body_is_a_readable_400(member):
    c = member("editor")
    r = _create(c, body="a\u0000b")
    assert r.status_code == 400 and "Null characters" in r.json()["body_md"][0]


@pytest.mark.django_db
def test_upload_md_with_nul_is_stripped_not_500(member):
    c = member("editor")
    f = SimpleUploadedFile("faq.md", "a\u0000b".encode("utf-8"))
    r = c.post("/api/knowledge/upload", {"file": f}, format="multipart")
    assert r.status_code == 201, r.content
    assert c.get(f"/api/knowledge/{r.json()['id']}").json()["body_md"] == "ab"


# --- delete -----------------------------------------------------------------------------------------


def _graph_using(doc_id, step_name="Pricing answers"):
    from tests.test_workflow_graph import driver_graph, step

    g = driver_graph()
    g["steps"].append(step("k1", step_name, "knowledge", knowledge_id=doc_id))
    return g


@pytest.mark.django_db
def test_delete_removes_the_document_and_unlinks_agents(member, workspace):
    from voiceagents.models import Agent

    c = member("editor")
    pk = _create(c).json()["id"]
    keep = _create(c, title="Keep").json()["id"]
    agent = Agent.objects.create(workspace=workspace, name="A")
    agent.knowledge.add(pk, keep)
    assert c.delete(f"/api/knowledge/{pk}").status_code == 204
    assert c.get(f"/api/knowledge/{pk}").status_code == 404
    assert [d["id"] for d in c.get("/api/knowledge").json()] == [keep]
    assert list(agent.knowledge.values_list("id", flat=True)) == [keep]
    # Gone from the console; the row and its history stay in the database.
    doc = KnowledgeDocument.objects.get(pk=pk)
    assert doc.archived and doc.revisions.count() == 1
    assert c.delete(f"/api/knowledge/{pk}").status_code == 404


@pytest.mark.django_db
def test_delete_refused_while_a_workflow_step_uses_it(member, workspace):
    from tests.test_publish import make_workflow

    c = member("editor")
    pk = _create(c).json()["id"]
    make_workflow(workspace, _graph_using(pk), name="Onboarding")
    r = c.delete(f"/api/knowledge/{pk}")
    assert r.status_code == 409
    assert r.json()["detail"] == (
        'The "Pricing answers" step of the workflow "Onboarding" uses this document. '
        "Pick another document there first."
    )
    assert not KnowledgeDocument.objects.get(pk=pk).archived


@pytest.mark.django_db
def test_delete_ignores_old_workflow_revisions_and_archived_workflows(member, workspace):
    from tests.test_publish import make_workflow
    from tests.test_workflow_graph import driver_graph
    from workflows.models import WorkflowRevision

    c = member("editor")
    pk = _create(c).json()["id"]
    moved_on = make_workflow(workspace, _graph_using(pk), name="Moved on")
    WorkflowRevision.objects.create(workflow=moved_on, number=2, graph=driver_graph())
    gone = make_workflow(workspace, _graph_using(pk), name="Gone")
    gone.archived = True
    gone.save()
    assert c.delete(f"/api/knowledge/{pk}").status_code == 204


@pytest.mark.django_db
def test_published_agent_keeps_the_text_until_it_is_published_again(member, workspace):
    from tests.test_publish import make_agent, make_user
    from voiceagents.publish import is_outdated, publish

    c = member("editor")
    pk = _create(c, body="Deposit 5000").json()["id"]
    agent = make_agent(workspace)
    agent.knowledge.add(pk)
    version = publish(agent, make_user())
    assert c.delete(f"/api/knowledge/{pk}").status_code == 204
    version.refresh_from_db()
    assert version.snapshot["knowledge"][0]["body_md"] == "Deposit 5000"
    agent.refresh_from_db()
    assert is_outdated(agent) is True


@pytest.mark.django_db
def test_viewers_cannot_delete_and_other_workspaces_documents_404(member, other_workspace):
    e, v = member("editor"), member("viewer")
    pk = _create(e).json()["id"]
    assert v.delete(f"/api/knowledge/{pk}").status_code == 403
    foreign = KnowledgeDocument.objects.create(workspace=other_workspace, title="x")
    assert e.delete(f"/api/knowledge/{foreign.id}").status_code == 404
    assert not KnowledgeDocument.objects.get(pk=pk).archived
    assert not KnowledgeDocument.objects.get(pk=foreign.id).archived


@pytest.mark.django_db
def test_delete_skips_malformed_workflow_steps(member, workspace):
    from tests.test_publish import make_workflow
    from tests.test_workflow_graph import driver_graph, step

    c = member("editor")
    pk = _create(c).json()["id"]
    g = driver_graph()
    g["steps"] += ["not a step", step("k1", "Odd", "knowledge", knowledge_id=True), step("k2", "Text id", "knowledge", knowledge_id=str(pk))]
    make_workflow(workspace, g)
    assert c.delete(f"/api/knowledge/{pk}").status_code == 204
