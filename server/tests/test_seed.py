import re
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from knowledge.models import KnowledgeDocument
from voiceagents.models import Agent
from workspaces.models import Workspace

pytestmark = pytest.mark.django_db


def _seed(*args):
    out = StringIO()
    call_command("seed_demo", *args, stdout=out)
    return out.getvalue()


def test_seed_idempotent(tmp_path):
    f = tmp_path / "k.md"
    f.write_text("# Rules\nbe nice")
    _seed("--knowledge", str(f))
    out = _seed("--knowledge", str(f))
    assert Agent.objects.count() == 1 and KnowledgeDocument.objects.count() == 1
    agent = Agent.objects.get()
    assert agent.name == "Rental enquiry assistant" and agent.status == "draft"
    assert agent.persona_name == "Maya" and agent.language == "English"
    assert agent.knowledge.count() == 1
    assert "Seeded the Northwind Car Rentals demo" in out and "1 knowledge document" in out
    doc = KnowledgeDocument.objects.get()
    f.write_text("# Rules\nbe very nice")
    _seed("--knowledge", str(f))
    assert KnowledgeDocument.objects.count() == 1 and doc.revisions.count() == 2


def test_seed_uses_built_in_knowledge_and_creates_the_default_workspace():
    _seed()
    _seed()
    ws = Workspace.objects.get()
    assert ws.slug == "default"
    doc = KnowledgeDocument.objects.get(workspace=ws)
    assert doc.title == "Rental policies and pricing" and doc.revisions.count() == 1
    assert "Northwind Car Rentals" in doc.revisions.get().body_md
    assert list(Agent.objects.get().knowledge.all()) == [doc]


def test_seed_into_existing_workspace(workspace, other_workspace):
    _seed()  # the oldest workspace
    assert Agent.objects.get().workspace == workspace
    _seed("--workspace", "other")
    assert Agent.objects.filter(workspace=other_workspace).count() == 1
    with pytest.raises(CommandError):
        _seed("--workspace", "missing")


def test_seed_missing_knowledge_file_is_an_error(tmp_path):
    with pytest.raises(CommandError):
        _seed("--knowledge", str(tmp_path / "missing.md"))
    assert not Agent.objects.exists()


TITLES = ["Your job", "Opening", "Qualify", "Pick the plan", "Explain it",
          "Questions and objections", "Confirm interest", "Close"]


def test_seed_script_shape():
    _seed()
    agent = Agent.objects.get()
    assert [s["title"] for s in agent.script] == TITLES
    assert len({s["id"] for s in agent.script}) == 8
    for s in agent.script:
        assert s["body"].strip() and "$" not in s["body"]
        assert not re.search(r"\d", re.sub(r"^\d+\.", "", s["body"].strip()))
    assert "Weekly rental" in agent.script[3]["body"]
    assert "record_outcome" in agent.script[7]["body"]


def test_seed_keeps_existing_agents():
    _seed()
    agent = Agent.objects.get()
    agent.script[2]["body"] = "edited by an operator"
    agent.save()
    _seed()
    assert Agent.objects.get().script[2]["body"] == "edited by an operator"


def test_seed_creates_valid_rental_enquiry_workflow():
    from workflows.graph import validate
    from workflows.models import Workflow

    _seed()
    _seed()
    wf = Workflow.objects.get(name="Rental enquiry")  # exactly one after two runs
    assert wf.revisions.count() == 1 and wf.current.number == 1
    graph = wf.current.graph
    assert validate(graph, set()) == []
    assert all(isinstance(s.get("position"), dict) for s in graph["steps"])
    assert len(graph["steps"]) == 9 and len(graph["paths"]) == 8
    assert not Agent.objects.filter(workflow=wf).exists()


def test_seed_tolerates_two_workflows_with_the_seed_name():
    from workflows.models import Workflow

    _seed()
    ws = Workspace.objects.get()
    Workflow.objects.create(workspace=ws, name="Rental enquiry")  # names aren't unique; an operator made a copy
    _seed()
    assert Workflow.objects.filter(name="Rental enquiry").count() == 2
