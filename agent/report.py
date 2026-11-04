"""Per-call report sent to the dashboard: outcome, caller mood, dead air, latency and behaviour."""

import logging
from datetime import timedelta

import aiohttp
from livekit import api

logger = logging.getLogger("phone-agent")

REPORT_IDENTITY = "agent-report"


def build_report(
    room: str,
    outcome: dict,
    mood: dict | None,
    timeline: list[dict],
    dead_air: list[dict],
    latency: dict,
    behavior: dict | None,
    turns: list[dict] | None,
) -> dict:
    """turns, when given, are {"role", "text", "at_s"}; at_s and timeline times are seconds since the call started."""
    report = {
        "room": room,
        "disposition": outcome.get("disposition"),
        "outcome": outcome,
        "mood": mood,
        "timeline": timeline,
        "dead_air": dead_air,
        "latency": latency,
        "behavior": behavior,
    }
    if turns is not None:
        report["turns"] = turns
    return report


async def send_report(url: str, report: dict, api_key: str, api_secret: str) -> bool:
    """POST the report, signed with a short-lived LiveKit token. Never raises; False on any failure."""
    try:
        token = (
            api.AccessToken(api_key, api_secret)
            .with_identity(REPORT_IDENTITY)
            .with_ttl(timedelta(seconds=60))
            .to_jwt()
        )
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as http:
            async with http.post(url, json=report, headers={"Authorization": f"Bearer {token}"}) as resp:
                if resp.status != 200:
                    logger.warning("dashboard rejected call report", extra={"status": resp.status})
                    return False
        return True
    except Exception as e:
        logger.warning("could not send call report", extra={"error": str(e)})
        return False
