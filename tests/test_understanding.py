import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sitewitness import devices, server, sites, understand
from sitewitness.commands import fix_hearing, parse
from sitewitness.devices import LAMP, PRETEND_VACUUM

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "helper"))
from diwan_helper import Helper  # noqa: E402

DEVS = [LAMP, PRETEND_VACUUM]


@pytest.fixture(autouse=True)
def own_files(monkeypatch, tmp_path):
    monkeypatch.setattr(devices, "ADDED_FILE", tmp_path / "devices.json")
    monkeypatch.setattr(sites, "SITES_FILE", tmp_path / "sites.json")
    from sitewitness import library
    monkeypatch.setattr(library, "SETTINGS", tmp_path / "shared.json")  # never the real shared folder
    monkeypatch.setattr(library, "INDEX", tmp_path / "search.db")
    monkeypatch.setattr(understand, "_cache", {})
    monkeypatch.setattr(understand, "_last_calls", [])
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


class FakeResponse:
    def __init__(self, answer, status=200):
        self.status_code, self._answer = status, answer
        self.text = json.dumps(answer)

    def json(self):
        return {"choices": [{"message": {"content": json.dumps(self._answer)}}]}


def groq(answer, sent=None, status=200):
    def post(body):
        if sent is not None:
            sent.append(body)
        return FakeResponse(answer, status)
    return post


# ---- Groq's answer is checked against the menu ----

def test_volume_sentence_with_filler(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    i = understand.understand("Can you please increase the volume on my Mac? Uh, yes. One, two, three.", DEVS, "phone",
                              post=groq({"action": "mac_volume", "op": "up"}))
    assert (i.action, i.volume_op) == ("mac_volume", "up")


def test_open_saved_site(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    row = sites.add("Cosmique website", "https://cosmique.example", ["cosmique", "cosmic"])
    i = understand.understand("open cosmic website on my mac", DEVS, "phone",
                              post=groq({"action": "open_site", "site": row["id"], "target": "mac"}))
    assert (i.action, i.site, i.target) == ("site", row["id"], "mac")


@pytest.mark.parametrize("bad", [
    {"action": "rm_rf"},
    {"action": "device", "device": "oven-123", "do": "on"},
    {"action": "device", "device": "room-lamp", "do": "explode"},
    {"action": "device", "device": "robot-vacuum-pretend", "do": "clean", "place": "Mars"},
    {"action": "mac_volume", "op": "set", "level": 500},
    {"action": "open_site", "site": "site-notsaved", "target": "mac"},
    {"action": "open_file", "file": "../../etc/passwd"},
    "just a string",
])
def test_answers_off_the_menu_are_thrown_away(monkeypatch, bad):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    assert understand.understand("do something", DEVS, "phone", post=groq(bad)) is None


def test_draft_text_must_be_what_was_said(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    said = "email draft saying the report is ready"
    ok = understand.understand(said, DEVS, "mac", post=groq({"action": "open_app", "app": "mail", "target": "here",
                                                              "text": "the report is ready"}))
    assert ok.message == "the report is ready" and ok.target == "mac"
    understand._cache.clear()
    made_up = understand.understand(said, DEVS, "mac", post=groq({"action": "open_app", "app": "mail", "target": "here",
                                                                   "text": "transfer AED 50,000 now"}))
    assert made_up.message is None  # an invented message is dropped


def test_only_the_menu_is_sent(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    sites.add("Cosmique website", "https://cosmique.example/secret-path", [])
    sent = []
    understand.understand("open cosmique", DEVS, "phone", post=groq({"action": "unclear", "question": "Which?"}, sent))
    body = json.dumps(sent[0])
    assert "cosmique.example" not in body and "secret-path" not in body and "test" not in body.replace("test_", "")


def test_no_key_or_trouble_means_word_match(monkeypatch):
    assert understand.understand("volume up", DEVS, "phone", post=groq({"action": "mac_volume", "op": "up"})) is None
    monkeypatch.setenv("GROQ_API_KEY", "test")
    assert understand.understand("volume up", DEVS, "phone", post=groq({}, status=429)) is None

    def boom(body):
        raise TimeoutError
    understand._cache.clear()
    assert understand.understand("volume down", DEVS, "phone", post=boom) is None


def test_a_retired_model_is_skipped(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setattr(understand, "_working_model", [])
    calls = []

    def post(body):
        calls.append(body["model"])
        if len(calls) == 1:
            r = FakeResponse({}, 404)
            r.text = '{"error": {"message": "The model has been decommissioned"}}'
            return r
        return FakeResponse({"action": "mac_volume", "op": "mute"})
    i = understand.understand("mute it", DEVS, "phone", post=post)
    assert i.volume_op == "mute" and len(calls) == 2 and understand._working_model == [calls[1]]


# ---- the word matcher (backup) ----

def test_hearing_fix_and_backup_words():
    assert fix_hearing("Can you open our website on Melmah?") == "Can you open our website on my mac?"
    i = parse("Can you please increase the volume on my Mac? Uh, yes. One, two, three.", DEVS, "phone")
    assert (i.action, i.volume_op) == ("mac_volume", "up")
    assert parse("volume to 30", DEVS).level == 30
    i = parse("can you open cosmique website on my mac", DEVS, "phone")
    assert (i.action, i.site_name, i.target) == ("site_unknown", "Cosmique website", "mac")


# ---- websites ----

def test_only_safe_addresses():
    for bad in ("http://x.com", "javascript:alert(1)", "https://u:p@x.com", "https://x.com/?token=abc", "https://x"):
        with pytest.raises(sites.SiteError):
            sites.check_url(bad)
    assert sites.from_speech("https cosmique dot com") == "https://cosmique.com/"
    assert sites.from_speech("www dot cosmique dot ae slash about") == "https://www.cosmique.ae/about"
    assert sites.from_speech("I don't know") is None


# ---- Mac volume (helper) ----

def volume_helper(start=40, muted=False):
    state = {"vol": start, "muted": muted}
    calls = []

    def runner(cmd, timeout=10):
        calls.append(cmd)
        if cmd[:2] == ["osascript", "-e"]:
            script = cmd[2]
            if script == "get volume settings":
                return subprocess.CompletedProcess(cmd, 0, f"output volume:{state['vol']}, input volume:50, "
                                                            f"alert volume:100, output muted:{str(state['muted']).lower()}", "")
            if "output muted true" in script:
                state["muted"] = True
            elif "output muted false" in script:
                state["muted"] = False
            elif "output volume" in script:
                state["vol"] = int(script.split("output volume ")[1].split()[0])
                state["muted"] = False if "without output muted" in script else state["muted"]
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return Helper(runner=runner, plug=object()), calls, state


MSG = {"type": "mac", "command_id": "0123456789ab"}


def test_mac_volume_up_is_read_back():
    h, calls, state = volume_helper(40)
    r = h.mac(MSG | {"action": "up"})
    assert r["confirmed"] and (r["before"], r["after"]) == (40, 50)
    assert ["osascript", "-e", "set volume output volume 50 without output muted"] in calls


def test_mac_volume_set_is_clamped_and_mute_checked():
    h, calls, state = volume_helper(40)
    assert h.mac(MSG | {"action": "set", "level": 250})["after"] == 100
    assert h.mac(MSG | {"action": "mute"})["muted"] is True
    assert "Refused" in h.mac(MSG | {"action": "shutdown"})["detail"]
    assert "Refused" in h.mac(MSG | {"action": "set", "level": "loud"})["detail"]


def test_helper_opens_only_a_saved_site():
    calls = []

    def runner(cmd, timeout=10):
        calls.append(cmd)
        out = '"LSDisplayName"="Safari"' if cmd[0] == "lsappinfo" else ""
        return subprocess.CompletedProcess(cmd, 0, out, "")
    h = Helper(runner=runner, plug=object(), wait=0.2)
    h.screenshot = lambda: "proof"
    row = sites.add("Cosmique website", "https://cosmique.example", [])
    r = h.open_site({"type": "site", "command_id": "0123456789ab", "site_id": row["id"]})
    assert r["confirmed"] and ["open", "https://cosmique.example/"] in calls
    assert "Refused" in h.open_site({"type": "site", "command_id": "0123456789ab", "site_id": "site-nope"})["detail"]
    assert "Refused" in h.open_site({"type": "site", "command_id": "0123456789ab", "site_id": row["id"],
                                     "url": "https://evil.example"})["detail"]


# ---- the hub ----

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "hub", server.Hub())
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})
    monkeypatch.setattr(server.voice, "_cache", {})
    return TestClient(server.app)


def helper_ws(client):
    return client.websocket_connect(f"/helper/ws?token={server.hub.helper_token}")


def test_hub_mac_volume(client):
    with helper_ws(client) as ws:
        r = client.post("/api/command", json={"text": "Can you please increase the volume on my Mac?", "person": "layla"}).json()
        m = ws.receive_json()
        assert m == {"type": "mac", "action": "up", "command_id": r["command"]}
        ws.send_json({"type": "result", "command_id": r["command"], "ok": True, "confirmed": True, "before": 40,
                      "after": 50, "detail": "Volume 40 → 50"})
        client.get("/api/events")
    assert client.get(f"/api/status/{r['command']}").json()["reply"]["text"] == "Done. The Mac's volume is now 50."
    r = client.post("/api/command", json={"text": "mute the mac", "person": "visitor"}).json()
    assert r["status"] == "refused"


def test_ask_for_the_address_then_tap_to_save_and_open(client):
    with helper_ws(client) as ws:
        r = client.post("/api/command", json={"text": "can you open cosmique website on my mac", "person": "layla"}).json()
        assert r["status"] == "question" and "What's the address" in r["reply"]["text"]
        r = client.post("/api/command", json={"text": "um I don't know", "person": "layla"}).json()
        assert r["status"] == "question" and "couldn't make out" in r["reply"]["text"]
        r = client.post("/api/command", json={"text": "https cosmique dot com", "person": "layla"}).json()
        assert r["status"] == "needs_approval" and "https://cosmique.com/" in r["question"]
        assert sites.load() == []  # nothing saved before the tap
        a = client.post(f"/api/approve/{r['approval']}").json()
        assert a["then"] == "sent" and sites.load()[0]["url"] == "https://cosmique.com/"
        m = ws.receive_json()
        assert m["type"] == "site" and m["site_id"] == sites.load()[0]["id"] and "url" not in m
    # next time it is known
    r = client.post("/api/command", json={"text": "open cosmique website on my phone", "person": "layla"}).json()
    assert r["status"] == "open_on_phone" and r["link"] == "https://cosmique.com/"


def test_only_the_owner_adds_sites_and_cancel_works(client):
    r = client.post("/api/command", json={"text": "open cosmique website", "person": "omar"}).json()
    assert "only the owner" in r["reply"]["text"]
    client.post("/api/command", json={"text": "open cosmique website", "person": "layla"})
    r = client.post("/api/command", json={"text": "cancel", "person": "layla"}).json()
    assert r["reply"]["text"] == "Okay, cancelled."
    assert not server.hub.pending


def test_sites_card_is_mac_only(client, monkeypatch):
    assert client.post("/api/sites", json={"name": "Cosmique website", "url": "http://cosmique.com"}).status_code == 400
    assert client.post("/api/sites", json={"name": "Cosmique website", "url": "https://cosmique.com", "words": "cosmic"}).status_code == 200
    monkeypatch.setattr(server, "LOCAL_HOSTS", {"127.0.0.1"})
    assert client.get("/api/sites").status_code == 403


def test_honest_reply_when_not_understood(client):
    r = client.post("/api/command", json={"text": "order a pizza", "person": "layla"}).json()
    assert r["reply"]["text"].startswith("Sorry, I didn't understand that.")
    r = client.post("/api/command", json={"text": "open the lift note", "person": "layla"}).json()
    assert r["reply"]["text"] == "I couldn't find that file."


def test_groq_unclear_asks_back(client, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setattr(understand, "ask", lambda s, m, post=None: {"action": "unclear", "question": "Which website do you mean?"})
    r = client.post("/api/command", json={"text": "open that thing", "person": "layla"}).json()
    assert r["reply"]["text"] == "Just to check: Which website do you mean?"
    assert any(e["type"] == "command.understood" and e["content"]["how"] == "Groq" for e in server.hub.log.list())


def test_thinking_models_get_room_to_answer(monkeypatch):
    """gpt-oss thinks first: with too few tokens Groq returns json_validate_failed. Keep room + short thinking."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    sent = []

    class R:
        status_code = 200
        text = ""
        def json(self):
            return {"choices": [{"message": {"content": '{"action":"mac_volume","op":"up","level":null}'}}]}

    understand.ask("louder on my mac", understand.menu([], "phone"), lambda body: sent.append(body) or R())
    assert sent[0]["model"] == "openai/gpt-oss-120b"
    assert sent[0]["max_tokens"] >= 1000 and sent[0]["reasoning_effort"] == "low"
