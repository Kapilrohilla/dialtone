"""Seed a demo agent for a fictional company, Northwind Car Rentals, so a fresh install has something to try.

Everything here is made up: the company, its cities, its fleet and its prices.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from knowledge.api import _add_revision
from knowledge.models import KnowledgeDocument
from voiceagents.models import Agent
from workflows.models import Workflow, WorkflowRevision
from workspaces.models import Workspace

COMPANY = "Northwind Car Rentals"
AGENT_NAME = "Rental enquiry assistant"
PERSONA = "Maya"
LANGUAGE = "English"
KNOWLEDGE_TITLE = "Rental policies and pricing"
WORKFLOW_NAME = "Rental enquiry"

SCRIPT = [
    {
        "id": "your-job",
        "title": "Your job",
        "body": """Your job: call people who asked about renting a car from Northwind Car Rentals, find out what they
need, suggest the rental plan that fits, answer simple questions, and confirm whether they want a booking
specialist to call them back. The goal is well-informed customers who really want to book, not the most
calls tagged Interested.""",
    },
    {
        "id": "opening",
        "title": "Opening",
        "body": """1. Opening: you speak first, with the opening line you are given. Then:
   - Busy: ask when to call back, and record a callback.
   - Not interested: thank them politely and close. Don't pitch.
   - Never say they made a booking or a request unless the lead record says so.""",
    },
    {
        "id": "qualify",
        "title": "Qualify",
        "body": """2. Qualify, one question at a time, skipping anything the lead record or the caller already answered:
   - City: "Which city would you like to pick the car up in?" Northwind has branches in the cities listed in
     the approved rental policies. If they need another city, say so politely.
   - Licence: "Do you have a valid driving licence in your own name?" It must be valid for the whole rental.
   - Dates: "When do you need the car, and for how long?"
   - Car: "What kind of car are you looking for: something compact, a family car, or a van?"
   If an answer is unclear, clarify once, at most twice, then move on.
   Never ask for card numbers, bank details or identity document numbers.
   If the caller clearly can't rent (no valid licence, unsupported city), explain politely and close.""",
    },
    {
        "id": "pick-the-plan",
        "title": "Pick the plan",
        "body": """3. Pick the plan:
   - Daily rental: for trips of a few days, picked up and returned at a branch.
   - Weekly rental: for a week or more, at a lower daily price.
   - Monthly subscription: a car for a month at a time, with maintenance and insurance included.
   Choose by the caller's dates, car type and budget, following the approved rental policies. If you can't
   tell which plan fits, keep it general and leave the plan to the booking specialist.""",
    },
    {
        "id": "explain-it",
        "title": "Explain it",
        "body": """4. Explain it in a line or two, with one or two relevant benefits, not every detail. For example:
   - Weekly rental: "With a weekly rental you keep the car for the whole week and pay less per day than a
     daily rental."
   - Monthly subscription: "The monthly subscription gives you a car for a month at a time, and
     maintenance and insurance are included."
   Then ask: "Does that sound like it would work for you?" If they have a concern, handle it first.""",
    },
    {
        "id": "questions-and-objections",
        "title": "Questions and objections",
        "body": """5. Questions and objections: answer only what was asked, briefly, and settle the concern before asking
   about interest again.
   - Prices, deposits, fees, offers: quote only the approved figures for the caller's city and plan. Never
     guess a price.
   - Insurance: "Basic cover is included in every rental; the booking specialist can explain the options."
   - "I need to think about it": "Of course. Is there anything I can clear up: the price, the car, or the
     dates?"
   - Already comparing other companies: "That makes sense. Would it help if I told you what is included
     with Northwind?"
   Never invent discounts, free upgrades or waived fees, and never argue. If the answer needs detail you
   don't have, offer a call with a booking specialist.""",
    },
    {
        "id": "confirm-interest",
        "title": "Confirm interest",
        "body": """6. Confirm interest: "If you'd like, I can have one of our booking specialists call you to confirm the
   car and the dates. Would that be all right?"
   Picking up, listening, being polite or asking a general question is not interest. Interested means the
   caller says they want to book, agrees to a call from a booking specialist, or asks for the next step.
   Note whether interest is confirmed, conditional or tentative.""",
    },
    {
        "id": "close",
        "title": "Close",
        "body": """7. Close: call `record_outcome`, then say the matching line, then call `end_call`.
   - Interested: "Thank you. I'm passing your details to our booking team, and a specialist will call you
     to confirm everything."
   - Not interested: "No problem at all. Thank you for your time."
   - Not eligible: "I understand. With our current rental rules we can't go ahead this time. Thank you."
   - Callback: "Sure, you said <the time they gave>. I'm noting that down for a callback." Never promise a
     callback time or say the team has already been in touch.""",
    },
]

KNOWLEDGE = """# Northwind Car Rentals: rental policies and pricing

Northwind Car Rentals is a fictional company used for the Dialtone demo. All figures are examples.

## Branches
Northwind has branches in Seattle, Portland, San Francisco, Denver and Austin. Cars are picked up and
returned at a branch during opening hours (8 am to 8 pm, every day).

## Who can rent
- Renters must be at least 21 years old and hold a full driving licence, valid for the whole rental, in
  their own name.
- A payment card in the renter's name is needed at pick-up. Never take card details on the phone.

## Plans and example prices
| Plan | Compact | Family car | Van |
|---|---|---|---|
| Daily rental (per day) | $45 | $65 | $90 |
| Weekly rental (per week) | $270 | $390 | $540 |
| Monthly subscription (per month) | $900 | $1,250 | $1,700 |

- Daily and weekly rentals include 200 miles per day; extra miles are $0.25 each.
- The monthly subscription includes maintenance, insurance and 1,500 miles per month.
- A refundable deposit of $200 is held at pick-up for daily and weekly rentals.

## Insurance
Basic cover is included in every rental. Full cover with no excess is $15 per day. Booking specialists
explain the options; the assistant only says that basic cover is included.

## Changes and cancellations
Free cancellation up to 48 hours before pick-up. Later cancellations cost one day's rental.

## What the assistant must not do
Never offer discounts, free upgrades or waived fees, and never promise a specific car model.
"""


def _step(id, type, name, x, y, **extra):
    return {"id": id, "type": type, "name": name, "position": {"x": x, "y": y}, **extra}


def _path(src, dst, label):
    return {"from": src, "to": dst, "label": label}


# Every prompt is one plain line the agent says (no prices). Laid out top to bottom like the console's own
# layout: cards are 260x88, rows 180px apart leave room for the path labels.
ENQUIRY_GRAPH = {
    "steps": [
        _step("greeting", "start", "Greeting", 290, 0,
              prompt="Hi, this is Maya from Northwind Car Rentals. Do you have two minutes to talk about your rental?"),
        _step("ask_city", "prompt", "Ask city", 290, 180, prompt="Which city would you like to pick the car up in?"),
        _step("ask_licence", "collect", "Ask licence and dates", 145, 360, field="licence",
              prompt="Do you have a valid driving licence in your own name, and when do you need the car?"),
        _step("explain_plan", "prompt", "Explain the plan", 0, 540,
              prompt="[[expr:excited]]Shall I tell you about our rental plans in {{lead.city}}?[[expr:pause:1]]"),
        _step("end_interested", "end", "End: interested", -290, 720, outcome="INTERESTED",
              prompt="Great, I'm sending your details to our booking team."),
        _step("schedule_callback", "end", "Schedule a call back", 0, 720, outcome="CBR",
              prompt="No problem, when would be a good time to call you back?"),
        _step("transfer", "transfer", "Transfer to a booking specialist", 290, 720,
              prompt="Let me put you through to one of our booking specialists."),
        _step("end_city", "end", "End: city not served", 435, 360, outcome="NE",
              prompt="We don't have a branch there yet, but thank you for your time."),
        _step("end_no_licence", "end", "End: not eligible", 290, 540, outcome="NE",
              prompt="We can't rent without a valid licence, but thank you for your time."),
    ],
    "paths": [
        _path("greeting", "ask_city", "Next"),
        _path("ask_city", "ask_licence", "City we serve"),
        _path("ask_city", "end_city", "Other city"),
        _path("ask_licence", "explain_plan", "Has licence"),
        _path("ask_licence", "end_no_licence", "No licence"),
        _path("explain_plan", "end_interested", "Interested"),
        _path("explain_plan", "schedule_callback", "Busy"),
        _path("explain_plan", "transfer", "Upset"),
    ],
}


class Command(BaseCommand):
    help = (
        f"Seed a demo agent for the fictional {COMPANY} (persona {PERSONA}): script, workflow and knowledge "
        "document. Creates the default workspace if there is none. Idempotent; never publishes."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--workspace", default=None,
            help="Workspace slug to seed into (default: the oldest workspace, created if there is none)",
        )
        parser.add_argument(
            "--knowledge", default=None,
            help="Markdown file to use as the knowledge document instead of the built-in demo policies",
        )

    @transaction.atomic
    def handle(self, *args, workspace, knowledge, **options):
        if workspace is None:
            ws, _ = Workspace.ensure_default()
        else:
            try:
                ws = Workspace.objects.get(slug=workspace)
            except Workspace.DoesNotExist:
                raise CommandError(f"No workspace with slug '{workspace}'.")
        if knowledge is None:
            body = KNOWLEDGE
        else:
            path = Path(knowledge)
            if not path.is_file():
                raise CommandError(f"{knowledge} not found")
            body = path.read_text(encoding="utf-8")

        agent, _ = Agent.objects.get_or_create(
            workspace=ws,
            name=AGENT_NAME,
            defaults={
                "description": f"Follows up {COMPANY} rental enquiries in English.",
                "status": Agent.DRAFT,
                "language": LANGUAGE,
                "persona_name": PERSONA,
                "script": SCRIPT,
            },
        )
        # Names aren't unique (an operator may have made a copy), so get_or_create could raise.
        if not Workflow.objects.filter(workspace=ws, name=WORKFLOW_NAME).exists():
            workflow = Workflow.objects.create(workspace=ws, name=WORKFLOW_NAME)
            # Same shape the workflows API saves: revision 1 holds the graph.
            WorkflowRevision.objects.create(workflow=workflow, number=1, graph=ENQUIRY_GRAPH)
        doc = KnowledgeDocument.objects.filter(workspace=ws, title=KNOWLEDGE_TITLE).first()
        if doc is None:
            doc = KnowledgeDocument.objects.create(workspace=ws, title=KNOWLEDGE_TITLE)
        _add_revision(doc, body, None)  # no-op when the text is unchanged
        agent.knowledge.add(doc)
        self.stdout.write(f"Seeded the {COMPANY} demo into '{ws.name}': 1 agent, 1 workflow, 1 knowledge document")
