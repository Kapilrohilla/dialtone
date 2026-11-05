import pytest

from tests.helpers import assert_isolated
from tests.test_workflow_graph import driver_graph, path, step
from workflows.models import Workflow, WorkflowRevision


@pytest.mark.django_db
def test_save_creates_revision_and_returns_errors(member):
    c = member("editor")
    r = c.post("/api/workflows", {"name": "Onboarding"}, format="json")
    assert r.status_code == 201
    pk = r.json()["id"]
    assert r.json()["name"] == "Onboarding"
    ok = c.patch(f"/api/workflows/{pk}", {"graph": driver_graph()}, format="json")
    assert ok.status_code == 200 and ok.json()["errors"] == []
    assert ok.json()["current_revision"] == 1
    bad = driver_graph()
    bad["steps"].append(step("x", "Orphan", "end", outcome="NI"))
    r2 = c.patch(f"/api/workflows/{pk}", {"graph": bad}, format="json")
    assert r2.status_code == 200 and r2.json()["current_revision"] == 2
    assert any("Orphan" in e for e in r2.json()["errors"])
    assert WorkflowRevision.objects.filter(workflow_id=pk).count() == 2
    assert WorkflowRevision.objects.get(workflow_id=pk, number=2).saved_by == c.user
    got = c.get(f"/api/workflows/{pk}").json()
    assert got["graph"] == bad and got["errors"] == r2.json()["errors"]
    assert c.get(f"/api/workflows/{pk}/validate").json() == {"errors": r2.json()["errors"]}
    c.patch(f"/api/workflows/{pk}", {"name": "Renamed"}, format="json")
    assert WorkflowRevision.objects.filter(workflow_id=pk).count() == 2
    assert [w["name"] for w in c.get("/api/workflows").json()] == ["Renamed"]


@pytest.mark.django_db
def test_malformed_graph_saves_with_errors(member):
    c = member("editor")
    pk = c.post("/api/workflows", {"name": "W"}, format="json").json()["id"]
    r = c.patch(f"/api/workflows/{pk}", {"graph": {"steps": "x"}}, format="json")
    assert r.status_code == 200 and r.json()["errors"]
    assert c.patch(f"/api/workflows/{pk}", {"graph": "nope"}, format="json").status_code == 400


@pytest.mark.django_db
def test_knowledge_ids_scoped_to_workspace(member, other_workspace):
    from knowledge.models import KnowledgeDocument

    c = member("editor")
    foreign = KnowledgeDocument.objects.create(workspace=other_workspace, title="x")
    pk = c.post("/api/workflows", {"name": "W"}, format="json").json()["id"]
    g = driver_graph()
    g["steps"].append(step("k1", "Look up FAQ", "knowledge", knowledge_id=foreign.id))
    g["paths"] += [path("p9", "s4", "k1", "q"), path("p10", "k1", "e3", "done")]
    r = c.patch(f"/api/workflows/{pk}", {"graph": g}, format="json")
    assert any("does not exist" in e for e in r.json()["errors"])


@pytest.mark.django_db
def test_viewer_read_only(member):
    e, v = member("editor"), member("viewer")
    pk = e.post("/api/workflows", {"name": "W"}, format="json").json()["id"]
    assert v.get(f"/api/workflows/{pk}").status_code == 200
    assert v.post("/api/workflows", {"name": "x"}, format="json").status_code == 403
    assert v.patch(f"/api/workflows/{pk}", {"name": "x"}, format="json").status_code == 403


@pytest.mark.django_db
def test_workflows_isolated(member, other_workspace):
    c = member("editor")
    wf = Workflow.objects.create(workspace=other_workspace, name="theirs")
    assert_isolated(c, f"/api/workflows/{wf.id}")
    assert_isolated(c, f"/api/workflows/{wf.id}/validate")
    assert c.patch(f"/api/workflows/{wf.id}", {"name": "x"}, format="json").status_code == 404
    assert c.get("/api/workflows").json() == []
