import json
import threading
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from sitewitness import devices, replies, server
from sitewitness.commands import parse
from sitewitness.connectors import robots, roborock_vac
from sitewitness.connectors.robots import PretendRobot
from sitewitness.connectors.ros_robot import RosRobot
from sitewitness.devices import LAMP, PRETEND_ROS, PRETEND_VACUUM, from_found

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "helper"))
from diwan_helper import Helper  # noqa: E402

DEVS = [LAMP, PRETEND_VACUUM, PRETEND_ROS]


@pytest.fixture(autouse=True)
def own_files(monkeypatch, tmp_path):
    monkeypatch.setattr(devices, "ADDED_FILE", tmp_path / "devices.json")
    monkeypatch.setattr(devices, "PRETEND_FILE", tmp_path / "pretend.json")
    for k in ("SW_PLUG", "SW_PLUG_HOST", "TAPO_USERNAME", "TAPO_PASSWORD"):
        monkeypatch.delenv(k, raising=False)


# ---- phone apps ----

@pytest.mark.parametrize("said", ["open WhatsApp", "افتح واتساب", "open whatsapp on my phone"])
def test_open_whatsapp(said):
    i = parse(said, DEVS)
    assert i.action == "app" and i.app == "whatsapp" and i.target == "phone" and i.message is None


def test_whatsapp_message_is_typed_not_sent():
    i = parse("WhatsApp message: I've sent the report & the quote", DEVS)
    assert i.message == "I've sent the report & the quote"
    from sitewitness import apps
    url = apps.link("whatsapp", i.message)
    assert url.startswith("https://wa.me/?text=") and unquote(url.split("=", 1)[1]) == i.message and "&the" not in url


def test_youtube_goes_to_the_tv_unless_on_my_phone():
    tv = from_found({"key": "tv-1", "kind": "tv", "label": "TV"}, "Living room TV", "Living room", ["owner"])
    assert parse("open YouTube", DEVS).target == "phone"
    assert parse("open YouTube", DEVS + [tv]).device.kind == "tv"
    assert parse("open YouTube on my phone", DEVS + [tv]).target == "phone"


# ---- robot words ----

@pytest.mark.parametrize("said,dev,action,place", [
    ("clean the kitchen", PRETEND_VACUUM, "clean", "Kitchen"),
    ("نظف المطبخ", PRETEND_VACUUM, "clean", "Kitchen"),
    ("start the vacuum", PRETEND_VACUUM, "start", None),
    ("send the vacuum home", PRETEND_VACUUM, "dock", None),
    ("stop the vacuum", PRETEND_VACUUM, "stop", None),
    ("robot go to the meeting room", PRETEND_ROS, "goto", "Meeting room"),
    ("روح غرفة الاجتماعات", PRETEND_ROS, "goto", "Meeting room"),
])
def test_robot_words(said, dev, action, place):
    i = parse(said, DEVS)
    assert i.device is dev and i.action == action and i.place == place


def test_stop_alone_means_every_robot_and_files_are_untouched():
    i = parse("stop", DEVS)
    assert i.action == "stop" and i.device is None and len(i.device_options) == 2
    assert parse("وقف", DEVS).action == "stop"
    assert [r.id for r in parse("open the Al Noor slides", DEVS).matches] == ["alnoor-slides"]


def test_unknown_room_is_named():
    i = parse("clean the bathroom", DEVS)
    assert i.device is PRETEND_VACUUM and i.place_unknown == "bathroom"


# ---- pretend robots ----

def test_pretend_vacuum_goes_home_then_charges(tmp_path):
    t = [1000.0]
    r = PretendRobot(PRETEND_VACUUM.id, "vacuum", PRETEND_VACUUM.places, tmp_path / "r.json", travel=3,
                     wait=1, sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0])
    assert r.do("clean", "Kitchen")["confirmed"]
    assert r.do("dock")["state"] == "returning_home"
    t[0] += 5
    assert r.status()["state"] == "charging"


def test_pretend_ros_robot_arrives(tmp_path):
    t = [0.0]
    r = PretendRobot(PRETEND_ROS.id, "ros", PRETEND_ROS.places, tmp_path / "r.json", travel=2, wait=5,
                     sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0])
    out = r.do("goto", "Reception")
    assert out["confirmed"] and out["place"] == "Reception"


# ---- the real ROS connector, against a pretend rosbridge ----

class FakeRosbridge:
    """A tiny rosbridge: accepts a Nav2 goal, 'drives' (sends poses), answers cancels, records what it got."""

    def __init__(self, drive_to=None, finish=True):
        from websockets.sync.server import serve
        self.got, self.drive_to, self.finish = [], drive_to, finish
        self.server = serve(self.handle, "127.0.0.1", 0)
        self.port = self.server.socket.getsockname()[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def handle(self, ws):
        pose = [0.0, 0.0]
        for raw in ws:
            m = json.loads(raw)
            self.got.append(m)

            def send_pose():
                ws.send(json.dumps({"op": "publish", "topic": "/amcl_pose",
                                    "msg": {"pose": {"pose": {"position": {"x": pose[0], "y": pose[1], "z": 0}}}}}))
            if m["op"] == "subscribe":
                send_pose()
            if m["op"] == "call_service":
                ws.send(json.dumps({"op": "service_response", "id": m["id"], "result": True, "values": {"return_code": 0}}))
            if m["op"] == "send_action_goal" and self.drive_to:
                for step in (0.5, 1.0):
                    pose[:] = [self.drive_to[0] * step, self.drive_to[1] * step]
                    send_pose()
                if self.finish:
                    ws.send(json.dumps({"op": "action_result", "id": m["id"], "status": 4, "result": True}))

    def close(self):
        self.server.shutdown()


def ros(bridge, tmp_path, wait=3):
    return RosRobot("127.0.0.1", bridge.port, PRETEND_ROS.spots, tmp_path / "ros.json", wait=wait)


def test_ros_robot_goes_to_a_spot_and_is_seen_there(tmp_path):
    bridge = FakeRosbridge(drive_to=(4.0, 2.0))
    try:
        r = ros(bridge, tmp_path).do("goto", "Meeting room")
    finally:
        bridge.close()
    assert r["confirmed"] and r["place"] == "Meeting room"
    goal = next(m for m in bridge.got if m["op"] == "send_action_goal")
    assert goal["action"] == "/navigate_to_pose" and goal["args"]["pose"]["pose"]["position"]["x"] == 4.0


def test_ros_stop_cancels_the_goal_and_sends_zero_speed(tmp_path):
    (tmp_path / "ros.json").write_text(json.dumps({"goal": "diwan-abc"}))
    bridge = FakeRosbridge()
    try:
        r = ros(bridge, tmp_path).do("stop")
    finally:
        bridge.close()
    ops = [(m["op"], m.get("topic") or m.get("service") or m.get("id")) for m in bridge.got]
    assert ("call_service", "/navigate_to_pose/_action/cancel_goal") in ops  # cancels every goal, from any connection
    assert ("publish", "/cmd_vel") in ops
    assert "Nav2 cancelled its goals" in r["detail"]
    assert r["confirmed"]  # the robot's position didn't change


def test_ros_unreachable_is_said(tmp_path):
    r = RosRobot("127.0.0.1", 1, PRETEND_ROS.spots, tmp_path / "ros.json").do("goto", "Reception")
    assert not r["ok"] and "rosbridge" in r["detail"]


def test_ros_unknown_spot_refused(tmp_path):
    assert "no spot" in RosRobot("127.0.0.1", 1, PRETEND_ROS.spots, tmp_path / "x").do("goto", "Mars")["detail"]


# ---- Roborock (fake library objects) ----

class FakeProps:
    def __init__(self, after, error=None):
        self.sent, self.after, self.err = [], after, error
        outer = self

        class Status:
            state = None
            battery = 77
            error_code = None

            async def refresh(self):
                self.state = type("S", (), {"name": outer.after})()
                self.error_code = type("E", (), {"name": outer.err})() if outer.err else None

        class Command:
            async def send(self, cmd, params=None):
                outer.sent.append((cmd, params))
        self.status, self.command = Status(), Command()


def fake_vacuum(monkeypatch, after, error=None):
    props = FakeProps(after, error)
    v = roborock_vac.RoborockVacuum("duid1", (("Kitchen",),), Path("/nonexistent"), segments={"Kitchen": 16},
                                    wait=0.01, sleep=lambda s: None)

    async def with_device(work):
        return await work(props)
    monkeypatch.setattr(v, "_with_device", with_device)
    return v, props


def test_roborock_clean_room_confirmed(monkeypatch):
    v, props = fake_vacuum(monkeypatch, "segment_cleaning")
    r = v.do("clean", "Kitchen")
    assert r["confirmed"] and props.sent == [("app_segment_clean", [{"segments": [16], "repeat": 1}])] and r["battery"] == 77


def test_roborock_dock_and_stuck(monkeypatch):
    assert fake_vacuum(monkeypatch, "returning_home")[0].do("dock")["confirmed"]
    r = fake_vacuum(monkeypatch, "error", error="wheels_suspended")[0].do("start")
    assert not r["ok"] and r["problem"] == "wheels suspended"


def test_roborock_errors_never_carry_the_token(monkeypatch, tmp_path):
    v = roborock_vac.RoborockVacuum("d", (), tmp_path / "rr.json")

    async def boom(work):
        raise RuntimeError("token=SECRET-TOKEN rejected for someone@example.com")
    monkeypatch.setattr(v, "_with_device", boom)
    r = v.do("start")
    assert "SECRET" not in json.dumps(r) and "example.com" not in json.dumps(r)


# ---- the helper ----

def test_helper_robot_rules(tmp_path):
    calls = []

    class Fake:
        def do(self, action, place=None):
            calls.append((action, place))
            return {"ok": True, "confirmed": True, "state": "segment_cleaning", "battery": 80, "detail": "ok"}
    h = Helper(plug=object(), device_list=lambda: DEVS, robot_for=lambda d: Fake())
    msg = {"type": "device", "command_id": "0123456789ab", "device_id": PRETEND_VACUUM.id, "action": "clean", "arg": "Kitchen"}
    assert h.device(msg)["confirmed"]
    assert "no room" in h.device(msg | {"arg": "../../etc"})["detail"]
    assert "can't do that" in h.device(msg | {"action": "goto"})["detail"]  # a vacuum has no "go to"
    assert calls == [("clean", "Kitchen")]


# ---- replies ----

def test_robot_and_phone_replies_fill_in():
    for o in replies.TEXT:
        for lang in ("en", "ar"):
            t = replies.reply(o, lang, device=PRETEND_VACUUM, place="Kitchen", places=("Kitchen",), action="clean",
                              app="WhatsApp", problem="stuck", kind="robot", file="alnoor-report")
            assert "{" not in t, (o, lang)
    assert replies.reply("robot_clean", "en", device=PRETEND_VACUUM, place="Kitchen") == \
        "Done. The robot vacuum is cleaning the kitchen."


# ---- the hub ----

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "hub", server.Hub())
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})
    monkeypatch.setattr(server.voice, "_cache", {})
    return TestClient(server.app)


def helper_ws(client):
    return client.websocket_connect(f"/helper/ws?token={server.hub.helper_token}")


def test_hub_open_whatsapp_on_the_phone(client):
    r = client.post("/api/command", json={"text": "on my phone WhatsApp message: meeting at 5", "person": "omar"}).json()
    assert r["status"] == "open_on_phone" and r["link"].startswith("https://wa.me/?text=meeting")
    assert "press send yourself" in r["reply"]["text"]
    assert any(e["type"] == "app.opened" and e["content"]["where"] == "phone" for e in server.hub.log.list())


def test_robot_moves_only_after_a_tap_and_stop_needs_none(client):
    with helper_ws(client) as ws:
        r = client.post("/api/command", json={"text": "clean the kitchen", "person": "layla"}).json()
        assert r["status"] == "needs_approval" and "Tap Approve" in r["reply"]["text"]
        assert not any(e["type"] == "device.command" for e in server.hub.log.list())
        s = client.post("/api/command", json={"text": "stop the vacuum", "person": "layla"}).json()
        assert s["status"] == "sent"  # no tap
        assert ws.receive_json()["action"] == "stop"
        a = client.post(f"/api/approve/{r['approval']}").json()
        assert a["status"] == "cancelled"  # stop came first: the waiting clean is dropped
        ws.send_json({"type": "result", "command_id": s["command"], "ok": True, "confirmed": True, "state": "idle",
                      "battery": 80, "detail": "ok"})
        client.get("/api/events")
    assert client.get(f"/api/status/{s['command']}").json()["reply"]["text"] == "Stopped."
    row = next(d for d in client.get("/api/devices").json() if d["id"] == PRETEND_VACUUM.id)
    assert row["state"] == "idle" and row["battery"] == 80


def test_approved_clean_goes_to_the_robot_with_the_room(client):
    with helper_ws(client) as ws:
        r = client.post("/api/command", json={"text": "نظف المطبخ", "person": "layla"}).json()
        a = client.post(f"/api/approve/{r['approval']}").json()
        m = ws.receive_json()
        assert m["action"] == "clean" and m["arg"] == "Kitchen"
        ws.send_json({"type": "result", "command_id": a["command"], "ok": True, "confirmed": True,
                      "state": "segment_cleaning", "detail": "ok"})
        client.get("/api/events")
    assert "المطبخ" in client.get(f"/api/status/{a['command']}").json()["reply"]["text"]


def test_stop_alone_stops_every_robot(client):
    with helper_ws(client) as ws:
        r = client.post("/api/command", json={"text": "stop", "person": "omar"}).json()
        got = {ws.receive_json()["device_id"], ws.receive_json()["device_id"]}
    assert r["status"] == "sent" and len(r["commands"]) == 2 and got == set(devices.PRETENDS)


def test_visitor_cant_move_robots_and_unknown_room_is_said(client):
    assert client.post("/api/command", json={"text": "clean the kitchen", "person": "visitor"}).json()["status"] == "refused"
    r = client.post("/api/command", json={"text": "clean the bathroom", "person": "layla"}).json()
    assert r["status"] == "not_found" and "bathroom" in r["reply"]["text"] and "Kitchen" in r["reply"]["text"]


def test_add_ros_robot_mac_only(client, monkeypatch):
    body = {"name": "Office robot", "room": "Office", "address": "192.168.1.50", "port": 9090, "roles": ["owner"],
            "spots": "Meeting room: 4, 2, 0\nDock: 0, 0"}
    assert client.post("/api/devices/add-ros", json=body | {"spots": "nonsense"}).status_code == 400
    assert client.post("/api/devices/add-ros", json=body | {"address": "1.2.3.4; rm -rf"}).status_code == 400
    assert client.post("/api/devices/add-ros", json=body).json()["status"] == "added"
    ids = [d.id for d in devices.current()]
    assert PRETEND_ROS.id not in ids  # a real ROS robot replaces the pretend one
    monkeypatch.setattr(server, "LOCAL_HOSTS", {"127.0.0.1"})
    assert client.post("/api/devices/add-ros", json=body).status_code == 403


def test_roborock_login_flow(client, monkeypatch):
    monkeypatch.setattr(server.roborock_vac, "request_code", lambda email: None)
    monkeypatch.setattr(server.roborock_vac, "login", lambda email, code, path: None)
    monkeypatch.setattr(server.roborock_vac, "list_vacuums",
                        lambda path: [{"duid": "d1", "label": "Roborock S8", "model": "roborock.vacuum.a51",
                                       "rooms": [(16, "Kitchen"), (17, "Bedroom")]}])
    assert client.post("/api/roborock/code", json={"email": "not-an-email"}).status_code == 400
    assert client.post("/api/roborock/code", json={"email": "owner@example.com"}).json()["status"] == "code_sent"
    vacs = client.post("/api/roborock/login", json={"code": "123456"}).json()
    assert vacs[0]["label"] == "Roborock S8" and "uid" not in vacs[0]
    client.post("/api/devices/add", json={"key": vacs[0]["key"], "name": "Roborock", "room": "Home", "roles": ["owner"]})
    dev = devices.by_id(vacs[0]["key"])
    assert dev.sub == "vacuum" and dict((s[0], s[1]) for s in dev.spots) == {"Kitchen": 16, "Bedroom": 17}
    assert PRETEND_VACUUM.id not in [d.id for d in devices.current()]
    assert not any("example.com" in json.dumps(e) for e in server.hub.log.list())  # the email isn't logged


def test_two_pretend_robots_stopping_at_once_both_stop(tmp_path):
    """Both stops write the same state file: neither may undo the other."""
    path = tmp_path / "r.json"
    ros_bot = PretendRobot(PRETEND_ROS.id, "ros", PRETEND_ROS.places, path, travel=60, wait=0.01, sleep=lambda s: None)
    vac = PretendRobot(PRETEND_VACUUM.id, "vacuum", PRETEND_VACUUM.places, path, wait=0.01, sleep=lambda s: None)
    ros_bot._change("goto", "Meeting room")
    vac._change("start", None)
    ts = [threading.Thread(target=r.do, args=("stop",)) for r in (ros_bot, vac) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert ros_bot.status()["state"] == "idle" and vac.status()["state"] == "idle"


def test_pretend_goto_stopped_midway_is_not_called_arrived(tmp_path):
    t = [0.0]
    path = tmp_path / "r.json"
    bot = PretendRobot(PRETEND_ROS.id, "ros", PRETEND_ROS.places, path, travel=3, wait=5,
                       sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0])
    other = PretendRobot(PRETEND_ROS.id, "ros", PRETEND_ROS.places, path, clock=lambda: t[0])
    real_sleep = bot.sleep

    def sleep_then_stop(s):
        real_sleep(s)
        if t[0] >= 1 and other.status()["state"] == "moving":
            other._change("stop", None)
    bot.sleep = sleep_then_stop
    r = bot.do("goto", "Meeting room")
    assert not r["confirmed"] and "Stopped before" in r["detail"]


def test_stopped_trip_says_so(client):
    with helper_ws(client) as ws:
        r = client.post("/api/command", json={"text": "robot go to reception", "person": "layla"}).json()
        a = client.post(f"/api/approve/{r['approval']}").json()
        ws.receive_json()
        ws.send_json({"type": "result", "command_id": a["command"], "ok": True, "confirmed": False, "state": "idle",
                      "detail": "Stopped before getting there"})
        client.get("/api/events")
    assert client.get(f"/api/status/{a['command']}").json()["reply"]["text"] == \
        "The office robot stopped before getting to the reception."


def test_stopped_trip_home_says_so(client):
    with helper_ws(client) as ws:
        r = client.post("/api/command", json={"text": "office robot go home", "person": "layla"}).json()
        a = client.post(f"/api/approve/{r['approval']}").json()
        assert ws.receive_json()["action"] == "dock"
        ws.send_json({"type": "result", "command_id": a["command"], "ok": True, "confirmed": False, "state": "idle",
                      "detail": "Stopped before getting there"})
        client.get("/api/events")
    assert client.get(f"/api/status/{a['command']}").json()["reply"]["text"] == \
        "The office robot stopped before getting to the dock."
