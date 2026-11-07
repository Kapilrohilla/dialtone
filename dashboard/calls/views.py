import json
import logging
import time
from datetime import datetime, timezone

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone as djtz
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from livekit import api
from livekit.protocol.models import ParticipantInfo

from runtime.auth import REPORT_IDENTITY, verify_agent

from .livekit_state import fetch_livekit_state
from .models import Call, CallReport, Recording
from .numbers import strip_nul

logger = logging.getLogger(__name__)

if not (settings.LIVEKIT_API_KEY and settings.LIVEKIT_API_SECRET):
    # An empty secret would let anyone sign webhooks, so refuse to start.
    raise ImproperlyConfigured("LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be set")

receiver = api.WebhookReceiver(api.TokenVerifier(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET))


EGRESS_EVENTS = {"egress_started", "egress_updated", "egress_ended"}


def _dt(epoch: int) -> datetime:
    return datetime.fromtimestamp(epoch, timezone.utc)


@require_GET
def index(request):
    return redirect(settings.CONSOLE_URL)


@csrf_exempt
@require_POST
def webhook(request):
    try:
        event = receiver.receive(request.body.decode(), request.headers.get("Authorization", ""))
    except Exception:
        logger.warning("rejected webhook with invalid signature")
        return HttpResponse(status=401)

    if event.event in EGRESS_EVENTS:
        # Recording progress. Never fails the webhook: LiveKit would only retry the same event.
        try:
            rec = Recording.from_egress(event.egress_info)
            if rec is not None:
                level = logging.WARNING if rec.status == Recording.FAILED else logging.INFO
                logger.log(level, "recording %s: %s %s", event.event, rec.call.room, rec.status,
                           extra={"egress_id": rec.egress_id, "error": rec.error})
        except Exception:
            logger.exception("could not apply %s", event.event)
        return HttpResponse("ok")

    room = event.room.name
    ts = _dt(int(event.created_at) or int(time.time()))

    if event.event == "room_started":
        created = int(event.room.creation_time)
        Call.record_first(room, started_at=_dt(created) if created else ts)
    elif event.event == "participant_joined":
        p = event.participant
        if p.kind == ParticipantInfo.Kind.SIP:
            a = p.attributes
            Call.record_first(
                room,
                started_at=ts,
                answered_at=ts,
                caller=a.get("sip.phoneNumber"),
                called=a.get("sip.trunkPhoneNumber"),
                sip_call_id=a.get("sip.callID"),
            )
        elif p.kind == ParticipantInfo.Kind.AGENT:
            Call.record_first(room, started_at=ts, agent_joined_at=ts)
    elif event.event == "room_finished":
        reason = api.RoomEndReason.Name(event.room_end_reason).removeprefix("ROOM_END_").lower()
        Call.mark_ended(room, ts, reason)

    return HttpResponse("ok")


def _history() -> dict:
    recent = [c.as_dict() for c in Call.objects.select_related("report")[:50]]
    # Local (Asia/Kolkata) midnight; the aiohttp version used UTC midnight.
    day_start = djtz.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    todays = list(Call.objects.filter(started_at__gte=day_start))
    durations = [(c.ended_at - c.answered_at).total_seconds() for c in todays if c.ended_at and c.answered_at]
    today = {
        "total": len(todays),
        "answered": sum(1 for c in todays if c.agent_joined_at),
        "avg_duration": sum(durations) / len(durations) if durations else None,
    }
    return {"recent": recent, "today": today}


@login_required
@require_GET
async def state(request):
    result = {"now": int(time.time())}
    result.update(await fetch_livekit_state())
    result.update(await sync_to_async(_history)())
    return JsonResponse(result)


@csrf_exempt
@require_POST
def report_ingest(request):
    if not verify_agent(request, REPORT_IDENTITY):
        logger.warning("rejected call report with invalid token")
        return HttpResponse(status=401)

    try:
        report = strip_nul(json.loads(request.body))
    except (ValueError, UnicodeDecodeError):
        return HttpResponse("invalid JSON", status=400)
    if not isinstance(report, dict) or not isinstance(report.get("room"), str) or not report["room"]:
        return HttpResponse("missing room", status=400)

    CallReport.store(report)
    return HttpResponse("ok")


@login_required
@require_GET
def report_detail(request, room: str):
    report = get_object_or_404(CallReport, call__room=room)
    return JsonResponse(report.data)
