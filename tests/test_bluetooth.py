"""Bluetooth: scan (the Mac + relays), lamps, SwitchBot, Sphero, relays. Bluetooth is always faked here."""
import asyncio
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sitewitness import bluetooth, devices, server, understand
from sitewitness.bluetooth import Advert
from sitewitness.commands import parse
from sitewitness.connectors import ble_lamp, sphero, switchbot

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "helper"))
from diwan_helper import Helper  # noqa: E402
from sitewitness import mac_map  # noqa: E402


@pytest.fixture(autouse=True)
def own_relays(monkeypatch, tmp_path):
    monkeypatch.setattr(bluetooth, "RELAYS_FILE", tmp_path / "relays.json")


class FakeAdapter:
    def __init__(self, id_="mac", name="this Mac", adverts=(), reply=None, fail=False):
        self.id, self.name, self.adverts, self.reply, self.fail = id_, name, list(adverts), reply, fail
        self.writes = []

    async def scan(self, seconds):
        if self.fail:
            raise bluetooth.BluetoothError("couldn't reach the relay")
        return [Advert(**{**a.__dict__, "via": self.id, "via_name": self.name}) for a in self.adverts]

    async def write(self, address, char, data, notify=None, wait=3.0):
        self.writes.append((address, char, bytes(data), notify))
        return self.reply


ADS = [Advert("A1", "ELK-BLEDOM", -60), Advert("B2", "WoHand", -70, services=(bluetooth.SWITCHBOT_SERVICE,)),
       Advert("C3", "SB-1A2B", -55), Advert("D4", "Triones-77", -80), Advert("E5", "Someone's headphones", -40)]


# ---------------- scan ----------------

def test_scan_guesses_kinds_and_strongest_signal_wins():
    mac = FakeAdapter(adverts=ADS)
    kitchen = FakeAdapter("relay-1", "relay: Kitchen", adverts=[Advert("A1", "ELK-BLEDOM", -45)])
    rows, problems = asyncio.run(bluetooth.scan(1, [mac, kitchen]))
    by = {r["address"]: r for r in rows}
    assert problems == []
    assert by["A1"]["kind"] == "ble_lamp" and by["A1"]["via"] == "relay-1" and by["A1"]["rssi"] == -45
    assert by["A1"]["path"] == "elk" and by["D4"]["path"] == "triones"
    assert by["B2"]["kind"] == "switchbot"
    assert by["C3"]["kind"] == "robot" and by["C3"]["sub"] == "sphero" and by["C3"]["uid"] == "SB-1A2B"
    assert by["E5"]["kind"] == "other" and not by["E5"]["connector"]
    assert mac.writes == [] and kitchen.writes == []  # a scan never writes to anything


def test_a_relay_that_cant_be_reached_doesnt_spoil_the_scan():
    rows, problems = asyncio.run(bluetooth.scan(1, [FakeAdapter(adverts=ADS[:1]), FakeAdapter("r", "Kitchen", fail=True)]))
    assert len(rows) == 1 and "Kitchen" in problems[0]


# ---------------- lamps ----------------

def test_lamp_bytes_for_both_families():
    assert ble_lamp.command("elk", "on")[1].hex() == "7e0404f00001ff00ef"
    assert ble_lamp.command("elk", "off")[1].hex() == "7e04040000 00ff00ef".replace(" ", "")
    assert ble_lamp.command("elk", "colour", "blue")[1].hex() == "7e07050300 00ff10ef".replace(" ", "")
    assert ble_lamp.command("triones", "on") == (ble_lamp.TRIONES_CHAR, bytes.fromhex("cc2333"))
    assert ble_lamp.command("triones", "colour", "أحمر")[1].hex() == "56ff000000f0aa"
    with pytest.raises(ble_lamp.LampError):
        ble_lamp.command("elk", "colour", "tartan")
    assert ble_lamp.next_level(100, "dimmer") == 75 and ble_lamp.next_level(10, "dimmer") == 10


def lamp_device(**kw):
    return devices.Device("bt-lamp", "the LED strip", "الشريط", "Office", "ble_lamp", ("strip",), ("owner", "broker"),
                          address="A1", path="elk", via="mac", **kw)


def helper_for(devs, adapter, **kw):
    h = Helper(runner=lambda c, timeout=10: __import__("subprocess").CompletedProcess(c, 1, "", ""), plug=object(),
               settle=0, device_list=lambda: devs, app_map=mac_map.AppMap([]), bt_adapters=lambda: [adapter], **kw)
    h.photo = lambda: None
    return h


MSG = {"type": "device", "command_id": "0123456789ab"}


def test_helper_lamp_colour_and_honest_proof():
    a = FakeAdapter()
    h = helper_for([lamp_device()], a)
    r = h.device(MSG | {"device_id": "bt-lamp", "action": "colour", "arg": "blue"})
    assert r["ok"] and not r["confirmed"] and "can't report back" in r["detail"]
    assert a.writes == [("A1", ble_lamp.ELK_CHAR, bytes.fromhex("7e0705030000ff10ef"), None)]
    assert "Refused" in h.device(MSG | {"device_id": "bt-lamp", "action": "colour", "arg": "tartan"})["detail"]
    assert len(a.writes) == 1


def test_brighter_and_dimmer_step_through_levels():
    a = FakeAdapter()
    h = helper_for([lamp_device()], a)
    h.device(MSG | {"device_id": "bt-lamp", "action": "dimmer"})
    h.device(MSG | {"device_id": "bt-lamp", "action": "dimmer"})
    assert [w[2][3] for w in a.writes] == [75, 50]


# ---------------- SwitchBot ----------------

def test_switchbot_bytes_and_read_back():
    a = FakeAdapter(reply=bytes([1]))
    r = asyncio.run(switchbot.SwitchBot(a, "B2").do("press"))
    assert r["confirmed"] and a.writes[0] == ("B2", switchbot.WRITE, bytes.fromhex("570100"), switchbot.NOTIFY)
    a = FakeAdapter(reply=bytes([11]))
    assert "battery" in asyncio.run(switchbot.SwitchBot(a, "B2").do("on"))["detail"]
    a = FakeAdapter(reply=None)
    assert not asyncio.run(switchbot.SwitchBot(a, "B2").do("off"))["confirmed"]


def test_a_risky_switchbot_always_needs_a_tap():
    found = {"key": "bt-12345678", "kind": "switchbot", "label": "SwitchBot Bot", "address": "B2", "via": "mac"}
    bot = devices.from_found(found, "Kettle switch", "Kitchen", ["owner"], risky=True)
    assert bot.needs_tap_for("press") and bot.via == "mac"
    assert not devices.from_found(found, "Lamp switch", "Office", ["owner"]).needs_tap_for("press")


# ---------------- Sphero ----------------

class FakeEdu:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.calls.append("disconnect")

    def roll(self, heading, speed, seconds):
        self.calls.append(("roll", heading, speed, seconds))

    def stop_roll(self):
        self.calls.append("stop")

    def spin(self, angle, seconds):
        self.calls.append(("spin", angle))


def test_sphero_moves_are_short_and_capped():
    edu = FakeEdu()
    r = sphero.Sphero("SB-1A2B", api_factory=lambda name: edu).do("forward")
    assert r["confirmed"] and edu.calls == [("roll", 0, 128, 2), "stop", "disconnect"]
    assert sphero.SPEED <= 128 and sphero.MAX_SECONDS <= 2


SPHERO = devices.Device("bt-sphero", "the Sphero", "سفيرو", "Office", "robot", ("sphero",), ("owner", "broker"),
                        sub="sphero", uid="SB-1A2B", address="C3", via="mac")


def test_sphero_rules_moves_need_a_tap_stop_and_light_dont():
    assert SPHERO.needs_tap_for("forward") and SPHERO.needs_tap_for("spin")
    assert not SPHERO.needs_tap_for("stop") and not SPHERO.needs_tap_for("colour")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "hub", server.Hub())
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})
    monkeypatch.setattr(server.voice, "_cache", {})
    with TestClient(server.app) as c:
        yield c


def test_sphero_forward_waits_for_approve_and_stop_cancels_it(client, monkeypatch):
    monkeypatch.setattr(devices, "load_added", lambda path=None: [SPHERO])
    monkeypatch.setenv("GROQ_API_KEY", "test")
    def fake_ask(sentence, menu, post=None):
        do = "stop" if "stop" in sentence else "forward"
        return {"steps": [{"action": "device", "device": "bt-sphero", "do": do}]}
    monkeypatch.setattr(understand, "ask", fake_ask)
    ws = client.websocket_connect(f"/helper/ws?token={server.hub.helper_token}")
    ws.__enter__()
    r = client.post("/api/command", json={"text": "sphero go forward", "person": "layla"}).json()
    assert r["status"] == "needs_approval"
    aid = r["approval"]
    r = client.post("/api/command", json={"text": "stop", "person": "layla"}).json()
    assert r["status"] == "sent"
    m = ws.receive_json()
    assert m["action"] == "stop" and m["device_id"] == "bt-sphero"
    assert client.post(f"/api/approve/{aid}").json()["status"] == "cancelled"
    ws.__exit__(None, None, None)
    r = client.post("/api/command", json={"text": "sphero go forward", "person": "visitor"}).json()
    assert r["status"] in ("refused", "not_found")


def test_helper_sphero_colour(monkeypatch):
    edu = FakeEdu()
    edu.set_main_led = lambda c: edu.calls.append(("led", c))
    types_mod = type(sys)("spherov2.types")
    types_mod.Color = lambda r, g, b: (r, g, b)
    monkeypatch.setitem(sys.modules, "spherov2", type(sys)("spherov2"))
    monkeypatch.setitem(sys.modules, "spherov2.types", types_mod)
    h = helper_for([SPHERO], FakeAdapter(), sphero_for=lambda d: sphero.Sphero(d.uid, api_factory=lambda n: edu))
    r = h.device(MSG | {"device_id": "bt-sphero", "action": "colour", "arg": "green"})
    assert r["confirmed"] and ("led", (0, 255, 0)) in edu.calls


# ---------------- relays ----------------

KEY = "A" * 43 + "="


def test_relay_key_is_never_shown_or_logged(client):
    r = client.post("/api/relays", json={"name": "Kitchen", "host": "kitchen-proxy.local", "key": KEY})
    assert r.status_code == 200 and KEY not in r.text
    listing = client.get("/api/relays")
    assert KEY not in listing.text and listing.json()[0]["has_key"] is True
    assert KEY not in str(server.hub.log.list())
    assert oct(bluetooth.RELAYS_FILE.stat().st_mode)[-3:] == "600"
    assert client.post("/api/relays", json={"name": "x", "host": "bad host; rm"}).status_code == 400
    assert client.post("/api/relays", json={"name": "x", "host": "10.0.0.5", "key": "short"}).status_code == 400
    rid = listing.json()[0]["id"]
    assert client.delete(f"/api/relays/{rid}").json()["status"] == "removed"


def test_only_the_mac_manages_relays(monkeypatch):
    monkeypatch.setattr(server, "hub", server.Hub())
    c = TestClient(server.app)  # not localhost
    assert c.post("/api/relays", json={"name": "K", "host": "10.0.0.5"}).status_code in (401, 403)
    assert c.post("/api/bt-scan").status_code in (401, 403)


def test_adapter_choice():
    mac, kitchen = FakeAdapter(), FakeAdapter("relay-1", "Kitchen")
    assert bluetooth.adapter_for("relay-1", [mac, kitchen]) is kitchen
    assert bluetooth.adapter_for("relay-gone", [mac, kitchen]) is mac
    assert bluetooth.adapter_for("", [mac, kitchen]) is mac


def test_bt_scan_through_the_hub(client):
    ws = client.websocket_connect(f"/helper/ws?token={server.hub.helper_token}")
    ws.__enter__()
    out = {}
    t = threading.Thread(target=lambda: out.update(r=client.post("/api/bt-scan").json()))
    t.start()
    m = ws.receive_json()
    assert m["type"] == "bt_scan"
    rows, _ = asyncio.run(bluetooth.scan(0, [FakeAdapter(adverts=ADS)]))
    ws.send_json({"type": "bt_found", "request_id": m["request_id"], "items": rows, "problems": []})
    t.join(5)
    r = out["r"]
    assert len(r["items"]) == 5 and sum(i["connector"] for i in r["items"]) == 4
    lamp = next(i for i in r["items"] if i["kind"] == "ble_lamp" and i["name"] == "ELK-BLEDOM")
    a = client.post("/api/devices/add", json={"key": lamp["key"], "name": "LED strip", "room": "Office",
                                              "roles": ["owner"]}).json()
    dev = devices.by_id(a["device"])
    assert dev.kind == "ble_lamp" and dev.address == "A1" and dev.path == "elk" and dev.via == "mac"
    ws.__exit__(None, None, None)


# ---------------- understanding ----------------

def test_make_the_strip_blue_by_words_and_by_groq():
    strip = lamp_device()
    i = parse("make the strip blue", [strip])
    assert (i.action, i.place, i.device) == ("colour", "blue", strip)
    i = understand.to_intent({"action": "device", "device": "bt-lamp", "do": "colour", "place": "Blue"}, "blue strip",
                             [strip], "mac")
    assert (i.action, i.place) == ("colour", "blue")
    assert understand.to_intent({"action": "device", "device": "bt-lamp", "do": "colour", "place": "tartan"}, "x",
                                [strip], "mac") is None
    assert understand.menu([strip], "mac")["devices"][0]["colours"][:3] == ["red", "green", "blue"]


def test_two_bluetooth_steps_in_one_sentence(monkeypatch):
    bot = devices.Device("bt-bot", "the coffee switch", "زر القهوة", "Kitchen", "switchbot", ("coffee switch",),
                         ("owner",), address="B2", via="mac")
    steps, _, skipped = understand.to_plan(
        {"steps": [{"action": "device", "device": "bt-lamp", "do": "colour", "place": "blue"},
                   {"action": "device", "device": "bt-bot", "do": "press"}]},
        "turn the strip blue and press the coffee switch", [lamp_device(), bot], "mac")
    assert [(s.action, s.device.id) for s in steps] == [("colour", "bt-lamp"), ("press", "bt-bot")] and skipped == 0
