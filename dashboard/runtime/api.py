"""Endpoints the voice agent calls at the start of and during every call (LiveKit JWT, identity agent-runtime)."""

import json
import logging
import math
import re
from datetime import datetime, timezone

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone as djtz
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from calls.models import Call, CallEvent
from voiceagents.models import Agent

from .auth import RUNTIME_IDENTITY, verify_agent

logger = logging.getLogger(__name__)

MAX_EVENTS = 200
EVENT_TYPES = {t for t, _ in CallEvent.TYPES}
SEQ_MAX = 2**31 - 1  # PositiveIntegerField
NOT_FOUND = {"detail": "No published agent for this number."}


def _unauthorized():
    logger.warning("rejected runtime request with invalid token")
    return JsonResponse({"detail": "Invalid token."}, status=401)


def _digits(value) -> str:
    # Leading zeros are trunk/international prefixes ("0", "00"), not part of the number.
    return re.sub(r"\D", "", str(value or "")).lstrip("0")


def _same_number(a: str, b: str) -> bool:
    """Digits-only match; the Indian country code "91" is optional on either side."""
    a, b = _digits(a), _digits(b)
    if not a or not b:
        return False
    return a == b or a == "91" + b or b == "91" + a


def find_published(number: str):
    """The published agent for `number`, or None when nothing (or more than one workspace) matches."""
    published = list(
        Agent.objects.filter(status=Agent.PUBLISHED, published_version__isnull=False)
        .select_related("published_version", "workspace")
    )
    matches = [a for a in published if a.phone_number and _same_number(a.phone_number, number)]
    if len(matches) == 1:
        return matches[0]
    if matches:
        logger.warning("number %s matches published agents in several workspaces", number)
        return None
    # Fallback while numbers aren't configured: the one workspace with a published agent.
    if len(published) == 1 and not any(_digits(a.phone_number) for a in published):
        return published[0]
    return None


@csrf_exempt
@require_GET
def config(request):
    if not verify_agent(request, RUNTIME_IDENTITY):
        return _unauthorized()
    agent = find_published(request.GET.get("number", ""))
    if agent is None:
        return JsonResponse(NOT_FOUND, status=404)
    version = agent.published_version
    room = request.GET.get("room", "").strip()
    if room:
        # First value wins: a call keeps the version it started with.
        Call.record_first(room[:255], workspace=agent.workspace, agent_version=version)
    return JsonResponse({"version_id": version.id, "workspace": agent.workspace.slug, "snapshot": version.snapshot})


def _seq(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= SEQ_MAX:
        return None
    return value


def _at(value) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        try:
            return datetime.fromtimestamp(value, timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    return djtz.now()


def _event(raw):
    """A CallEvent (unsaved, without call) or None when the event is malformed or of an unknown type."""
    if not isinstance(raw, dict):
        return None
    seq = _seq(raw.get("seq"))
    if seq is None or raw.get("type") not in EVENT_TYPES or not isinstance(raw.get("payload"), dict):
        return None
    return CallEvent(seq=seq, type=raw["type"], payload=raw["payload"], at=_at(raw.get("at")))


@csrf_exempt
@require_POST
def events(request):
    if not verify_agent(request, RUNTIME_IDENTITY):
        return _unauthorized()
    try:
        body = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    if not isinstance(body, dict) or not isinstance(body.get("room"), str) or not body["room"].strip():
        return JsonResponse({"detail": "Missing room."}, status=400)
    raw = body.get("events", [])
    if not isinstance(raw, list):
        return JsonResponse({"detail": "events must be a list."}, status=400)
    if len(raw) > MAX_EVENTS:
        return JsonResponse({"detail": f"At most {MAX_EVENTS} events per batch."}, status=413)

    parsed = [_event(e) for e in raw]
    valid = [e for e in parsed if e is not None]
    skipped = len(parsed) - len(valid)
    with transaction.atomic():
        call = Call.record_first(body["room"].strip()[:255])
        for e in valid:
            e.call = call
        seqs = {e.seq for e in valid}
        before = CallEvent.objects.filter(call=call, seq__in=seqs).count()
        CallEvent.objects.bulk_create(valid, ignore_conflicts=True)
        after = CallEvent.objects.filter(call=call, seq__in=seqs).count()
    return JsonResponse({"stored": after - before, "skipped": skipped})
