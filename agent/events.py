"""Streams call events (turns, steps, moods, captured fields) to the console. Never blocks or fails the call."""

import asyncio
import logging
import time

import aiohttp

import console_config

logger = logging.getLogger("phone-agent")

REQUEST_TIMEOUT_S = 3
MAX_BUFFER = 5000


def _retryable(status: int) -> bool:
    return status == 429 or status >= 500


class EventSink:
    """Buffers events and posts them in batches from a background task.

    add() is synchronous, never awaits, never raises. The background flush task starts lazily on the
    first add() made while an asyncio loop is running (no explicit start() needed); add() with no
    running loop just buffers, and close() will flush it. An empty url disables the sink entirely.
    """

    def __init__(
        self,
        url: str,
        room: str,
        api_key: str,
        api_secret: str,
        flush_every_s: float = 1.0,
        max_batch: int = 50,
        retry_delays: tuple[float, ...] = (0.5, 1.0, 2.0),
        max_buffer: int = MAX_BUFFER,
    ):
        self.url = url
        self.room = room
        self._key = api_key
        self._secret = api_secret
        self._flush_every_s = flush_every_s
        self._max_batch = max(1, min(max_batch, 200))
        self._retry_delays = retry_delays
        self._max_buffer = max_buffer
        self._buffer: list[dict] = []
        self._seq = 0
        self._closing = False
        self._task: asyncio.Task | None = None
        self._wakeup = asyncio.Event()
        self._http: aiohttp.ClientSession | None = None
        self.dropped = 0

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def add(self, type: str, payload: dict) -> None:
        if not self.enabled or self._closing:
            return
        try:
            if len(self._buffer) >= self._max_buffer:
                del self._buffer[0]
                self.dropped += 1
            self._buffer.append({"seq": self._seq, "type": type, "at": time.time(), "payload": payload})
            self._seq += 1
            if self._task is None or self._task.done():
                try:
                    self._task = asyncio.get_running_loop().create_task(self._run())
                except RuntimeError:
                    pass  # no loop yet; close() flushes
            if len(self._buffer) >= self._max_batch:
                self._wakeup.set()
        except Exception as e:  # never break a live call
            logger.warning("event add failed", extra={"error": str(e)})

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wakeup.wait(), self._flush_every_s)
            except asyncio.TimeoutError:
                pass
            self._wakeup.clear()
            try:
                await self._drain()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("event flush loop error", extra={"error": str(e)})
            if self._closing and not self._buffer:
                return

    async def _drain(self) -> None:
        while self._buffer:
            batch = self._buffer[: self._max_batch]
            del self._buffer[: len(batch)]
            await self._send(batch)
            if not self._closing and len(self._buffer) < self._max_batch:
                return

    async def _send(self, batch: list[dict]) -> None:
        attempts = len(self._retry_delays) + 1
        for attempt in range(attempts):
            try:
                if self._http is None:
                    self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S))
                token = console_config.runtime_token(self._key, self._secret)
                async with self._http.post(
                    self.url,
                    json={"room": self.room, "events": batch},
                    headers={"Authorization": f"Bearer {token}"},
                ) as resp:
                    status = resp.status
                if 200 <= status < 300:
                    return
                if not _retryable(status):
                    logger.warning("console rejected event batch", extra={"status": status})
                    break
                logger.warning("event batch failed", extra={"status": status, "attempt": attempt + 1})
            except asyncio.CancelledError:
                self.dropped += len(batch)
                raise
            except Exception as e:
                logger.warning("event batch error", extra={"error": str(e), "attempt": attempt + 1})
            if attempt < attempts - 1:
                try:
                    await asyncio.sleep(self._retry_delays[attempt])
                except asyncio.CancelledError:
                    self.dropped += len(batch)
                    raise
        self.dropped += len(batch)
        logger.warning("dropped event batch", extra={"events": len(batch), "total_dropped": self.dropped})

    async def close(self, timeout_s: float = 3.0) -> None:
        """Flush what is left within timeout_s, stop the background task, close the HTTP session. Never raises."""
        if not self.enabled:
            return
        try:
            self._closing = True
            task = self._task if self._task and not self._task.done() else asyncio.get_running_loop().create_task(self._run())
            self._task = task
            self._wakeup.set()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout_s)
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass
                self.dropped += len(self._buffer)
                self._buffer.clear()
                logger.warning("event flush timed out on close")
        except Exception as e:
            logger.warning("event sink close failed", extra={"error": str(e)})
        finally:
            if self._http is not None:
                try:
                    await self._http.close()
                except Exception:
                    pass
                self._http = None
