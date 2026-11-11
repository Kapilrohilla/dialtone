"""Load the Northwind Car Rentals example into a Dialtone workspace as a draft agent. Idempotent.

Run from server/ (it needs the Django settings and database):

    WORKSPACE=northwind python manage.py shell < ../examples/car-rental-agent/load.py

WORKSPACE is the slug of the workspace to load into (default "northwind", created if missing).
EXAMPLE_DIR points at this folder (default ../examples/car-rental-agent, relative to server/).
"""

import json
import os
import re
from pathlib import Path

from django.db import transaction

from knowledge.models import KnowledgeDocument, KnowledgeRevision
from voiceagents.models import Agent
from workflows.models import Workflow, WorkflowRevision
from workspaces.models import Workspace

EXAMPLE_DIR = Path(os.environ.get("EXAMPLE_DIR", "../examples/car-rental-agent"))
WORKSPACE = os.environ.get("WORKSPACE", "northwind")


def script_sections(text: str) -> list[dict]:
    """script.md: every "## Title" starts a section; anything before the first one is a comment."""
    sections = []
    for chunk in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        title, _, body = chunk.partition("\n")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        sections.append({"id": slug, "title": title.strip(), "body": body.strip()})
    return sections


def knowledge_doc(ws, title: str, body: str) -> KnowledgeDocument:
    doc = KnowledgeDocument.objects.filter(workspace=ws, title=title, archived=False).first()
    if doc is None:
        doc = KnowledgeDocument.objects.create(workspace=ws, title=title)
    cur = doc.revisions.order_by("-number").first()
    if cur is None or cur.body_md != body:
        KnowledgeRevision.objects.create(document=doc, number=(cur.number + 1) if cur else 1, body_md=body)
    return doc


def workflow(ws, spec: dict) -> Workflow:
    wf = Workflow.objects.filter(workspace=ws, name=spec["name"], archived=False).first()
    if wf is None:
        wf = Workflow.objects.create(workspace=ws, name=spec["name"],
                                     dead_air_enabled=spec.get("dead_air_enabled", True))
    cur = wf.revisions.order_by("-number").first()
    if cur is None or cur.graph != spec["graph"]:
        WorkflowRevision.objects.create(workflow=wf, number=(cur.number + 1) if cur else 1, graph=spec["graph"])
    return wf


@transaction.atomic
def load() -> Agent:
    config = json.loads((EXAMPLE_DIR / "agent.json").read_text(encoding="utf-8"))
    ws, _ = Workspace.objects.get_or_create(slug=WORKSPACE, defaults={"name": "Northwind Car Rentals"})
    docs = [knowledge_doc(ws, k["title"], (EXAMPLE_DIR / k["file"]).read_text(encoding="utf-8"))
            for k in config.get("knowledge", [])]
    fields = {
        "description": config["description"],
        "language": config["language"],
        "persona_name": config["persona_name"],
        "voice_id": config.get("voice_id", ""),
        "phone_number": config.get("phone_number", ""),
        "settings": config["settings"],
        "custom_expressions": config.get("custom_expressions", {}),
        "script": script_sections((EXAMPLE_DIR / config["script_file"]).read_text(encoding="utf-8")),
        "workflow": workflow(ws, config["workflow"]) if config.get("workflow") else None,
    }
    agent = Agent.objects.filter(workspace=ws, name=config["name"]).first()
    if agent is None:
        agent = Agent.objects.create(workspace=ws, name=config["name"], status=Agent.DRAFT, **fields)
    else:
        for key, value in fields.items():
            setattr(agent, key, value)
        agent.save()
    agent.knowledge.set(docs)
    return agent


loaded = load()
print(f"Loaded draft agent {loaded.name!r} (id {loaded.id}) into workspace {WORKSPACE!r}.")
