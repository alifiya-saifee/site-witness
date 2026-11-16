import subprocess
import sys
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from sitewitness import devices, replies, server
from sitewitness.commands import parse
from sitewitness.devices import BY_DEVICE, Device, PlugError, PretendPlug, may_use, plug_from_env

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "helper"))
import diwan_helper  # noqa: E402
from diwan_helper import Helper  # noqa: E402


# ---- words ----

@pytest.mark.parametrize("said,action", [
    ("turn on the lamp", "on"), ("switch the light off", "off"), ("turn off the lights", "off"),
    ("شغّل المصباح", "on"), ("طفّي الضوء", "off"), ("اطفئ الإضاءة", "off"),
])
def test_device_words_in_english_and_arabic(said, action):
    i = parse(said)
    assert i.device is BY_DEVICE["room-lamp"] and i.action == action and not i.matches


def test_files_still_work_and_never_touch_the_lamp():
    assert [r.id for r in parse("open the Al Noor slides").matches] == ["alnoor-slides"] and parse("open the Al Noor slides").device is None
    assert parse("افتح عرض النور").device is None  # "النور" is the building, not the light
    assert len(parse("open the report").matches) == 2


# ---- rules and adapters ----

def test_who_may_use_the_lamp():
    lamp = BY_DEVICE["room-lamp"]
    assert may_use("layla", lamp) and may_use("omar", lamp) and not may_use("visitor", lamp)


def test_pretend_plug_remembers(tmp_path):
    p = PretendPlug(tmp_path / "plug.json")
    assert p.state() is False and p.set(True) is True and PretendPlug(tmp_path / "plug.json").state() is True


def test_tapo_only_with_all_settings():
    assert plug_from_env({}).kind == "pretend"
    assert plug_from_env({"SW_PLUG": "tapo", "SW_PLUG_HOST": "192.168.1.9"}).kind == "pretend"
    assert plug_from_env({"SW_PLUG": "tapo", "SW_PLUG_HOST": "h", "TAPO_USERNAME": "u", "TAPO_PASSWORD": "p"}).kind == "tapo"


def test_tapo_errors_never_carry_the_login(monkeypatch):
    plug = devices.TapoPlug("10.0.0.9", "someone@example.com", "secret-pass", timeout=1)

    async def boom(on):
        raise RuntimeError("login secret-pass for someone@example.com failed")
    monkeypatch.setattr(plug, "_do", boom)
    with pytest.raises(PlugError) as e:
        plug.set(True)
    assert "secret" not in str(e.value) and "example.com" not in str(e.value)


def test_new_replies_in_both_languages():
    for o in ("on", "off", "switch_unseen", "switch_failed", "refused_device", "approve_device"):
        for lang in ("en", "ar"):
            t = replies.reply(o, lang, device="room-lamp", person="Visitor", action="off")
            assert t and "{" not in t
    assert replies.reply("on", "en", device="room-lamp") == "Done. The meeting-room lamp is on."


# ---- the helper switches and proves it ----

def jpg(level: int) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (64, 48), (level, level, level)).save(buf, "JPEG")
    return buf.getvalue()


class FakePlug:
    kind, real = "tapo", True

    def __init__(self, fail=False, stuck=False):
        self.on, self.fail, self.stuck = False, fail, stuck

    def set(self, on):
        if self.fail:
            raise PlugError("TimeoutError")
        if not self.stuck:
            self.on = on
        return self.on

    def state(self):
        return self.on


def helper_with(plug, photos):
    h = Helper(runner=lambda cmd, timeout=10: subprocess.CompletedProcess(cmd, 0, "", ""), plug=plug, settle=0)
    shots = iter(photos)
    h.photo = lambda: next(shots)
    return h


MSG = {"type": "switch", "command_id": "0123456789ab", "device_id": "room-lamp", "action": "on"}


def test_lamp_on_and_the_camera_sees_it():
    r = helper_with(FakePlug(), [jpg(40), jpg(120)]).switch(MSG)
    assert r["ok"] and r["confirmed"] and r["state"] is True and r["proof_b64"] and "camera saw it" in r["detail"]


def test_off_needs_darker():
    plug = FakePlug(); plug.on = True
    r = helper_with(plug, [jpg(120), jpg(40)]).switch(MSG | {"action": "off"})
    assert r["confirmed"] and r["state"] is False


def test_no_change_on_camera_is_not_claimed():
    r = helper_with(FakePlug(), [jpg(60), jpg(62)]).switch(MSG)
    assert r["ok"] and not r["confirmed"] and "saw no change" in r["detail"]


def test_camera_blocked_is_said_plainly():
    r = helper_with(FakePlug(), [None, None]).switch(MSG)
    assert r["ok"] and not r["confirmed"] and "couldn't take a photo" in r["detail"]


def test_plug_unreachable_or_stuck_fails():
    assert not helper_with(FakePlug(fail=True), [jpg(40)]).switch(MSG)["ok"]
    r = helper_with(FakePlug(stuck=True), [jpg(40)]).switch(MSG)
    assert not r["ok"] and "still off" in r["detail"]


def test_helper_refuses_anything_else():
    h = helper_with(FakePlug(), [])
    assert "not a device" in h.switch(MSG | {"device_id": "oven"})["detail"]
    assert "only switch" in h.switch(MSG | {"action": "rm -rf"})["detail"]
    assert "bad command" in h.switch(MSG | {"command_id": "../x"})["detail"]


def test_pretend_plug_skips_the_camera(tmp_path):
    h = helper_with(PretendPlug(tmp_path / "p.json"), [])  # no photos: must not ask for any
    r = h.switch(MSG)
    assert r["confirmed"] and "no camera check" in r["detail"] and r["plug"] == "pretend"


# ---- the hub ----

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "hub", server.Hub())
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})
    monkeypatch.setattr(server.voice, "_cache", {})
    return TestClient(server.app)


def test_turn_on_the_lamp_end_to_end(client):
    with client.websocket_connect(f"/helper/ws?token={server.hub.helper_token}") as ws:
        r = client.post("/api/command", json={"text": "turn on the lamp", "person": "layla"}).json()
        assert r["status"] == "sent"
        msg = ws.receive_json()
        assert msg == {"type": "switch", "command_id": r["command"], "device_id": "room-lamp", "action": "on"}
        ws.send_json({"type": "result", "command_id": r["command"], "ok": True, "confirmed": True, "state": True,
                      "detail": "Plug is on and the camera saw it"})
        client.get("/api/events")
    st = client.get(f"/api/status/{r['command']}").json()
    assert st["state"] == "confirmed" and st["device"] == "room-lamp"
    assert st["reply"]["text"] == "Done. The meeting-room lamp is on."
    assert client.get("/api/devices").json()[0]["on"] is True
    types = [e["type"] for e in server.hub.log.list()]
    assert "device.matched" in types and "device.command" in types and "device.confirmed" in types


def test_camera_unsure_gives_an_honest_reply(client):
    with client.websocket_connect(f"/helper/ws?token={server.hub.helper_token}") as ws:
        r = client.post("/api/command", json={"text": "شغّل المصباح", "person": "omar"}).json()
        ws.receive_json()
        ws.send_json({"type": "result", "command_id": r["command"], "ok": True, "confirmed": False, "state": True,
                      "detail": "camera blocked"})
        client.get("/api/events")
    st = client.get(f"/api/status/{r['command']}").json()
    assert st["state"] == "unconfirmed" and "الكاميرا" in st["reply"]["text"]


def test_visitor_is_refused_and_nothing_is_sent(client):
    r = client.post("/api/command", json={"text": "turn on the lamp", "person": "visitor"}).json()
    assert r["status"] == "refused" and "isn't allowed to use the meeting-room lamp" in r["reply"]["text"]
    assert not any(e["type"] == "device.command" for e in server.hub.log.list())


def test_risky_device_waits_for_a_tap(client, monkeypatch):
    oven = Device("test-oven", "the test oven", "الفرن", "Kitchen", "plug", ("oven",), ("owner",), risky=True)
    monkeypatch.setitem(server.BY_DEVICE, oven.id, oven)
    monkeypatch.setattr("sitewitness.commands.DEVICES", devices.DEVICES + (oven,))
    with client.websocket_connect(f"/helper/ws?token={server.hub.helper_token}") as ws:
        r = client.post("/api/command", json={"text": "turn on the oven", "person": "layla"}).json()
        assert r["status"] == "needs_approval"
        assert not any(e["type"] == "device.command" for e in server.hub.log.list())  # nothing switched yet
        a = client.post(f"/api/approve/{r['approval']}").json()
        assert a["then"] == "sent"
        assert ws.receive_json()["device_id"] == "test-oven"
        again = client.post(f"/api/approve/{r['approval']}").json()
        assert again["repeat"] and again["command"] == a["command"]  # a double tap doesn't switch twice


def test_devices_need_pairing(monkeypatch):
    monkeypatch.setattr(server, "hub", server.Hub())
    assert TestClient(server.app).get("/api/devices").status_code == 401
