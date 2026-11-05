from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from knowledge.api import _add_revision
from knowledge.models import KnowledgeDocument
from voiceagents.models import Agent
from workspaces.models import Workspace

AGENT_NAME = "Driver lead qualifier"
KNOWLEDGE_TITLE = "Approved pricing and rules"

SCRIPT = [
    {
        "id": "greeting",
        "title": "Greeting",
        "body": "[[expr:happy]] नमस्ते! मैं Carrum Mobility से Priya बोल रही हूँ। [[expr:pause:1.2]] "
        "क्या मेरी बात {{lead.name}} जी से हो रही है?",
    },
    {
        "id": "city-and-licence",
        "title": "City and licence",
        "body": "[[expr:laugh]] अरे वाह, बहुत बढ़िया! क्या आपके पास commercial yellow plate है?",
    },
    {
        "id": "driver-hesitates",
        "title": "If the driver hesitates",
        "body": "[[expr:sad]] मैं आपकी बात समझ सकती हूँ। [[expr:whisper]] क्या मैं WhatsApp पर details भेज दूँ?",
    },
]


class Command(BaseCommand):
    help = "Seed the Carrum workspace with a draft agent and, if the file exists, its knowledge document. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument("--knowledge", default="../agent/knowledge.md", help="Markdown file (default relative to cwd)")

    @transaction.atomic
    def handle(self, *args, knowledge, **options):
        ws, _ = Workspace.objects.get_or_create(slug="carrum", defaults={"name": "Carrum Mobility"})
        agent, _ = Agent.objects.get_or_create(
            workspace=ws,
            name=AGENT_NAME,
            defaults={
                "description": "Qualifies driver-partner leads in Hindi and Hinglish.",
                "status": Agent.DRAFT,
                "script": SCRIPT,
            },
        )
        docs = 0
        path = Path(knowledge)
        if path.is_file():
            body = path.read_text(encoding="utf-8")
            doc = KnowledgeDocument.objects.filter(workspace=ws, title=KNOWLEDGE_TITLE).first()
            if doc is None:
                doc = KnowledgeDocument.objects.create(workspace=ws, title=KNOWLEDGE_TITLE)
            _add_revision(doc, body, None)  # no-op when the file is unchanged
            agent.knowledge.add(doc)
            docs = 1
        self.stdout.write(
            f"Seeded Carrum Mobility: 1 agent, {docs} knowledge document{'' if docs == 1 else 's'}"
        )
