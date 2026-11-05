"""Voices each pipeline can speak (voices.json is a copy of the dashboard's catalog)."""

import json
import logging
from pathlib import Path

logger = logging.getLogger("phone-agent")

CATALOG: dict[str, list[dict]] = json.loads((Path(__file__).parent / "voices.json").read_text())


def resolve(pipeline: str, voice_id: str | None, default: str) -> str:
    """`voice_id` when this pipeline can speak it, else `default`."""
    if not voice_id:
        return default
    if any(v["id"] == voice_id for v in CATALOG.get(pipeline, [])):
        return voice_id
    logger.warning("voice not available on this pipeline, using the default",
                   extra={"voice": voice_id, "pipeline": pipeline})
    return default
