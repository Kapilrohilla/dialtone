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
    assert [s["title"] for s in agent.script] == ["Greeting", "City and licence", "If the driver hesitates"]
    assert "{{lead.name}}" in agent.script[0]["body"]
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
