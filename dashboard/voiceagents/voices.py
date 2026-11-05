"""Voices each agent pipeline can speak. The catalog is voices.json; agent/voices.json is a copy."""

import json
from pathlib import Path

CATALOG: dict[str, list[dict]] = json.loads((Path(__file__).parent / "voices.json").read_text())


def for_pipeline(pipeline: str) -> list[dict]:
    return CATALOG.get(pipeline, [])
