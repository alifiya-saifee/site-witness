import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sitewitness import replies, server, voice

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "helper"))
from diwan_helper import Helper  # noqa: E402


# ---- what the agent says ----

def test_every_outcome_has_english_and_arabic():
    for outcome, (en, ar) in replies.TEXT.items():
        assert en and ar and replies.ARABIC.search(ar), outcome
        for lang in ("en", "ar"):
            assert "{" not in replies.reply(outcome, lang, file="alnoor-slides", person="Visitor", to="Karim")


def test_reply_language_follows_the_command():
    assert replies.lang_of("open the Al Noor slides") == "en"
    assert replies.lang_of("افتح عرض النور") == "ar"
    assert replies.lang_of("open the slides", heard_lang="ar") == "ar"
    assert replies.reply("confirmed", "en", file="alnoor-slides") == "Done. I've opened the Al Noor slides on your Mac."
    assert "النور" in replies.reply("sent", "ar", file="alnoor-slides")


# ---- the voice engine ----

@pytest.fixture
def fake_mac(monkeypatch):
    calls = []

    def run(cmd):
        calls.append(cmd)
        if cmd[0] == "say":
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"aiff")
        if cmd[0] == "afconvert":
            Path(cmd[-1]).write_bytes(b"m4a-audio")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")
    monkeypatch.setattr(voice, "run", run)
    monkeypatch.setattr(voice, "_cache", {})
    for k in ("SW_TTS", "NVIDIA_API_KEY", "SW_MAGPIE_FUNCTION_ID"):
        monkeypatch.delenv(k, raising=False)
    return calls


def test_mac_voice_per_language_and_cache(fake_mac):
    audio, engine, note = voice.speak("Done.", "en")
    assert audio == b"m4a-audio" and engine == "mac" and note == "Mac voice"
    voice.speak("Done.", "en")  # cached: no second call
    voice.speak("تم.", "ar")
    says = [c for c in fake_mac if c[0] == "say"]
    assert [c[2] for c in says] == ["Samantha", "Majed"]


def test_magpie_only_when_everything_is_in_place(fake_mac, monkeypatch, tmp_path):
    monkeypatch.setattr(voice, "SAMPLE", tmp_path / "voice-sample.wav")
    assert voice.magpie_ready("en") == "off"
    monkeypatch.setenv("SW_TTS", "magpie")
    assert "key" in voice.magpie_ready("en")
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    monkeypatch.setenv("SW_MAGPIE_FUNCTION_ID", "fid")
    assert "sample" in voice.magpie_ready("en")
    voice.SAMPLE.write_bytes(b"RIFF")
    assert voice.magpie_ready("en") is None
    assert "English only" in voice.magpie_ready("ar")


def test_magpie_trouble_falls_back_to_the_mac_voice_and_says_so(fake_mac, monkeypatch, tmp_path):
    monkeypatch.setattr(voice, "SAMPLE", tmp_path / "voice-sample.wav")
    voice.SAMPLE.write_bytes(b"RIFF")
    monkeypatch.setenv("SW_TTS", "magpie"); monkeypatch.setenv("NVIDIA_API_KEY", "k"); monkeypatch.setenv("SW_MAGPIE_FUNCTION_ID", "f")

    def boom(text):
        raise PermissionError("access not approved")
    monkeypatch.setattr(voice, "magpie_call", boom)
    audio, engine, note = voice.speak("Done.", "en")
    assert engine == "mac" and "magpie failed" in note and "PermissionError" in note
    assert voice._cache == {}  # a one-off failure isn't cached

    monkeypatch.setattr(voice, "magpie_call", lambda text: b"\x00\x01" * 2205)
    audio, engine, note = voice.speak("Done.", "en")
    assert engine == "magpie" and "your voice" in note


# ---- the hub ----

@pytest.fixture
def client(monkeypatch, fake_mac):
    monkeypatch.setattr(server, "hub", server.Hub())
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})
    return TestClient(server.app)


def test_answers_carry_a_spoken_reply_in_the_right_language(client):
    r = client.post("/api/command", json={"text": "افتح عرض النور", "person": "visitor"}).json()
    assert r["status"] == "refused" and r["reply"]["lang"] == "ar" and "الزائر" in r["reply"]["text"] and "صلاحية" in r["reply"]["text"]
    audio = client.get(f"/api/reply/{r['reply']['id']}.m4a")
    assert audio.status_code == 200 and audio.content == b"m4a-audio" and audio.headers["x-voice"] == "Mac voice"
    assert any(e["type"] == "reply.spoken" for e in server.hub.log.list())


def test_reply_audio_needs_pairing(monkeypatch, fake_mac):
    monkeypatch.setattr(server, "hub", server.Hub())
    c = TestClient(server.app)
    rid = "abcdef0123"
    server.hub.replies[rid] = {"text": "x", "lang": "en", "audio": None, "engine": None, "note": None}
    assert c.get(f"/api/reply/{rid}.m4a").status_code == 401


def test_open_then_reply_spoken_on_the_mac_too(client):
    with client.websocket_connect(f"/helper/ws?token={server.hub.helper_token}") as ws:
        r = client.post("/api/command", json={"text": "open the Al Noor slides", "person": "layla",
                                              "also_mac": True}).json()
        assert r["status"] == "sent" and "reply" not in r  # the reply comes with the final result
        ws.receive_json()  # open_file
        ws.send_json({"type": "result", "command_id": r["command"], "ok": True, "confirmed": True, "detail": "ok"})
        speak = ws.receive_json()
        assert speak["type"] == "speak"
        got = client.get(f"/helper/reply/{speak['reply_id']}?t={speak['token']}")
        assert got.content == b"m4a-audio"
        assert client.get(f"/helper/reply/{speak['reply_id']}?t={speak['token']}").status_code == 403  # once only
        ws.send_json({"type": "spoken", "reply_id": speak["reply_id"], "ok": True})
        client.get("/api/events")
    st = client.get(f"/api/status/{r['command']}").json()
    assert st["reply"]["text"] == "Done. I've opened the Al Noor slides on your Mac."
    assert any(e["type"] == "reply.spoken" and e["content"]["where"] == "Mac speakers" for e in server.hub.log.list())


def test_voice_sample_needs_the_mac_and_consent(client, monkeypatch, tmp_path):
    monkeypatch.setattr(server.voice, "SAMPLE", tmp_path / "voice-sample.wav")
    h = {"Content-Type": "audio/webm"}
    assert client.post("/api/voice-sample", content=b"x" * 5000, headers=h).status_code == 400  # no consent
    monkeypatch.setattr(server, "LOCAL_HOSTS", {"127.0.0.1"})
    assert client.post("/api/voice-sample?consent=my-own-voice", content=b"x" * 5000, headers=h).status_code == 403
    assert client.delete("/api/voice-sample").status_code == 403


# ---- the helper plays replies, nothing else ----

def test_helper_speaks_only_hub_replies(tmp_path):
    calls = []

    def runner(cmd, timeout=10):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    h = Helper(runner=runner, opened_dir=tmp_path / "opened", fetch_reply=lambda rid, tok: b"m4a")
    assert "Refused" in h.speak({"type": "speak", "reply_id": "../../etc", "token": "t"})["detail"]
    assert h.speak({"type": "speak", "reply_id": "abcdef0123", "token": "t"})["ok"]
    assert "already used" in h.speak({"type": "speak", "reply_id": "abcdef0123", "token": "t"})["detail"]
    assert calls == [["afplay", str(tmp_path / "replies" / "abcdef0123.m4a")]]
