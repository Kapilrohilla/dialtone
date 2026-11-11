"""Load the published agent config from the Dialtone console, with disk cache and built-in fallback."""

import asyncio
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

import aiohttp
from livekit import api

logger = logging.getLogger("phone-agent")

RUNTIME_IDENTITY = "agent-runtime"
# A publish reaches new calls within this delay: successful console responses are memoised per number.
MEMO_TTL_S = 15.0

# The console's 404 detail when no agent is published for the number (dashboard runtime API).
NO_AGENT_DETAIL = "No published agent for this number."

_memo: dict[str, tuple[float, "Config"]] = {}
_warned_unwritable = False


@dataclass(frozen=True)
class Config:
    # "draft": a console voice test (browser call), never cached.
    source: Literal["console", "cache", "builtin", "draft"]
    snapshot: dict | None
    version_id: int | None


_BUILTIN = Config("builtin", None, None)


def dashboard_url() -> str:
    """DASHBOARD_URL, else DASHBOARD_REPORT_URL minus its /api/report suffix. Empty means console off."""
    if "DASHBOARD_URL" in os.environ:
        return os.environ["DASHBOARD_URL"].rstrip("/")
    report = os.environ.get("DASHBOARD_REPORT_URL", "")
    return report.removesuffix("/api/report").rstrip("/")


def cache_dir() -> str:
    return os.environ.get("CONFIG_CACHE_DIR", "/cache")


def runtime_token(api_key: str, api_secret: str, identity: str = RUNTIME_IDENTITY, ttl_s: int = 60) -> str:
    return (
        api.AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_ttl(timedelta(seconds=ttl_s))
        .to_jwt()
    )


def _cache_path(number: str) -> str:
    digits = "".join(c for c in number if c in "0123456789")
    return os.path.join(cache_dir(), (digits or "_default") + ".json")


def _write_cache(number: str, version_id: int, snapshot: dict) -> None:
    global _warned_unwritable
    path = _cache_path(number)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"version_id": version_id, "snapshot": snapshot}, f)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as e:
        if not _warned_unwritable:
            _warned_unwritable = True
            logger.warning("config cache dir not writable, using memory only", extra={"error": str(e)})


def _read_cache(number: str) -> Config | None:
    try:
        with open(_cache_path(number)) as f:
            data = json.load(f)
        snapshot = data["snapshot"]
        if not isinstance(snapshot, dict):
            return None
        return Config("cache", snapshot, data.get("version_id"))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _delete_cache(number: str) -> None:
    try:
        os.unlink(_cache_path(number))
    except OSError:
        pass


async def _fetch(number: str, room: str, base_url: str, api_key: str, api_secret: str, timeout_s: float) -> Config | None:
    """Config from the console, _BUILTIN when it has no published agent for the number, None when
    unavailable (caller falls back to cache)."""
    token = runtime_token(api_key, api_secret)
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        async with http.get(
            f"{base_url}/api/runtime/config",
            params={"number": number, "room": room},
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            if resp.status == 404:
                # Only the console's own answer means "no agent": any other 404 (a proxy, a wrong
                # DASHBOARD_URL) must not clear the cache.
                try:
                    detail = (await resp.json(content_type=None)).get("detail")
                except Exception:
                    detail = None
                if detail == NO_AGENT_DETAIL:
                    return _BUILTIN
                logger.warning("console config unavailable", extra={"status": resp.status})
                return None
            if resp.status == 401:
                logger.warning("console rejected the runtime token; check LIVEKIT_API_KEY/SECRET")
                return None
            if resp.status != 200:
                logger.warning("console config unavailable", extra={"status": resp.status})
                return None
            body = await resp.json(content_type=None)
    snapshot = body["snapshot"]
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot is not an object")
    return Config("console", snapshot, int(body["version_id"]))


async def load_config(
    number: str,
    room: str,
    *,
    base_url: str,
    api_key: str,
    api_secret: str,
    timeout_s: float = 1.5,
    now: Callable[[], float] = time.monotonic,
) -> Config:
    """Never raises. Fresh console config, else last good cached config, else built-in."""
    start = time.monotonic()
    cfg: Config | None = None
    try:
        if not base_url:
            cfg = _BUILTIN
        else:
            hit = _memo.get(number)
            if hit and now() - hit[0] < MEMO_TTL_S:
                return hit[1]
            try:
                cfg = await _fetch(number, room, base_url, api_key, api_secret, timeout_s)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError) as e:
                logger.warning("console config fetch failed", extra={"error": repr(e)})
                cfg = None
            if cfg is None:
                cfg = _read_cache(number) or _BUILTIN
            elif cfg.source == "console":
                _memo[number] = (now(), cfg)
                _write_cache(number, cfg.version_id, cfg.snapshot)
            else:
                _memo.pop(number, None)
                _delete_cache(number)
    except Exception as e:  # never fail a call over config
        logger.warning("config load failed", extra={"error": repr(e)})
        cfg = _BUILTIN
    logger.info(
        "config loaded",
        extra={"source": cfg.source, "version_id": cfg.version_id, "elapsed_ms": round((time.monotonic() - start) * 1000)},
    )
    return cfg


def web_test_agent_id(metadata: dict) -> int | None:
    """The console agent a voice test (browser call, dispatched by the dashboard) runs, else None."""
    web_test = metadata.get("web_test") if isinstance(metadata, dict) else None
    agent_id = web_test.get("agent_id") if isinstance(web_test, dict) else None
    if isinstance(agent_id, bool) or not isinstance(agent_id, int) or agent_id <= 0:
        return None
    return agent_id


async def load_draft_config(
    agent_id: int,
    room: str,
    *,
    base_url: str,
    api_key: str,
    api_secret: str,
    timeout_s: float = 3.0,
) -> Config:
    """Never raises. The agent's current draft for a voice test, else built-in. Never memoised or cached:
    each test call hears the latest edits, and a draft must never serve a phone call."""
    start = time.monotonic()
    cfg = _BUILTIN
    try:
        if base_url:
            token = runtime_token(api_key, api_secret)
            timeout = aiohttp.ClientTimeout(total=timeout_s)
            async with aiohttp.ClientSession(timeout=timeout) as http:
                async with http.get(
                    f"{base_url}/api/runtime/config",
                    params={"agent": str(agent_id), "room": room},
                    headers={"Authorization": f"Bearer {token}"},
                ) as resp:
                    if resp.status == 200:
                        snapshot = (await resp.json(content_type=None))["snapshot"]
                        if isinstance(snapshot, dict):
                            cfg = Config("draft", snapshot, None)
                        else:
                            logger.warning("draft config snapshot is not an object")
                    else:
                        logger.warning("draft config unavailable", extra={"status": resp.status})
    except Exception as e:  # never fail a call over config
        logger.warning("draft config load failed", extra={"error": repr(e)})
        cfg = _BUILTIN
    logger.info(
        "config loaded",
        extra={"source": cfg.source, "agent_id": agent_id, "elapsed_ms": round((time.monotonic() - start) * 1000)},
    )
    return cfg
