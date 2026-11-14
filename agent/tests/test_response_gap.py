import array

import pytest

from response_gap import LeadingSilence, ResponseGapTracker, frame_rms

T0 = 1000.0


def tracker():
    return ResponseGapTracker(call_start=T0)


def test_opening_line_is_not_a_reply():
    t = tracker()
    t.agent_playout_started(T0 + 1)
    assert t.summary()["n"] == 0
    assert t.summary()["system"] == {}


def test_reply_gap_system_and_perceived():
    t = tracker()
    t.caller_started(T0 + 5)
    t.caller_ended(T0 + 7)
    t.agent_playout_started(T0 + 8.2)
    t.agent_audible_after(0.3)  # a pause cue at the start of the line
    s = t.summary()
    assert s["n"] == 1
    assert s["replies"] == [{"at_s": 7.0, "system_ms": 1200, "perceived_ms": 1500}]
    assert s["system"]["p50_ms"] == 1200 and s["perceived"]["avg_ms"] == 1500
    assert s["slow_replies"] == 0


def test_vad_end_arriving_after_playout_still_counts_as_reply():
    # The VAD says "ended 0.55 s ago" only after the silence; the model may already be replying.
    t = tracker()
    t.caller_started(T0 + 5)
    t.agent_playout_started(T0 + 7.4)
    t.agent_audible_after(0.0)
    t.caller_ended(T0 + 7.0)  # the true end, reported late
    s = t.summary()
    assert s["n"] == 1 and s["replies"][0]["system_ms"] == 400 and s["agent_cut_ins"] == 0


def test_agent_cut_in_is_counted_not_measured():
    # Mobile number in chunks: the agent starts while the caller is still giving digits.
    t = tracker()
    t.caller_started(T0 + 5)
    t.agent_playout_started(T0 + 6)
    t.caller_ended(T0 + 8)
    assert t.summary()["agent_cut_ins"] == 1
    assert t.summary()["n"] == 0


def test_second_segment_of_same_reply_not_measured_twice():
    t = tracker()
    t.caller_started(T0 + 1)
    t.caller_ended(T0 + 2)
    t.agent_playout_started(T0 + 3)
    t.agent_playout_started(T0 + 6)
    assert t.summary()["n"] == 1


def test_long_gap_is_not_a_reply():
    t = tracker()
    t.caller_started(T0 + 1)
    t.caller_ended(T0 + 2)
    t.agent_playout_started(T0 + 20)  # a dead-air check-in
    assert t.summary()["n"] == 0


def test_slow_replies_and_percentiles():
    t = tracker()
    for i, gap in enumerate([0.8, 1.0, 2.5, 3.0]):
        base = T0 + i * 20
        t.caller_started(base)
        t.caller_ended(base + 1)
        t.agent_playout_started(base + 1 + gap)
    s = t.summary()
    assert s["n"] == 4 and s["slow_replies"] == 2
    assert s["system"] == {"avg_ms": 1825, "p50_ms": 1000, "p95_ms": 3000, "max_ms": 3000}
    # No audible info: perceived falls back to system.
    assert s["perceived"] == s["system"]


def pcm(value, n=160):
    return array.array("h", [value] * n).tobytes()


def test_frame_rms():
    assert frame_rms(pcm(0)) == 0
    assert frame_rms(pcm(1000)) == pytest.approx(1000)
    assert frame_rms(b"") == 0


def test_leading_silence():
    ls = LeadingSilence(threshold=300)
    assert ls.frame(pcm(5000), 0.01) is None  # no segment open
    ls.new_segment()
    assert ls.frame(pcm(10), 0.01) is None
    assert ls.frame(pcm(0), 0.01) is None
    assert ls.frame(pcm(4000), 0.01) == pytest.approx(0.02)
    assert ls.frame(pcm(0), 0.01) is None  # later silence doesn't count


class FakeSink:
    """Stands in for the room's audio output."""

    def __new__(cls):
        from livekit.agents.voice.io import AudioOutput, AudioOutputCapabilities

        class _Sink(AudioOutput):
            def __init__(self):
                super().__init__(label="fake", capabilities=AudioOutputCapabilities(pause=False), sample_rate=16000)
                self.frames, self.flushed, self.cleared = [], 0, 0

            async def capture_frame(self, frame):
                await super().capture_frame(frame)
                self.frames.append(frame)

            def flush(self):
                super().flush()
                self.flushed += 1

            def clear_buffer(self):
                self.cleared += 1

        return _Sink()


def frame(value, n=160, rate=16000):
    from livekit import rtc

    return rtc.AudioFrame(pcm(value, n), rate, 1, n)


async def test_gap_tap_passes_audio_through_and_reports():
    from response_gap import GapAudioTap

    sink = FakeSink()
    t = tracker()
    t.caller_started(T0 + 1)
    t.caller_ended(T0 + 2)
    tap = GapAudioTap(t, sink)
    for v in (0, 0, 0, 5000, 5000):  # 30 ms of silence, then speech
        await tap.capture_frame(frame(v))
    tap.flush()
    sink.on_playback_started(created_at=T0 + 3)  # the room starts playing the reply
    tap.clear_buffer()
    assert len(sink.frames) == 5 and sink.flushed == 1 and sink.cleared == 1
    reply = t.summary()["replies"][0]
    assert reply["system_ms"] == 1000 and reply["perceived_ms"] == 1030
