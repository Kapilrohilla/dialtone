"""Response gap: how long the caller waits between finishing a sentence and hearing the agent reply.

Two numbers per reply, both measured from the moment the caller stopped speaking (a local VAD on the caller's
audio, so it works whatever the pipeline does its own turn detection with):

- system: until the agent's audio starts playing out. What the stack (turn detection, model, TTS, network to
  the room) costs.
- perceived: until the first audible sample of that reply. Adds any silence at the start of the agent's audio,
  such as a pause cue at the start of a line. This is what the caller hears.

Replies the caller didn't wait for are left out: the opening line (nothing to reply to), turns where the caller
was still talking when the agent started (the agent cut in), and gaps so long they are not a reply (a dead-air
nudge, for instance).
"""

from __future__ import annotations

import array
import math
from dataclasses import dataclass, field

# A gap at or above this is not a reply to the caller's last words (a dead-air check-in, a stalled call).
MAX_REPLY_GAP_S = 15.0
SLOW_GAP_S = 2.0
# Agent audio quieter than this (int16 RMS) counts as silence when finding the first audible sample.
SILENCE_RMS = 300
MAX_TURNS_KEPT = 200


def frame_rms(data: bytes | memoryview) -> float:
    """RMS of 16-bit PCM samples (any channel layout)."""
    samples = array.array("h")
    samples.frombytes(bytes(data))
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


@dataclass
class _Reply:
    at_s: float
    system_s: float
    perceived_s: float | None = None


@dataclass
class _Playout:
    start: float
    leading_s: float | None = None
    reply: _Reply | None = None
    settled: bool = False


@dataclass
class ResponseGapTracker:
    """Fed wall-clock times (time.time()) by the call; summary() goes into the call report.

    The VAD reports the end of the caller's speech only after a short silence, with how long that silence
    already was, so the true end time can arrive after the agent's reply started. A reply that starts while the
    caller still counts as speaking is therefore settled when the end arrives: before the reply started, it was
    a normal reply; after, the agent cut in."""

    call_start: float
    caller_speaking: bool = False
    last_caller_end: float | None = None
    # The caller's last end of speech already answered by a reply (never measured twice).
    answered_end: float | None = None
    agent_cut_ins: int = 0
    replies: list[_Reply] = field(default_factory=list)
    _playout: _Playout | None = None

    def caller_started(self, at: float) -> None:
        self.caller_speaking = True

    def caller_ended(self, at: float) -> None:
        self.caller_speaking = False
        self.last_caller_end = at
        p = self._playout
        if p is not None and not p.settled:
            if at <= p.start:
                self._settle(p)
            else:
                p.settled = True
                self.agent_cut_ins += 1

    def agent_playout_started(self, at: float) -> None:
        """The agent's audio for a new reply started playing out to the room."""
        self._playout = _Playout(start=at)
        if not self.caller_speaking:
            self._settle(self._playout)

    def agent_audible_after(self, leading_silence_s: float) -> None:
        """The current reply's first audible sample came this long after its playout started."""
        p = self._playout
        if p is None or p.leading_s is not None:
            return
        p.leading_s = max(0.0, leading_silence_s)
        if p.reply is not None:
            p.reply.perceived_s = p.reply.system_s + p.leading_s

    def _settle(self, p: _Playout) -> None:
        p.settled = True
        end = self.last_caller_end
        if end is None or end == self.answered_end:
            return  # the opening line, or another segment of the same reply
        self.answered_end = end
        gap = p.start - end
        if gap >= MAX_REPLY_GAP_S:
            return
        p.reply = _Reply(at_s=round(end - self.call_start, 2), system_s=gap)
        if p.leading_s is not None:
            p.reply.perceived_s = gap + p.leading_s
        self.replies.append(p.reply)

    def summary(self) -> dict:
        system = [r.system_s for r in self.replies]
        perceived = [r.perceived_s if r.perceived_s is not None else r.system_s for r in self.replies]
        return {
            "n": len(self.replies),
            "system": _stats(system),
            "perceived": _stats(perceived),
            "slow_replies": sum(1 for p in perceived if p > SLOW_GAP_S),
            "slow_threshold_ms": round(SLOW_GAP_S * 1000),
            "agent_cut_ins": self.agent_cut_ins,
            "replies": [
                {"at_s": r.at_s, "system_ms": round(r.system_s * 1000), "perceived_ms": round(p * 1000)}
                for r, p in zip(self.replies[:MAX_TURNS_KEPT], perceived[:MAX_TURNS_KEPT])
            ],
        }


def _stats(values: list[float]) -> dict:
    if not values:
        return {}
    ordered = sorted(values)

    def pct(p: int) -> int:
        return round(ordered[max(1, math.ceil(p / 100 * len(ordered))) - 1] * 1000)

    return {
        "avg_ms": round(sum(ordered) / len(ordered) * 1000),
        "p50_ms": pct(50),
        "p95_ms": pct(95),
        "max_ms": round(ordered[-1] * 1000),
    }


class LeadingSilence:
    """Counts the silent audio at the start of each agent reply segment, frame by frame."""

    def __init__(self, threshold: float = SILENCE_RMS) -> None:
        self.threshold = threshold
        self._silent_s = 0.0
        self._found = True  # no segment open

    def new_segment(self) -> None:
        self._silent_s = 0.0
        self._found = False

    def frame(self, data: bytes | memoryview, duration_s: float) -> float | None:
        """Feed one frame; returns the leading silence (seconds) at the first audible frame, else None."""
        if self._found:
            return None
        if frame_rms(data) < self.threshold:
            self._silent_s += duration_s
            return None
        self._found = True
        return self._silent_s


# --- LiveKit wiring ------------------------------------------------------------------------------------------

import asyncio  # noqa: E402
import logging  # noqa: E402
import time  # noqa: E402

from livekit import rtc  # noqa: E402
from livekit.agents import vad as agents_vad  # noqa: E402
from livekit.agents.voice.io import AudioOutput, AudioOutputCapabilities  # noqa: E402

logger = logging.getLogger("phone-agent")


class GapAudioTap(AudioOutput):
    """A pass-through in the session's audio output chain: reports when each reply starts playing out and how
    much silence it starts with. Audio goes on to the room unchanged."""

    def __init__(self, gaps: ResponseGapTracker, next_in_chain: AudioOutput) -> None:
        super().__init__(
            label="response-gap",
            capabilities=AudioOutputCapabilities(pause=True),
            next_in_chain=next_in_chain,
            sample_rate=next_in_chain.sample_rate,
        )
        self._gaps = gaps
        self._silence = LeadingSilence()
        self._capturing = False
        # Frames arrive faster than real time, so the first audible frame is usually found before the room
        # starts playing the segment: keep it until then.
        self._lead: float | None = None
        self._started = False

    def on_playback_started(self, *, created_at: float) -> None:
        # created_at is time.time() when the room output started playing this segment.
        self._started = True
        self._gaps.agent_playout_started(created_at)
        if self._lead is not None:
            self._gaps.agent_audible_after(self._lead)
        super().on_playback_started(created_at=created_at)

    async def capture_frame(self, frame: rtc.AudioFrame) -> None:
        if not self._capturing:
            self._capturing = True
            self._silence.new_segment()
            self._lead, self._started = None, False
        await super().capture_frame(frame)
        try:
            lead = self._silence.frame(frame.data, frame.samples_per_channel / frame.sample_rate)
            if lead is not None:
                self._lead = lead
                if self._started:
                    self._gaps.agent_audible_after(lead)
        except Exception:  # measuring must never break the call's audio
            logger.debug("response gap frame check failed", exc_info=True)
        await self.next_in_chain.capture_frame(frame)

    def flush(self) -> None:
        super().flush()
        self._capturing = False
        self.next_in_chain.flush()

    def clear_buffer(self) -> None:
        self.next_in_chain.clear_buffer()


async def watch_caller_speech(room: rtc.Room, identity: str, vad: agents_vad.VAD, gaps: ResponseGapTracker) -> None:
    """Run the VAD on the caller's microphone and feed start/end of speech into `gaps` until cancelled."""
    track = await _caller_audio_track(room, identity)
    stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1)
    vad_stream = vad.stream()

    async def push() -> None:
        async for ev in stream:
            vad_stream.push_frame(ev.frame)
        vad_stream.end_input()

    pusher = asyncio.create_task(push())
    try:
        async for ev in vad_stream:
            now = time.time()
            if ev.type == agents_vad.VADEventType.START_OF_SPEECH:
                gaps.caller_started(now - ev.speech_duration)
            elif ev.type == agents_vad.VADEventType.END_OF_SPEECH:
                gaps.caller_ended(now - ev.silence_duration)
    finally:
        pusher.cancel()
        await vad_stream.aclose()
        await stream.aclose()


async def _caller_audio_track(room: rtc.Room, identity: str) -> rtc.RemoteAudioTrack:
    found: asyncio.Future[rtc.RemoteAudioTrack] = asyncio.get_running_loop().create_future()

    def on_subscribed(track, _pub, participant) -> None:
        if participant.identity == identity and isinstance(track, rtc.RemoteAudioTrack) and not found.done():
            found.set_result(track)

    room.on("track_subscribed", on_subscribed)
    try:
        participant = room.remote_participants.get(identity)
        for pub in (participant.track_publications.values() if participant else []):
            if isinstance(pub.track, rtc.RemoteAudioTrack):
                return pub.track
        return await found
    finally:
        room.off("track_subscribed", on_subscribed)
