from io import StringIO

import pytest
from django.core.management import call_command

from knowledge.models import KnowledgeDocument
from voiceagents.models import Agent


def _seed(*args):
    out = StringIO()
    call_command("seed_carrum", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_seed_idempotent(tmp_path):
    f = tmp_path / "k.md"
    f.write_text("# Rules\nbe nice")
    _seed("--knowledge", str(f))
    out = _seed("--knowledge", str(f))
    assert Agent.objects.count() == 1 and KnowledgeDocument.objects.count() == 1
    agent = Agent.objects.get()
    assert agent.name == "Driver lead qualifier" and agent.status == "draft"
    assert agent.knowledge.count() == 1
    assert "Seeded Carrum Mobility: 1 agent, 1 knowledge document" in out
    doc = KnowledgeDocument.objects.get()
    f.write_text("# Rules\nbe very nice")
    _seed("--knowledge", str(f))
    assert KnowledgeDocument.objects.count() == 1 and doc.revisions.count() == 2


@pytest.mark.django_db
def test_seed_without_knowledge_file(tmp_path):
    out = _seed("--knowledge", str(tmp_path / "missing.md"))
    assert "1 agent, 0 knowledge documents" in out
    assert Agent.objects.count() == 1 and KnowledgeDocument.objects.count() == 0
    assert "0 knowledge documents" in _seed()


TITLES = ["Your job", "Opening", "Qualify", "Pick the plan", "Explain it",
          "Questions and objections", "Confirm interest", "Close"]


@pytest.mark.django_db
def test_seed_script_matches_agent_fallback(tmp_path):
    import re
    _seed("--knowledge", str(tmp_path / "missing.md"))
    agent = Agent.objects.get()
    assert [s["title"] for s in agent.script] == TITLES
    assert len({s["id"] for s in agent.script}) == 8
    for s in agent.script:
        assert s["body"].strip() and "₹" not in s["body"]
        assert not re.search(r"\d", re.sub(r"^\d+\.", "", s["body"].strip()))
    assert "Uber Go rental" in agent.script[3]["body"]
    assert "record_outcome" in agent.script[7]["body"]


@pytest.mark.django_db
def test_seed_keeps_existing_agents(tmp_path):
    _seed("--knowledge", str(tmp_path / "missing.md"))
    agent = Agent.objects.get()
    agent.script[2]["body"] = "edited by an operator"
    agent.save()
    _seed("--knowledge", str(tmp_path / "missing.md"))
    assert Agent.objects.get().script[2]["body"] == "edited by an operator"


@pytest.mark.django_db
def test_seed_creates_valid_driver_onboarding_workflow(tmp_path):
    from workflows.graph import validate
    from workflows.models import Workflow

    _seed("--knowledge", str(tmp_path / "missing.md"))
    _seed("--knowledge", str(tmp_path / "missing.md"))
    wf = Workflow.objects.get(name="Driver onboarding")  # exactly one after two runs
    assert wf.revisions.count() == 1 and wf.current.number == 1
    graph = wf.current.graph
    assert validate(graph, set()) == []
    assert all(isinstance(s.get("position"), dict) for s in graph["steps"])
    assert len(graph["steps"]) == 9 and len(graph["paths"]) == 8
    assert not Agent.objects.filter(workflow=wf).exists()
