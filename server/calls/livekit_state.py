"""Live rooms, SIP trunks and dispatch rules from the LiveKit server API."""

import asyncio
import logging

from django.conf import settings
from livekit import api
from livekit.protocol.models import ParticipantInfo

logger = logging.getLogger(__name__)

KIND_NAMES = {v: k.lower() for k, v in ParticipantInfo.Kind.items()}


def participant_view(p) -> dict:
    return {
        "identity": p.identity,
        "kind": KIND_NAMES.get(p.kind, str(p.kind)),
        "joined_at": int(p.joined_at),
        "phone": p.attributes.get("sip.phoneNumber"),
        "call_status": p.attributes.get("sip.callStatus"),
        "tracks": len(p.tracks),
    }


async def fetch_livekit_state() -> dict:
    """Return {"server": {"ok", "error"}, "live", "trunks", "rules"}; never raises."""
    result: dict = {"server": {"ok": True, "error": None}}
    lk = None
    try:
        lk = api.LiveKitAPI(settings.LIVEKIT_URL, settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
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
    finally:
        if lk is not None:
            try:
                await lk.aclose()
            except Exception:
                logger.warning("closing the LiveKit API client failed", exc_info=True)
    return result


async def transfer(room: str, participant_identity: str, to_uri: str) -> None:
    """Transfer the SIP participant `participant_identity` in `room` to `to_uri`; raises on failure."""
    lk = api.LiveKitAPI(settings.LIVEKIT_URL, settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
    try:
        await lk.sip.transfer_sip_participant(
            api.TransferSIPParticipantRequest(
                room_name=room, participant_identity=participant_identity, transfer_to=to_uri
            )
        )
    finally:
        await lk.aclose()


async def end_call(room: str) -> None:
    """Delete `room`, which hangs up everyone in it; raises on failure."""
    lk = api.LiveKitAPI(settings.LIVEKIT_URL, settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
    try:
        await lk.room.delete_room(api.DeleteRoomRequest(room=room))
    finally:
        await lk.aclose()
