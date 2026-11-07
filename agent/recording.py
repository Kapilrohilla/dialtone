"""Call recording: an audio-only LiveKit Egress of the whole room, written to the media VM's dashboard volume.

The caller hears the consent line only when the egress actually started (start_recording returned a handle),
so a call is never recorded without the notice, and a recording failure never stops or delays the call by
more than START_TIMEOUT_S.
"""

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from livekit import api
from livekit.protocol.models import AudioCodec

logger = logging.getLogger("phone-agent")

# Inside the egress container: the dashboard-data volume (docker-compose.yml), served by the dashboard.
RECORDINGS_ROOT = "/data/recordings"
START_TIMEOUT_S = 1.0
# Opus at 32 kbps: about 240 KB a minute, plenty for phone audio.
AUDIO_BITRATE_KBPS = 32

# Egress starts that answered after the timeout; kept so they can be stopped (no consent was spoken).
_late: set[asyncio.Task] = set()


@dataclass(frozen=True)
class RecordingHandle:
    egress_id: str
    started_at: float  # epoch seconds
    filepath: str


def kill_switch_on() -> bool:
    """RECORDING_ENABLED is the worker-wide master switch: false means never record, whatever the console says."""
    return os.getenv("RECORDING_ENABLED", "false").lower() == "true"


def recording_wanted(source: str, snapshot: dict | None, is_phone_call: bool) -> tuple[bool, str]:
    """Whether to record this call, and why not. Only real phone calls running a fresh console config whose
    account switch is on: a cached or built-in config has no known setting, so it never records."""
    if not kill_switch_on():
        return False, "kill_switch"
    if not is_phone_call:
        return False, "not_phone_call"
    if source != "console":
        return False, "no_live_config"
    account = snapshot.get("account") if isinstance(snapshot, dict) else None
    setting = account.get("recording") if isinstance(account, dict) else None
    if not isinstance(setting, dict) or setting.get("enabled") is not True:
        reason = setting.get("reason") if isinstance(setting, dict) else None
        return False, reason if isinstance(reason, str) and reason else "off"
    return True, ""


def recording_path(room: str, now: float | None = None) -> str:
    """/data/recordings/YYYY/MM/<room>.ogg, the room name reduced to safe filename characters."""
    when = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", room).strip("._") or "call"
    return f"{RECORDINGS_ROOT}/{when:%Y}/{when:%m}/{name}.ogg"


def egress_request(room: str, filepath: str) -> api.RoomCompositeEgressRequest:
    return api.RoomCompositeEgressRequest(
        room_name=room,
        audio_only=True,
        file_outputs=[api.EncodedFileOutput(file_type=api.EncodedFileType.OGG, filepath=filepath, disable_manifest=True)],
        advanced=api.EncodingOptions(audio_codec=AudioCodec.OPUS, audio_bitrate=AUDIO_BITRATE_KBPS, audio_frequency=48000),
    )


async def _stop_when_started(lkapi, task: asyncio.Task, room: str) -> None:
    try:
        info = await task
        await lkapi.egress.stop_egress(api.StopEgressRequest(egress_id=info.egress_id))
        logger.warning("stopped a recording that started too late", extra={"room": room, "egress_id": info.egress_id})
    except Exception:
        pass  # the start failed after all: nothing to stop


async def start_recording(
    lkapi, room: str, timeout_s: float = START_TIMEOUT_S
) -> tuple[RecordingHandle | None, str | None]:
    """Start the room's recording. Never raises: (handle, None) when it started, else (None, error).
    A start slower than timeout_s counts as failed; if it does start later, it is stopped straight away."""
    filepath = recording_path(room)
    started = time.monotonic()
    task = asyncio.ensure_future(lkapi.egress.start_room_composite_egress(egress_request(room, filepath)))
    try:
        info = await asyncio.wait_for(asyncio.shield(task), timeout_s)
    except asyncio.TimeoutError:
        late = asyncio.create_task(_stop_when_started(lkapi, task, room))
        _late.add(late)
        late.add_done_callback(_late.discard)
        logger.warning("recording start timed out; the call goes on unrecorded", extra={"room": room})
        return None, f"egress start took over {timeout_s:g} s"
    except Exception as e:
        logger.warning("recording failed to start; the call goes on unrecorded", extra={"room": room, "error": repr(e)})
        return None, f"egress start failed: {e!r}"[:500]
    logger.info(
        "recording started",
        extra={"room": room, "egress_id": info.egress_id, "elapsed_ms": round((time.monotonic() - started) * 1000)},
    )
    return RecordingHandle(info.egress_id, time.time(), filepath), None


def report_field(handle: RecordingHandle | None, error: str | None) -> dict | None:
    """The call report's "recording": None when recording wasn't attempted."""
    if handle is not None:
        return {"egress_id": handle.egress_id, "started_at": handle.started_at, "filepath": handle.filepath, "error": None}
    if error:
        return {"egress_id": None, "started_at": None, "filepath": None, "error": error}
    return None
