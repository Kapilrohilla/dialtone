"""Calls dashboard: live calls from the LiveKit API, call history from LiveKit webhooks.

Listens on 127.0.0.1 by default; reach it from your laptop with an SSH tunnel
(`make tunnel`). It shows caller phone numbers, so don't expose it publicly.
"""

import asyncio
import logging
import os
import sqlite3
import time
from pathlib import Path

from aiohttp import web
from dotenv import load_dotenv
from livekit import api
from livekit.protocol.models import ParticipantInfo

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("dashboard")

LIVEKIT_URL = os.getenv("LIVEKIT_URL", "ws://127.0.0.1:7880").replace("ws://", "http://").replace("wss://", "https://")
API_KEY = os.environ["LIVEKIT_API_KEY"]
API_SECRET = os.environ["LIVEKIT_API_SECRET"]
HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.getenv("DASHBOARD_PORT", "8787"))
DB_PATH = os.getenv("DASHBOARD_DB", "/data/calls.db")
STATIC = Path(__file__).parent / "static"

KIND_NAMES = {v: k.lower() for k, v in ParticipantInfo.Kind.items()}


# --- storage -----------------------------------------------------------------

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS calls (
                room            TEXT PRIMARY KEY,
                started_at      INTEGER,
                answered_at     INTEGER,
                ended_at        INTEGER,
                caller          TEXT,
                called          TEXT,
                sip_call_id     TEXT,
                agent_joined_at INTEGER,
                end_reason      TEXT
            )"""
        )


def upsert(room: str, **fields) -> None:
    fields = {k: v for k, v in fields.items() if v is not None}
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO calls (room) VALUES (?)", (room,))
        if fields:
            cols = ", ".join(f"{k} = COALESCE({k}, ?)" for k in fields)  # first value wins
            conn.execute(f"UPDATE calls SET {cols} WHERE room = ?", (*fields.values(), room))


def set_ended(room: str, ended_at: int, reason: str | None) -> None:
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO calls (room) VALUES (?)", (room,))
        conn.execute("UPDATE calls SET ended_at = ?, end_reason = ? WHERE room = ?", (ended_at, reason, room))


# --- webhook -----------------------------------------------------------------

receiver = api.WebhookReceiver(api.TokenVerifier(API_KEY, API_SECRET))


async def webhook(request: web.Request) -> web.Response:
    body = await request.text()
    try:
        event = receiver.receive(body, request.headers.get("Authorization", ""))
    except Exception:
        logger.warning("rejected webhook with invalid signature")
        return web.Response(status=401)

    room = event.room.name
    ts = int(event.created_at) or int(time.time())

    if event.event == "room_started":
        upsert(room, started_at=int(event.room.creation_time) or ts)
    elif event.event == "participant_joined":
        p = event.participant
        if p.kind == ParticipantInfo.Kind.SIP:
            a = p.attributes
            upsert(
                room,
                started_at=ts,
                answered_at=ts,
                caller=a.get("sip.phoneNumber"),
                called=a.get("sip.trunkPhoneNumber"),
                sip_call_id=a.get("sip.callID"),
            )
        elif p.kind == ParticipantInfo.Kind.AGENT:
            upsert(room, started_at=ts, agent_joined_at=ts)
    elif event.event == "room_finished":
        reason = api.RoomEndReason.Name(event.room_end_reason).removeprefix("ROOM_END_").lower()
        set_ended(room, ts, reason)

    return web.Response(text="ok")


# --- API ---------------------------------------------------------------------

def participant_view(p) -> dict:
    return {
        "identity": p.identity,
        "kind": KIND_NAMES.get(p.kind, str(p.kind)),
        "joined_at": int(p.joined_at),
        "phone": p.attributes.get("sip.phoneNumber"),
        "call_status": p.attributes.get("sip.callStatus"),
        "tracks": len(p.tracks),
    }


async def state(request: web.Request) -> web.Response:
    lk: api.LiveKitAPI = request.app["lk"]
    now = int(time.time())
    result: dict = {"now": now, "server": {"ok": True, "error": None}}

    try:
        rooms = (await lk.room.list_rooms(api.ListRoomsRequest())).rooms
        parts = await asyncio.gather(
            *(lk.room.list_participants(api.ListParticipantsRequest(room=r.name)) for r in rooms)
        )
        result["live"] = sorted(
            (
                {
                    "room": r.name,
                    "created_at": int(r.creation_time),
                    "participants": [participant_view(p) for p in ps.participants],
                }
                for r, ps in zip(rooms, parts)
            ),
            key=lambda x: -x["created_at"],
        )
        trunks = (await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())).items
        rules = (await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())).items
        result["trunks"] = [
            {"id": t.sip_trunk_id, "name": t.name, "numbers": list(t.numbers), "allowed": list(t.allowed_addresses)}
            for t in trunks
        ]
        result["rules"] = [
            {
                "id": r.sip_dispatch_rule_id,
                "name": r.name,
                "trunks": list(r.trunk_ids),
                "agents": [a.agent_name for a in r.room_config.agents],
            }
            for r in rules
        ]
    except Exception as e:
        logger.exception("LiveKit API call failed")
        result["server"] = {"ok": False, "error": str(e)}
        result.update(live=[], trunks=[], rules=[])

    with db() as conn:
        result["recent"] = [dict(r) for r in conn.execute("SELECT * FROM calls ORDER BY started_at DESC LIMIT 50")]
        day_start = now - (now % 86400)  # UTC midnight
        row = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(agent_joined_at IS NOT NULL) AS answered,
                      AVG(CASE WHEN ended_at IS NOT NULL AND answered_at IS NOT NULL
                               THEN ended_at - answered_at END) AS avg_duration
               FROM calls WHERE started_at >= ?""",
            (day_start,),
        ).fetchone()
        result["today"] = dict(row)

    return web.json_response(result)


async def index(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC / "index.html")


async def on_startup(app: web.Application) -> None:
    app["lk"] = api.LiveKitAPI(LIVEKIT_URL, API_KEY, API_SECRET)


async def on_cleanup(app: web.Application) -> None:
    await app["lk"].aclose()


def main() -> None:
    init_db()
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/state", state)
    app.router.add_post("/webhook", webhook)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    logger.info("dashboard on http://%s:%d (LiveKit %s)", HOST, PORT, LIVEKIT_URL)
    web.run_app(app, host=HOST, port=PORT, print=None)


if __name__ == "__main__":
    main()
