"""Voices each pipeline can speak (voices.json is a copy of the dashboard's catalog)."""

import json
import logging
import os
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


# The env var naming each pipeline's default voice, and the voice used when it is unset.
DEFAULT_VOICES = {
    "gemini-live": ("GEMINI_VOICE", "Kore"),
    "sarvam": ("TTS_SPEAKER", "priya"),
    "elevenlabs": ("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL"),
}


def default_voice(pipeline: str) -> str:
    env, fallback = DEFAULT_VOICES.get(pipeline, DEFAULT_VOICES["gemini-live"])
    return os.getenv(env, fallback)


def pipeline() -> str:
    return os.getenv("AGENT_PIPELINE", "gemini-live")


def gender(voice_id: str | None, pipeline_name: str | None = None) -> str | None:
    """"female" or "male" for the voice a call on `pipeline_name` (the env's by default) speaks with when
    `voice_id` is chosen: the chosen voice if the pipeline has it, else the pipeline's default voice. None when
    the catalog doesn't say (e.g. an env voice that isn't in the catalog)."""
    name = pipeline_name or pipeline()
    catalog = CATALOG.get(name, [])
    spoken = voice_id if voice_id and any(v["id"] == voice_id for v in catalog) else default_voice(name)
    for v in catalog:
        if v["id"] == spoken and v.get("gender") in ("female", "male"):
            return v["gender"]
    return None
