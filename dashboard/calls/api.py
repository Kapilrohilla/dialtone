"""Console API: calls history, call detail, CSV export, live calls, dashboard and phone numbers.

Every queryset is scoped to the requester's workspace; calls whose workspace is still null are never
returned (ruling R18). LiveKit is reached only through `livekit_state` module attributes, so tests can
monkeypatch `fetch_livekit_state`, `transfer` and `end_call`.
"""

import csv
import io
import logging
import math
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from asgiref.sync import async_to_sync
from django.conf import settings
from django.db.models import Count, F, Func, Q, Value
from django.db.models.functions import Trim, Upper
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from voiceagents.models import Agent
from workspaces.permissions import CanEdit, IsMember, workspace_for

from . import livekit_state
from .models import Call, CallEvent
from .numbers import same_number
from .outcomes import DISPLAY_OUTCOME, DROPPED, GROUPS, NOT_REACHED, codes_for, display_outcome
from .serializers import (
    _dict,
    _text,
    call_detail,
    call_row,
    captured_fields,
    duration_s,
    latest,
    outcome_data,
    report_of,
    transcript,
)

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
PAGE_SIZE = 25
CSV_MAX_ROWS = 10_000
LIVE_TAIL = 50
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class _Base(APIView):
    """Members read; editors and up act."""

    def get_permissions(self):
        return [CanEdit()] if self.request.method not in ("GET", "HEAD", "OPTIONS") else [IsMember()]


def calls_of(request):
    return Call.objects.filter(workspace=workspace_for(request))


# --- filters ----------------------------------------------------------------------------------------

def parse_date(value, name):
    if not DATE_RE.match(value or ""):
        raise ValidationError({name: ["Use a date like 2026-11-05."]})
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError({name: ["Use a date like 2026-11-05."]})


def day_start(d: date) -> datetime:
    """Midnight of `d` in Asia/Kolkata."""
    return datetime.combine(d, time.min, tzinfo=IST)


def _int(value, name, minimum=None):
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValidationError({name: ["Must be a whole number."]})
    if minimum is not None and n < minimum:
        raise ValidationError({name: [f"Must be at least {minimum}."]})
    return n


def filtered_calls(request):
    """The workspace's calls with the list filters applied, newest first; 400 on a bad filter."""
    p = request.query_params
    qs = calls_of(request).select_related("report", "agent_version")
    q = p.get("q", "").strip()
    if digits := re.sub(r"\D", "", q):
        qs = qs.annotate(
            caller_digits=Func(F("caller"), Value(r"\D"), Value(""), Value("g"), function="regexp_replace")
        ).filter(caller_digits__contains=digits)
    if outcome := p.get("outcome", "").strip():
        if outcome not in GROUPS:
            raise ValidationError({"outcome": [f"Choose one of: {', '.join(GROUPS)}."]})
        qs = qs.annotate(code=Upper(Trim("report__disposition")))
        match = Q(code__in=codes_for(outcome))
        if outcome == DROPPED:  # codes outside the 14 show as Dropped too
            match |= Q(report__isnull=False) & ~Q(code="") & ~Q(code__in=list(DISPLAY_OUTCOME))
        qs = qs.filter(match)
    if agent := p.get("agent", "").strip():
        qs = qs.filter(agent_version__agent_id=_int(agent, "agent"))
    if mood := p.get("mood", "").strip():
        qs = qs.filter(report__final_mood__iexact=mood)
    if city := p.get("city", "").strip():
        qs = qs.filter(report__data__outcome__city__icontains=city)
    if p.get("from"):
        qs = qs.filter(started_at__gte=day_start(parse_date(p["from"], "from")))
    if p.get("to"):
        qs = qs.filter(started_at__lt=day_start(parse_date(p["to"], "to") + timedelta(days=1)))
    return qs.order_by(F("started_at").desc(nulls_last=True), "-id")


# --- calls ------------------------------------------------------------------------------------------

class CallListView(_Base):
    def get(self, request):
        qs = filtered_calls(request)
        page = _int(request.query_params.get("page", 1), "page", minimum=1)
        count = qs.count()
        offset = (page - 1) * PAGE_SIZE
        rows = [call_row(c) for c in qs[offset:offset + PAGE_SIZE]]
        return Response({"results": rows, "count": count, "page": page,
                         "pages": max(1, math.ceil(count / PAGE_SIZE))})


class CallDetailView(_Base):
    def get(self, request, room):
        call = get_object_or_404(calls_of(request).select_related("report", "agent_version"), room=room)
        events = list(CallEvent.objects.filter(call=call).order_by("seq"))
        return Response(call_detail(call, events))


PHONE_LIKE = re.compile(r"^\+?[\d\s()-]+$")


def csv_cell(value):
    """Keep spreadsheet apps from running cell text as a formula (phone numbers stay as they are)."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r") and not PHONE_LIKE.match(value):
        return "'" + value
    return value


class CallExportView(_Base):
    HEADERS = ["When", "Caller", "Agent", "Outcome", "Mood", "Duration", "Summary"]

    def get(self, request):
        qs = filtered_calls(request)[:CSV_MAX_ROWS]
        buf = io.StringIO()
        buf.write("﻿")  # BOM so Excel reads UTF-8 (Devanagari) correctly
        writer = csv.writer(buf)
        writer.writerow(self.HEADERS)
        for call in qs:
            row = call_row(call)
            when = timezone.localtime(call.started_at, IST).strftime("%Y-%m-%d %H:%M") if call.started_at else ""
            duration = row["duration_s"]
            writer.writerow([csv_cell(v) for v in (
                when, row["caller"], row["agent_name"] or "", row["outcome"], row["mood"],
                "" if duration is None else duration, row["summary"],
            )])
        response = HttpResponse(buf.getvalue().encode("utf-8"), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="calls.csv"'
        return response


class NeedsPersonView(_Base):
    def post(self, request, room):
        call = get_object_or_404(calls_of(request), room=room)
        data = request.data if isinstance(request.data, dict) else {}
        if "handled" not in data and "needs_person" in data:
            if data["needs_person"] is not True:
                raise ValidationError({"needs_person": ["Must be true or false."]})
            call.needs_person, call.needs_person_handled_at = True, None  # mark for a call back
        else:
            handled = data.get("handled")
            if not isinstance(handled, bool):
                raise ValidationError({"handled": ["Must be true or false."]})
            call.needs_person_handled_at = timezone.now() if handled else None
        call.save(update_fields=["needs_person", "needs_person_handled_at"])
        return Response({"room": call.room, "needs_person": call.needs_person,
                         "handled_at": call.needs_person_handled_at})


# --- dashboard --------------------------------------------------------------------------------------

class DashboardView(_Base):
    def get(self, request):
        workspace = workspace_for(request)
        raw = request.query_params.get("date")
        day = parse_date(raw, "date") if raw else timezone.localtime(timezone.now(), IST).date()
        start = day_start(day)
        end = day_start(day + timedelta(days=1))
        calls = Call.objects.filter(workspace=workspace)

        today = list(calls.filter(started_at__gte=start, started_at__lt=end).select_related("report"))
        groups = [display_outcome(r.disposition if (r := report_of(c)) else "") for c in today]
        connected = [c for c, g in zip(today, groups) if g != NOT_REACHED]
        durations = [d for c in connected if (d := duration_s(c)) is not None]

        week = (
            calls.filter(started_at__gte=day_start(day - timedelta(days=6)), started_at__lt=end,
                         report__isnull=False)
            .values("report__disposition").annotate(n=Count("id"))
        )
        week_counts = dict.fromkeys(GROUPS, 0)
        for row in week:
            if group := display_outcome(row["report__disposition"]):
                week_counts[group] += row["n"]

        needs = (
            calls.filter(needs_person=True, needs_person_handled_at__isnull=True)
            .select_related("report").order_by(F("started_at").desc(nulls_last=True), "-id")[:10]
        )
        live = Agent.objects.filter(workspace=workspace, status=Agent.PUBLISHED).first()
        return Response({
            "calls_today": len(today),
            "connected_pct": round(100 * len(connected) / len(today)) if today else None,
            "interested": sum(1 for g in groups if g == "Interested"),
            "avg_duration_s": round(sum(durations) / len(durations)) if durations else None,
            "needs_person": [
                {"room": c.room, "caller": c.caller, "reason": _text(outcome_data(c).get("reason")),
                 "at": c.started_at}
                for c in needs
            ],
            "outcomes_week": [{"outcome": g, "count": n} for g, n in week_counts.items()],
            "live_agent": {"id": live.id, "name": live.name, "phone_number": live.phone_number} if live else None,
        })


# --- live -------------------------------------------------------------------------------------------

def livekit():
    return async_to_sync(livekit_state.fetch_livekit_state)()


def _sip_participant(room_state):
    for p in room_state.get("participants") or []:
        if isinstance(p, dict) and p.get("kind") == "sip" and p.get("identity"):
            return p
    return None


def _latest_city(events) -> str:
    for e in reversed(events):
        if e.type == CallEvent.FIELD_CAPTURED:
            p = _dict(e.payload)
            if p.get("field") == "city" and isinstance(p.get("value"), str) and p["value"]:
                return p["value"]
    return ""


def _step_path(events) -> list[str]:
    """Step names in the order the call entered them, consecutive repeats collapsed."""
    path: list[str] = []
    for e in events:
        if e.type != CallEvent.STEP_ENTERED:
            continue
        name = _dict(e.payload).get("step_name")
        if isinstance(name, str) and name and (not path or path[-1] != name):
            path.append(name)
    return path


class LiveListView(_Base):
    def get(self, request):
        rooms = [r for r in livekit().get("live") or [] if isinstance(r, dict) and r.get("room")]
        calls = {c.room: c for c in calls_of(request).filter(room__in=[r["room"] for r in rooms])}
        events: dict[int, list] = {c.id: [] for c in calls.values()}
        for e in CallEvent.objects.filter(call_id__in=list(events)).order_by("call_id", "seq"):
            events[e.call_id].append(e)
        out = []
        for r in rooms:
            call = calls.get(r["room"])
            if call is None:
                continue
            evs = events[call.id]
            sip = _sip_participant(r) or {}
            started = call.started_at
            if started is None and isinstance(r.get("created_at"), int) and r["created_at"]:
                started = datetime.fromtimestamp(r["created_at"], tz=IST)
            out.append({
                "room": call.room,
                "caller": call.caller or _text(sip.get("phone")),
                "city": _latest_city(evs),
                "started_at": started,
                "step_path": _step_path(evs),
                "captured": captured_fields(evs),
                "current_step": latest(evs, CallEvent.STEP_ENTERED, "step_name"),
                "mood": latest(evs, CallEvent.MOOD, "label"),
                "transcript_tail": transcript(evs)[-LIVE_TAIL:],
            })
        return Response(out)


class _LiveAction(_Base):
    def live_room(self, room):
        """The live room's state if `room` is this workspace's call and is live now; else 404."""
        get_object_or_404(calls_of(self.request), room=room)
        state = livekit()
        if not _dict(state.get("server")).get("ok", True):
            return None, Response({"detail": "Couldn't reach the call server."}, status=502)
        for r in state.get("live") or []:
            if isinstance(r, dict) and r.get("room") == room:
                return r, None
        raise Http404("This call isn't live.")

    def run(self, coro_fn, *args, done):
        try:
            async_to_sync(coro_fn)(*args)
        except Exception:
            logger.exception("LiveKit action failed")
            return Response({"detail": "The call server refused that; try again."}, status=502)
        return Response({"detail": done})


class LiveTransferView(_LiveAction):
    def post(self, request, room):
        get_object_or_404(calls_of(request), room=room)
        if not settings.HANDOFF_SIP_URI:
            return Response({"detail": "Live transfer isn't set up."}, status=409)
        live, error = self.live_room(room)
        if error:
            return error
        caller = _sip_participant(live)
        if caller is None:
            raise Http404("No caller on this call.")
        return self.run(livekit_state.transfer, room, caller["identity"], settings.HANDOFF_SIP_URI,
                        done="Transferred.")


class LiveEndView(_LiveAction):
    def post(self, request, room):
        _, error = self.live_room(room)
        if error:
            return error
        return self.run(livekit_state.end_call, room, done="Call ended.")


# --- phone numbers ----------------------------------------------------------------------------------

class PhoneNumbersView(_Base):
    def get(self, request):
        workspace = workspace_for(request)
        ours = list(
            Agent.objects.filter(workspace=workspace).exclude(status=Agent.ARCHIVED).exclude(phone_number="")
            .order_by(F("status").desc(), "-updated_at")  # "published" sorts before "draft"
            .values_list("name", "phone_number")
        )
        theirs = list(Agent.objects.exclude(workspace=workspace).exclude(phone_number="")
                      .values_list("phone_number", flat=True))
        out = []
        for trunk in livekit().get("trunks") or []:
            if not isinstance(trunk, dict):
                continue
            for number in trunk.get("numbers") or []:
                name = next((n for n, phone in ours if same_number(phone, number)), None)
                if name is None and any(same_number(phone, number) for phone in theirs):
                    continue  # another workspace's number
                out.append({"number": number, "trunk_name": _text(trunk.get("name")), "agent_name": name})
        return Response(out)
