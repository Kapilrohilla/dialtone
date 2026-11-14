"""Endpoints the voice agent calls at the start of and during every call (LiveKit JWT, identity agent-runtime)."""

import json
import logging
import math
import shutil
from datetime import datetime, timezone

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone as djtz
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from calls.models import Call, CallEvent
from calls.numbers import digits, same_number, strip_nul
from voiceagents.models import Agent
from voiceagents.publish import build_snapshot
from voiceagents.webcall import WEB_CALLER, is_web_room

from .auth import RUNTIME_IDENTITY, verify_agent

logger = logging.getLogger(__name__)

MAX_EVENTS = 200
EVENT_TYPES = {t for t, _ in CallEvent.TYPES}
SEQ_MAX = 2**31 - 1  # PositiveIntegerField
NOT_FOUND = {"detail": "No published agent for this number."}
NOT_FOUND_DRAFT = {"detail": "No agent to voice test."}


def _unauthorized():
    logger.warning("rejected runtime request with invalid token")
    return JsonResponse({"detail": "Invalid token."}, status=401)


def find_published(number: str):
    """The published agent for `number`, or None when nothing (or more than one workspace) matches."""
    published = list(
        Agent.objects.filter(status=Agent.PUBLISHED, published_version__isnull=False)
        .select_related("published_version", "workspace")
    )
    matches = [a for a in published if a.phone_number and same_number(a.phone_number, number)]
    if len(matches) == 1:
        return matches[0]
    if matches:
        logger.warning("number %s matches published agents in several workspaces", number)
        return None
    # Fallback while numbers aren't configured: the one workspace with a published agent.
    if len(published) == 1 and not any(digits(a.phone_number) for a in published):
        return published[0]
    return None


def recording_setting(workspace) -> dict:
    """Whether the agent should record this call: the workspace switch, unless the disk is nearly full."""
    if not workspace.recording_enabled:
        return {"enabled": False, "reason": "off"}
    try:
        settings.RECORDINGS_DIR.mkdir(mode=0o750, parents=True, exist_ok=True)
        free = shutil.disk_usage(settings.RECORDINGS_DIR).free
    except OSError:
        logger.warning("can't check free space for recordings", exc_info=True)
        return {"enabled": False, "reason": "disk_low"}
    if free < settings.RECORDING_MIN_FREE_BYTES:
        logger.warning("recording skipped: only %d MB free for recordings", free // 2**20)
        return {"enabled": False, "reason": "disk_low"}
    return {"enabled": True, "reason": None}


def _draft_config(agent_id: str, room: str):
    """A voice test (console, browser over WebRTC): the agent's draft, only ever for a `web-…` room."""
    if not is_web_room(room) or not agent_id.isdigit():
        return JsonResponse(NOT_FOUND_DRAFT, status=404)
    agent = (
        Agent.objects.select_related("workflow", "workspace")
        .exclude(status=Agent.ARCHIVED)
        .filter(pk=int(agent_id))
        .first()
    )
    if agent is None:
        return JsonResponse(NOT_FOUND_DRAFT, status=404)
    Call.record_first(room[:255], workspace=agent.workspace, caller=WEB_CALLER)
    # build_snapshot only reads: the draft is never saved as a version.
    # The account recording switch applies to voice tests too, so they can be played back in Call history.
    snapshot = {**build_snapshot(agent, 0), "account": {"recording": recording_setting(agent.workspace)}}
    return JsonResponse({
        "version_id": None,
        "draft": True,
        "workspace": agent.workspace.slug,
        "snapshot": snapshot,
    })


@csrf_exempt
@require_GET
def config(request):
    if not verify_agent(request, RUNTIME_IDENTITY):
        return _unauthorized()
    if request.GET.get("agent"):
        room = strip_nul(request.GET.get("room", "")).strip()
        return _draft_config(strip_nul(request.GET["agent"]).strip(), room)
    agent = find_published(request.GET.get("number", ""))
    if agent is None:
        return JsonResponse(NOT_FOUND, status=404)
    version = agent.published_version
    room = strip_nul(request.GET.get("room", "")).strip()
    if room:
        # First value wins: a call keeps the version it started with.
        Call.record_first(room[:255], workspace=agent.workspace, agent_version=version)
    # Account switches reach the next call without a republish: added here, never stored in the version.
    snapshot = {**version.snapshot, "account": {
        "dead_air_enabled": agent.workspace.dead_air_enabled,
        "recording": recording_setting(agent.workspace),
    }}
    return JsonResponse({"version_id": version.id, "workspace": agent.workspace.slug, "snapshot": snapshot})


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
        body = strip_nul(json.loads(request.body))
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
