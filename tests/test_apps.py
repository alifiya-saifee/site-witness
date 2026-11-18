import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from phone import join
from sitewitness import apps, devices, replies, server
from sitewitness.commands import parse
from sitewitness.devices import LAMP, from_found

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "helper"))
from diwan_helper import Helper  # noqa: E402

TV = from_found({"key": "tv-1", "kind": "tv", "label": "TV"}, "Living room TV", "Living room", ["owner"])


@pytest.fixture(autouse=True)
def own_files(monkeypatch, tmp_path):
    monkeypatch.setattr(devices, "ADDED_FILE", tmp_path / "devices.json")
    monkeypatch.setattr(apps, "whatsapp_installed", lambda: False)  # as on this Mac today


# ---- where it opens ----

@pytest.mark.parametrize("said,spoke_from,app,target", [
    ("can you open youtube on my mac", "phone", "youtube", "mac"),
    ("افتح يوتيوب على الماك", "phone", "youtube", "mac"),
    ("open youtube on my phone", "mac", "youtube", "phone"),
    ("open mail", "mac", "mail", "mac"),
    ("open mail", "phone", "mail", "phone"),
    ("open calendar", "phone", "calendar", "phone"),
    ("افتح التقويم على الماك", "phone", "calendar", "mac"),
    ("open my inbox on the laptop", "phone", "mail", "mac"),
])
def test_where(said, spoke_from, app, target):
    i = parse(said, [LAMP], spoke_from)
    assert (i.action, i.app, i.target) == ("app", app, target)


def test_youtube_goes_to_the_tv_unless_a_place_is_named():
    assert parse("open youtube", [LAMP, TV], "phone").device is TV
    assert parse("open youtube on my mac", [LAMP, TV], "phone").target == "mac"


def test_email_drafts_and_file_sends_stay_apart():
    i = parse("write an email saying the report is ready", [LAMP], "mac")
    assert (i.app, i.message) == ("mail", "the report is ready")
    assert parse("اكتب إيميل: التقرير جاهز", [LAMP], "mac").message == "التقرير جاهز"
    send = parse("email the Al Noor report to Karim", [LAMP], "phone")
    assert send.action == "send" and [r.id for r in send.matches] == ["alnoor-report"]


# ---- the commands built on the Mac ----

def test_mac_commands_come_only_from_the_list():
    assert apps.mac_command("youtube") == ["open", "https://www.youtube.com/"]
    assert apps.mac_command("mail") == ["open", "-a", "Mail"]
    assert apps.mac_command("calendar") == ["open", "-a", "Calendar"]
    cmd = apps.mac_command("mail", "the report is ready & signed")
    assert cmd[0] == "open" and cmd[1].startswith("mailto:?body=") and unquote(cmd[1].split("=", 1)[1]) == "the report is ready & signed"
    assert apps.mac_command("whatsapp", "hi")[1].startswith("https://web.whatsapp.com/send?text=")
    assert apps.mac_command("mail", "a\x00b\nc")[1] == "mailto:?body=a%20b%20c"  # no control characters


# ---- the helper ----

def helper_with(front="Mail", ok=True):
    calls = []

    def runner(cmd, timeout=10):
        calls.append(cmd)
        if cmd[:2] == ["lsappinfo", "info"]:
            return subprocess.CompletedProcess(cmd, 0, f'"LSDisplayName"="{front}"', "")
        return subprocess.CompletedProcess(cmd, 0 if ok else 1, "", "")
    h = Helper(runner=runner, plug=object(), wait=0.2)
    h.screenshot = lambda: "proof"
    return h, calls


MSG = {"type": "app", "command_id": "0123456789ab", "app": "mail"}


def test_helper_opens_and_checks_it_is_in_front():
    h, calls = helper_with("Mail")
    r = h.open_app(MSG)
    assert r["confirmed"] and calls[0] == ["open", "-a", "Mail"] and r["proof_b64"] == "proof"
    h, _ = helper_with("Code")
    r = h.open_app(MSG)
    assert r["ok"] and not r["confirmed"] and "Code is in front" in r["detail"]


def test_helper_youtube_in_any_browser():
    h, calls = helper_with("Google Chrome")
    assert h.open_app(MSG | {"app": "youtube"})["confirmed"] and calls[0] == ["open", "https://www.youtube.com/"]


def test_helper_refuses_anything_else():
    h, calls = helper_with()
    assert "not an app" in h.open_app(MSG | {"app": "terminal"})["detail"]
    assert "not an app" in h.open_app(MSG | {"app": "phone"})["detail"]  # the dialler isn't on the Mac
    assert "only from the list" in h.open_app(MSG | {"link": "https://evil.example"})["detail"]
    assert "1,000" in h.open_app(MSG | {"text": "x" * 1001})["detail"]
    assert calls == []  # nothing ran


def test_helper_open_failure():
    h, _ = helper_with(ok=False)
    assert not h.open_app(MSG)["ok"]


# ---- replies ----

def test_new_replies_fill_in_both_languages():
    for o in ("mail_draft_phone", "app_mac", "app_draft_mac", "whatsapp_draft_mac", "app_unconfirmed", "app_failed",
              "app_not_on_phone", "app_not_on_mac", "refused_mac_app"):
        for lang in ("en", "ar"):
            t = replies.reply(o, lang, app="Calendar", person="Visitor")
            assert t and "{" not in t
    assert replies.reply("app_mac", "ar", app="Calendar") == "تم. فتحتُ التقويم على جهاز الماك."


# ---- the hub ----

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "hub", server.Hub())
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})  # the Mac's own page
    monkeypatch.setattr(server.voice, "_cache", {})
    return TestClient(server.app)


def test_open_youtube_on_my_mac_from_the_hub(client):
    with client.websocket_connect(f"/helper/ws?token={server.hub.helper_token}") as ws:
        r = client.post("/api/command", json={"text": "can you open youtube on my mac", "person": "layla"}).json()
        assert r["status"] == "sent"
        m = ws.receive_json()
        assert m == {"type": "app", "command_id": r["command"], "app": "youtube"}  # a key, never a link or command
        ws.send_json({"type": "result", "command_id": r["command"], "ok": True, "confirmed": True, "detail": "ok"})
        client.get("/api/events")
    assert client.get(f"/api/status/{r['command']}").json()["reply"]["text"] == "Done. YouTube is open on your Mac."


def test_mail_draft_text_goes_to_the_helper_but_not_the_log(client):
    with client.websocket_connect(f"/helper/ws?token={server.hub.helper_token}") as ws:
        r = client.post("/api/command", json={"text": "write an email saying the slab is cracked", "person": "layla"}).json()
        m = ws.receive_json()
        assert m["app"] == "mail" and m["text"] == "the slab is cracked"
        ws.send_json({"type": "result", "command_id": r["command"], "ok": True, "confirmed": True, "detail": "ok"})
        client.get("/api/events")
    assert "press send yourself" in client.get(f"/api/status/{r['command']}").json()["reply"]["text"]
    opened = [e for e in server.hub.log.list() if e["type"] == "app.opened"]
    assert opened and "slab" not in json.dumps(opened)


def test_visitor_cant_open_mac_apps_but_can_on_their_phone(client):
    r = client.post("/api/command", json={"text": "open calendar on my mac", "person": "visitor"}).json()
    assert r["status"] == "refused" and "open apps on the Mac" in r["reply"]["text"]
    r = client.post("/api/command", json={"text": "open youtube on my phone", "person": "visitor"}).json()
    assert r["status"] == "open_on_phone"


def test_calendar_on_a_phone_and_dialler_on_the_mac_are_explained(client):
    r = client.post("/api/command", json={"text": "open calendar on my phone", "person": "layla"}).json()
    assert r["status"] == "not_found" and "on my Mac" in r["reply"]["text"]
    r = client.post("/api/command", json={"text": "open the dialler on my mac", "person": "layla"}).json()
    assert r["status"] == "not_found" and "only on your phone" in r["reply"]["text"]


def test_no_helper(client):
    r = client.post("/api/command", json={"text": "open mail", "person": "layla"}).json()
    assert r["status"] == "no_helper"


def test_phone_mail_button(client, monkeypatch):
    monkeypatch.setattr(server, "LOCAL_HOSTS", {"127.0.0.1"})  # a phone
    token = join(client)
    r = client.post("/api/command", headers={"X-Session": token},
                    json={"text": "write an email saying see you at 3", "person": "layla"}).json()
    assert r["status"] == "open_on_phone" and r["link"] == "mailto:?body=see%20you%20at%203" and r["app"] == "Mail"
