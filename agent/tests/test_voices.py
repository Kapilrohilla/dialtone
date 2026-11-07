import sys
import types

import agent
import voices


def test_resolve_known_voice():
    assert voices.resolve("gemini-live", "Puck", "Kore") == "Puck"


def test_resolve_unknown_falls_back(caplog):
    assert voices.resolve("gemini-live", "Sarah", "Kore") == "Kore" and "voice" in caplog.text


def test_resolve_empty_uses_default():
    assert voices.resolve("sarvam", "", "priya") == "priya"
    assert voices.resolve("sarvam", None, "priya") == "priya"


def _fake_plugin(monkeypatch, name, attr, made):
    class Fake:
        def __init__(self, **kw):
            made.update(kw)

    mod = types.ModuleType(f"livekit.plugins.{name}")
    setattr(mod, attr, Fake)
    if name == "google":
        mod.realtime = types.SimpleNamespace(RealtimeModel=Fake)
    monkeypatch.setitem(sys.modules, f"livekit.plugins.{name}", mod)
    monkeypatch.setattr(sys.modules["livekit.plugins"], name, mod, raising=False)


def test_gemini_session_uses_resolved_voice(monkeypatch):
    made = {}
    _fake_plugin(monkeypatch, "google", "x", made)
    monkeypatch.setattr(agent, "AgentSession", lambda llm: llm)
    agent.gemini_live_session({}, voice="Puck")
    assert made["voice"] == "Puck"


def test_gemini_session_default_voice(monkeypatch):
    made = {}
    _fake_plugin(monkeypatch, "google", "x", made)
    monkeypatch.setattr(agent, "AgentSession", lambda llm: llm)
    monkeypatch.setenv("GEMINI_VOICE", "Orus")
    agent.gemini_live_session({})
    assert made["voice"] == "Orus"


def test_gemini_session_pins_live_api_version(monkeypatch):
    # google-genai 3.x defaults to v1, where the Live websocket 404s and every call goes silent.
    made = {}
    _fake_plugin(monkeypatch, "google", "x", made)
    monkeypatch.setattr(agent, "AgentSession", lambda llm: llm)
    agent.gemini_live_session({})
    assert made["api_version"] == "v1beta"
    monkeypatch.setenv("GEMINI_AFFECTIVE_DIALOG", "true")
    agent.gemini_live_session({})
    assert made["api_version"] == "v1alpha"


def test_tts_builders_use_voice(monkeypatch):
    made = {}
    _fake_plugin(monkeypatch, "sarvam", "TTS", made)
    agent.sarvam_tts("priya")
    assert made["speaker"] == "priya"
    made.clear()
    _fake_plugin(monkeypatch, "elevenlabs", "TTS", made)
    agent.elevenlabs_tts("Xb7hH8MSUJpSbSDYk0k2")
    assert made["voice_id"] == "Xb7hH8MSUJpSbSDYk0k2"
