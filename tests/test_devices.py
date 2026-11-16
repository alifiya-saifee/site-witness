import subprocess
import sys
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from sitewitness import devices, discover, replies, server
from sitewitness.commands import parse
from sitewitness.connectors import ipp_printer
from sitewitness.connectors.ipp_printer import Printer
from sitewitness.connectors.plug import PlugError, PretendPlug, TapoPlug
from sitewitness.connectors.samsung_tv import SamsungTV
from sitewitness.devices import LAMP, Device, from_found, may_use, plug_from_env

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "helper"))
from diwan_helper import Helper  # noqa: E402

TV_FOUND = {"key": "tv-0a1b2c3d", "kind": "tv", "uid": "uuid:tv", "label": '55" Crystal UHD', "model": "UA55DU8000",
            "address": "10.0.0.68", "mac": "4C:57:39:00:00:01", "connector": True}
PRINTER_FOUND = {"key": "printer-0a1b2c3d", "kind": "printer", "uid": "uuid:pr", "label": "HP LaserJet", "model": "HP",
                 "address": "10.0.0.208", "path": "ipp/print", "connector": True}


@pytest.fixture(autouse=True)
def own_files(monkeypatch, tmp_path):
    """Every test gets its own device list and pretend lamp: the real run/ folder is never touched."""
    monkeypatch.setattr(devices, "ADDED_FILE", tmp_path / "devices.json")
    monkeypatch.setattr(devices, "PRETEND_FILE", tmp_path / "pretend.json")
    for k in ("SW_PLUG", "SW_PLUG_HOST", "TAPO_USERNAME", "TAPO_PASSWORD"):
        monkeypatch.delenv(k, raising=False)


def tv():
    return from_found(TV_FOUND, "Living room TV", "Living room", ["owner", "broker"])


def printer():
    return from_found(PRINTER_FOUND, "HP printer", "Office", ["owner", "broker"])


# ---- words ----

@pytest.mark.parametrize("said,action", [
    ("turn on the lamp", "on"), ("switch the light off", "off"), ("شغّل المصباح", "on"), ("طفّي الضوء", "off"),
])
def test_lamp_words(said, action):
    i = parse(said, [LAMP])
    assert i.device is LAMP and i.action == action and not i.matches


@pytest.mark.parametrize("said,action", [
    ("turn off the TV", "off"), ("اطفئ التلفزيون", "off"), ("turn on the television", "on"), ("volume up", "volume_up"),
    ("turn it down", "volume_down"), ("ارفع الصوت", "volume_up"), ("mute the tv", "mute"),
    ("open YouTube on the TV", "app:youtube"), ("شغل يوتيوب", "app:youtube"), ("put on netflix", "app:netflix"),
])
def test_tv_words(said, action):
    i = parse(said, [LAMP, tv()])
    assert i.device.kind == "tv" and i.action == action


def test_print_words_pick_the_file():
    i = parse("print the Al Noor report", [tv(), printer()])
    assert i.action == "print" and i.device.kind == "printer" and [r.id for r in i.matches] == ["alnoor-report"]
    assert [r.id for r in parse("اطبع تقرير النور", [printer()]).matches] == ["alnoor-report"]


def test_files_still_work_and_a_missing_device_is_never_a_file():
    assert [r.id for r in parse("open the Al Noor slides", [LAMP, tv()]).matches] == ["alnoor-slides"]
    assert parse("افتح عرض النور", [LAMP]).device is None  # "النور" is the building, not the light
    i = parse("turn off the TV", [LAMP])
    assert i.kind == "tv" and i.device is None and not i.device_options


def test_two_tvs_the_name_decides_or_it_asks():
    bedroom = from_found(TV_FOUND | {"key": "tv-99999999"}, "Bedroom TV", "Bedroom", ["owner"])
    assert parse("turn off the bedroom TV", [tv(), bedroom]).device.id == "tv-99999999"
    assert len(parse("turn off the TV", [tv(), bedroom]).device_options) == 2


# ---- the device list ----

def test_adding_saves_and_the_pretend_lamp_steps_aside():
    assert devices.current() == (LAMP,)
    devices.save_added([tv()])
    assert [d.id for d in devices.current()] == ["tv-0a1b2c3d"]  # a real device: no pretend lamp
    assert devices.by_id("tv-0a1b2c3d").name == "the living room TV" and devices.by_id("tv-0a1b2c3d").mac


def test_tapo_lamp_stays_with_real_devices(monkeypatch):
    devices.save_added([tv()])
    for k, v in {"SW_PLUG": "tapo", "SW_PLUG_HOST": "h", "TAPO_USERNAME": "u", "TAPO_PASSWORD": "p"}.items():
        monkeypatch.setenv(k, v)
    assert [d.id for d in devices.current()] == ["room-lamp", "tv-0a1b2c3d"]


def test_from_found_rules():
    assert printer().needs_tap and not tv().needs_tap
    with pytest.raises(ValueError):
        from_found(TV_FOUND, "TV", "Room", [])          # nobody may use it: refused
    with pytest.raises(ValueError):
        from_found({"key": "other-1", "kind": "other"}, "x", "y", ["owner"])  # no connector
    assert from_found(TV_FOUND, "<script>TV", "R", ["owner", "hacker"]).roles == ("owner",)
    assert "<" not in from_found(TV_FOUND, "<script>TV", "R", ["owner"]).name


def test_who_may_use():
    assert may_use("layla", LAMP) and may_use("omar", LAMP) and not may_use("visitor", LAMP)


def test_pretend_plug_and_tapo_settings(tmp_path):
    p = PretendPlug(tmp_path / "plug.json")
    assert p.state() is False and p.set(True) is True and PretendPlug(tmp_path / "plug.json").state() is True
    assert plug_from_env({}).kind == "pretend"
    assert plug_from_env({"SW_PLUG": "tapo", "SW_PLUG_HOST": "1.2.3.4"}).kind == "pretend"
    assert plug_from_env({"SW_PLUG": "tapo", "SW_PLUG_HOST": "h", "TAPO_USERNAME": "u", "TAPO_PASSWORD": "p"}).kind == "tapo"


def test_tapo_errors_never_carry_the_login(monkeypatch):
    plug = TapoPlug("10.0.0.9", "someone@example.com", "secret-pass", timeout=1)

    async def boom(on):
        raise RuntimeError("login secret-pass for someone@example.com failed")
    monkeypatch.setattr(plug, "_do", boom)
    with pytest.raises(PlugError) as e:
        plug.set(True)
    assert "secret" not in str(e.value) and "example.com" not in str(e.value)


# ---- the scan ----

def test_scan_sorts_and_merges():
    heard = [
        {"type": "_airplay._tcp.local.", "name": '55" Crystal UHD', "address": "10.0.0.68", "port": 7000, "props": {}},
        {"type": "_airplay._tcp.local.", "name": '55" Crystal UHD (2)', "address": "10.0.0.68", "port": 7000, "props": {}},
        {"type": "_ipp._tcp.local.", "name": "HP", "address": "10.0.0.208", "port": 631,
         "props": {"UUID": "abc", "ty": "HP Color LaserJet", "rp": "ipp/print"}},
        {"type": "_raop._tcp.local.", "name": "Other Mac", "address": "10.0.0.52", "port": 7000, "props": {}},
        {"type": "_airplay._tcp.local.", "name": "This Mac", "address": "10.0.0.95", "port": 7000, "props": {}},
    ]
    probe = lambda a: {"uid": "uuid:tv", "label": '55" Crystal UHD', "model": "UA55", "mac": "m"} if a == "10.0.0.68" else None
    found = discover.classify(heard, probe=probe, plugs=[{"uid": "aa:bb", "address": "10.0.0.7", "label": "Plug", "model": "P110"}],
                              own={"10.0.0.95"})
    kinds = sorted(f["kind"] for f in found)
    assert kinds == ["other", "plug", "printer", "tv"]  # one TV for two announcements; this Mac left out
    assert next(f for f in found if f["kind"] == "printer")["path"] == "ipp/print"
    assert not next(f for f in found if f["kind"] == "other")["connector"]


# ---- connectors ----

class FakeRemote:
    def __init__(self, tvstate):
        self.s, self.keys = tvstate, []

    def send_key(self, key):
        self.keys.append(key)
        if key == "KEY_POWER":
            self.s["power"] = "standby"
        if key == "KEY_VOLUP":
            self.s["vol"] += 1
        if key == "KEY_MUTE":
            self.s["mute"] = 1 - self.s["mute"]

    def rest_app_run(self, app_id):
        self.s["app"] = app_id

    def rest_app_status(self, app_id):
        return {"visible": self.s.get("app") == app_id}


def fake_tv(tmp_path, power="on", stuck=False):
    st = {"power": power, "vol": 7, "mute": 0}
    remote = FakeRemote(st)
    if stuck:
        remote.send_key = lambda k: None
    get = lambda url: {"device": {"PowerState": st["power"]}}
    post = lambda url, body, h: (f"<CurrentVolume>{st['vol']}</CurrentVolume>" if "GetVolume" in body
                                 else f"<CurrentMute>{st['mute']}</CurrentMute>")
    return SamsungTV("10.0.0.68", "m", tmp_path / "tv.token", remote=remote, get=get, post=post,
                     sleep=lambda s: None, wait=0.05), st


def test_tv_off_is_read_back(tmp_path):
    t, st = fake_tv(tmp_path)
    r = t.do("off")
    assert r["confirmed"] and r["state"] is False
    t2, _ = fake_tv(tmp_path, stuck=True)
    assert not t2.do("off")["confirmed"]  # the TV still says on: not claimed


def test_tv_volume_mute_and_app(tmp_path):
    t, st = fake_tv(tmp_path)
    r = t.do("volume_up")
    assert r["confirmed"] and (r["before"], r["after"]) == (7, 10)
    assert t.do("mute")["muted"] is True
    r = t.do("app:youtube")
    assert r["confirmed"] and r["app"] == "YouTube"
    assert "Refused" in t.do("rm -rf")["detail"]


def test_tv_on_without_wake_says_how(tmp_path):
    t, st = fake_tv(tmp_path, power="off")
    t._wake = lambda mac: None
    r = t.do("on")
    assert not r["ok"] and "Power On with Mobile" in r["detail"]


def ipp_answer(attrs: list[tuple[int, str, object]], status: int = 0) -> bytes:
    body = bytes([2, 0]) + status.to_bytes(2, "big") + (1).to_bytes(4, "big") + b"\x01"
    for tag, name, value in attrs:
        body += ipp_printer._attr(tag, name, value)
    return body + b"\x03"


def fake_printer(job_states, reasons=("none",)):
    states = iter(job_states)

    def post(body, timeout):
        op = int.from_bytes(body[2:4], "big")
        if op == ipp_printer.OP_GET_PRINTER:
            return ipp_answer([(ipp_printer.ENUM, "printer-state", 3)] +
                              [(ipp_printer.KEYWORD, "printer-state-reasons" if i == 0 else "", r) for i, r in enumerate(reasons)])
        if op == ipp_printer.OP_PRINT_JOB:
            assert body.endswith(b"%PDF-test")
            return ipp_answer([(ipp_printer.INTEGER, "job-id", 42)])
        return ipp_answer([(ipp_printer.ENUM, "job-state", next(states))])
    return Printer("10.0.0.208", post=post, sleep=lambda s: None)


def test_printer_job_followed_to_the_end():
    r = fake_printer([5, 9]).print_pdf(b"%PDF-test", "Al Noor")
    assert r["confirmed"] and r["job"] == 42


def test_printer_problem_in_plain_words():
    r = fake_printer([], reasons=("media-empty-error",)).print_pdf(b"%PDF-test", "x")
    assert not r["ok"] and r["problems"] == ["out of paper"]


def test_printer_unreachable():
    def post(body, timeout):
        raise OSError("no route")
    with pytest.raises(ipp_printer.PrinterError):
        Printer("10.0.0.208", post=post).status()


# ---- the helper ----

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


def helper_with(plug=None, photos=(), devs=(LAMP,), **kw):
    h = Helper(runner=lambda cmd, timeout=10: subprocess.CompletedProcess(cmd, 0, "", ""), plug=plug or FakePlug(),
               settle=0, device_list=lambda: devs, **kw)
    shots = iter(photos)
    h.photo = lambda: next(shots)
    return h


MSG = {"type": "device", "command_id": "0123456789ab", "device_id": "room-lamp", "action": "on"}


def test_lamp_on_and_the_camera_sees_it():
    r = helper_with(photos=[jpg(40), jpg(120)]).device(MSG)
    assert r["ok"] and r["confirmed"] and r["state"] is True and r["proof_b64"] and "camera saw it" in r["detail"]


def test_lamp_camera_unsure_is_said_plainly():
    assert "saw no change" in helper_with(photos=[jpg(60), jpg(62)]).device(MSG)["detail"]
    r = helper_with(photos=[None, None]).device(MSG)
    assert r["ok"] and not r["confirmed"] and "couldn't take a photo" in r["detail"]


def test_lamp_unreachable_or_stuck_fails():
    assert not helper_with(FakePlug(fail=True), [jpg(40)]).device(MSG)["ok"]
    assert "still off" in helper_with(FakePlug(stuck=True), [jpg(40)]).device(MSG)["detail"]


def test_pretend_lamp_skips_the_camera(tmp_path):
    r = helper_with(PretendPlug(tmp_path / "p.json")).device(MSG)
    assert r["confirmed"] and "no camera check" in r["detail"]


def test_helper_refuses_anything_else():
    h = helper_with(devs=(LAMP, printer()))
    assert "not a device" in h.device(MSG | {"device_id": "oven"})["detail"]
    assert "can't do that" in h.device(MSG | {"action": "volume_up"})["detail"]       # a plug has no volume
    assert "bad command" in h.device(MSG | {"command_id": "../x"})["detail"]
    pr = MSG | {"device_id": printer().id, "action": "print", "file_id": "alnoor-report", "filename": "../../etc/passwd", "token": "t"}
    assert "not a file" in h.device(pr)["detail"]


def test_helper_tv_passes_the_proof_on(tmp_path):
    t, st = fake_tv(tmp_path)
    h = helper_with(devs=(tv(),), tv_for=lambda d: t)
    r = h.device(MSG | {"device_id": tv().id, "action": "volume_up"})
    assert r["confirmed"] and r["before"] == 7 and r["after"] == 10


def test_helper_prints_once_per_token():
    h = helper_with(devs=(printer(),), printer_for=lambda d: fake_printer([9]), fetch=lambda fid, tok: b"%PDF-test")
    msg = MSG | {"device_id": printer().id, "action": "print", "file_id": "alnoor-report",
                 "filename": "al-noor-signed-report.pdf", "token": "one-time"}
    assert h.device(msg)["confirmed"]
    assert "already used" in h.device(msg)["detail"]


def test_new_replies_in_both_languages():
    for o in replies.TEXT:
        for lang in ("en", "ar"):
            t = replies.reply(o, lang, file="alnoor-report", device=tv(), person="Visitor", to="Karim", kind="tv",
                              before=7, after=10, app="YouTube", problem="out of paper", action="off")
            assert t and "{" not in t, (o, lang)
    assert replies.reply("on", "en", device=LAMP) == "Done. The meeting-room lamp is on."
    assert replies.reply("volume_up", "en", device=tv(), before=7, after=10) == "Turned the volume up, from 7 to 10."


# ---- the hub ----

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "hub", server.Hub())
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})
    monkeypatch.setattr(server.voice, "_cache", {})
    return TestClient(server.app)


def helper_ws(client):
    return client.websocket_connect(f"/helper/ws?token={server.hub.helper_token}")


def test_turn_on_the_lamp_end_to_end(client):
    with helper_ws(client) as ws:
        r = client.post("/api/command", json={"text": "turn on the lamp", "person": "layla"}).json()
        assert r["status"] == "sent"
        assert ws.receive_json() == {"type": "device", "command_id": r["command"], "device_id": "room-lamp", "action": "on"}
        ws.send_json({"type": "result", "command_id": r["command"], "ok": True, "confirmed": True, "state": True, "detail": "ok"})
        client.get("/api/events")
    st = client.get(f"/api/status/{r['command']}").json()
    assert st["state"] == "confirmed" and st["reply"]["text"] == "Done. The meeting-room lamp is on."
    d = client.get("/api/devices").json()[0]
    assert d["on"] is True and d["pretend"] is True


def test_tv_volume_reply_says_the_numbers(client):
    devices.save_added([tv()])
    with helper_ws(client) as ws:
        r = client.post("/api/command", json={"text": "ارفع الصوت", "person": "omar"}).json()
        m = ws.receive_json()
        assert m["action"] == "volume_up" and m["device_id"] == tv().id
        ws.send_json({"type": "result", "command_id": r["command"], "ok": True, "confirmed": True, "before": 7, "after": 10,
                      "detail": "Volume 7 → 10"})
        client.get("/api/events")
    assert client.get(f"/api/status/{r['command']}").json()["reply"]["text"] == "رفعتُ الصوت من 7 إلى 10."


def test_no_tv_added_is_said(client):
    r = client.post("/api/command", json={"text": "turn off the TV", "person": "layla"}).json()
    assert r["status"] == "not_found" and "no TV added" in r["reply"]["text"]


def test_visitor_is_refused_and_nothing_is_sent(client):
    r = client.post("/api/command", json={"text": "turn on the lamp", "person": "visitor"}).json()
    assert r["status"] == "refused" and "isn't allowed to use the meeting-room lamp" in r["reply"]["text"]
    assert not any(e["type"] == "device.command" for e in server.hub.log.list())


def test_printing_waits_for_a_tap_and_prints_once(client):
    devices.save_added([printer()])
    with helper_ws(client) as ws:
        r = client.post("/api/command", json={"text": "print the Al Noor report", "person": "layla"}).json()
        assert r["status"] == "needs_approval" and "Tap Approve" in r["reply"]["text"]
        assert not any(e["type"] == "device.command" for e in server.hub.log.list())  # nothing printed yet
        a = client.post(f"/api/approve/{r['approval']}").json()
        assert a["then"] == "sent"
        m = ws.receive_json()
        assert m["action"] == "print" and m["file_id"] == "alnoor-report" and m["token"]
        assert client.post(f"/api/approve/{r['approval']}").json()["repeat"]  # a double tap doesn't print twice
        ws.send_json({"type": "result", "command_id": a["command"], "ok": False, "problems": ["out of paper"], "detail": "x"})
        client.get("/api/events")
    assert client.get(f"/api/status/{a['command']}").json()["reply"]["text"] == "The printer says: out of paper."


def test_visitor_may_not_print_a_file_they_may_not_open(client):
    devices.save_added([from_found(PRINTER_FOUND, "HP printer", "Office", ["owner", "broker", "visitor"])])
    r = client.post("/api/command", json={"text": "print the Al Noor report", "person": "visitor"}).json()
    assert r["status"] == "refused"


def test_risky_device_waits_for_a_tap(client):
    oven = Device("plug-oven0001", "the test oven", "الفرن", "Kitchen", "plug", ("oven",), ("owner",), risky=True)
    devices.save_added([oven])
    r = client.post("/api/command", json={"text": "turn on the oven", "person": "layla"}).json()
    assert r["status"] == "needs_approval"


def test_scan_and_add_only_on_the_mac(client, monkeypatch):
    monkeypatch.setattr(server.discover, "scan", lambda s: [TV_FOUND, PRINTER_FOUND])
    found = client.post("/api/scan").json()
    assert {f["kind"] for f in found} == {"tv", "printer"} and "mac" not in found[0] and not found[0]["added"]
    with helper_ws(client) as ws:
        a = client.post("/api/devices/add", json={"key": TV_FOUND["key"], "name": "Living room TV", "room": "Living room",
                                                  "roles": ["owner"]}).json()
        assert a["status"] == "added" and a["pairing"]["status"] == "sent"
        assert ws.receive_json()["action"] == "pair"  # the TV shows "Allow" now
    assert devices.by_id(TV_FOUND["key"]).roles == ("owner",)
    assert client.post("/api/devices/add", json={"key": "nope"}).status_code == 404
    assert client.delete(f"/api/devices/{TV_FOUND['key']}").json()["status"] == "removed"
    monkeypatch.setattr(server, "LOCAL_HOSTS", {"127.0.0.1"})  # now a phone on the Wi-Fi
    assert client.post("/api/scan").status_code == 403
    assert client.post("/api/devices/add", json={"key": TV_FOUND["key"]}).status_code == 403


def test_devices_need_pairing(monkeypatch):
    monkeypatch.setattr(server, "hub", server.Hub())
    assert TestClient(server.app).get("/api/devices").status_code == 401
