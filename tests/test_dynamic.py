"""A dynamic assistant: several steps from one sentence, memory, answers, questions about live state,
the live map of apps and files, and the learned-remote lamp. Groq is always faked here."""
import base64
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sitewitness import devices, mac_map, server, understand
from sitewitness.connectors.ir_blaster import IRBlaster, IRError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "helper"))
from diwan_helper import Helper  # noqa: E402


# ---------------- helpers ----------------

@pytest.fixture
def groq(monkeypatch):
    """Set what the fake Groq answers. write_reply is off unless a test sets it."""
    monkeypatch.setenv("GROQ_API_KEY", "test")
    box = {"answer": None, "menus": []}

    def fake_ask(sentence, the_menu, post=None):
        box["menus"].append(the_menu)
        return box["answer"]
    monkeypatch.setattr(understand, "ask", fake_ask)
    monkeypatch.setattr(understand, "write_reply", lambda lang, facts, names=(), post=None: box.get("reply"))
    monkeypatch.setattr(understand, "_chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no real Groq")))
    return box


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "hub", server.Hub())
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})
    monkeypatch.setattr(server.voice, "_cache", {})
    with TestClient(server.app) as c:  # one event loop for the whole test: plans run in the background
        yield c


def plan_until(c, pid, done=("done",), t=5.0):
    until = time.monotonic() + t
    while time.monotonic() < until:
        p = c.get(f"/api/plan/{pid}").json()
        if p["state"] in done:
            return p
        time.sleep(0.05)
    raise AssertionError(f"plan stuck: {p}")


def say(c, text, person="layla"):
    return c.post("/api/command", json={"text": text, "person": person}).json()


def connect_helper(c, apps=("Notes", "Safari")):
    ws = c.websocket_connect(f"/helper/ws?token={server.hub.helper_token}")
    ws.__enter__()
    ws.send_json({"type": "map", "apps": list(apps)})
    deadline = time.monotonic() + 2
    while set(apps) - server.hub.mac_apps and time.monotonic() < deadline:
        time.sleep(0.02)
    return ws


def done(ws, msg, **extra):
    ws.send_json({"type": "result", "command_id": msg["command_id"], "ok": True, "confirmed": True, "detail": "ok"} | extra)


# ---------------- several steps ----------------

def test_two_steps_run_in_order_with_one_reply(client, groq):
    groq["answer"] = {"steps": [{"action": "open_mac_app", "app": "Notes"},
                                {"action": "mac_volume", "op": "set", "level": 30}], "answer": ""}
    ws = connect_helper(client)
    r = say(client, "open notes and set the mac volume to 30")
    assert r["status"] == "plan"
    m1 = ws.receive_json()
    assert m1["type"] == "mac_app" and m1["name"] == "Notes" and "path" not in m1
    p = client.get(f"/api/plan/{r['plan']}").json()
    assert [s["state"] for s in p["steps"]] == ["running", "waiting"]  # step 2 waits for step 1 to finish
    done(ws, m1)
    m2 = ws.receive_json()
    assert m2 == {"type": "mac", "action": "set", "level": 30, "command_id": m2["command_id"]}
    done(ws, m2, after=30)
    p = plan_until(client, r["plan"])
    assert [s["state"] for s in p["steps"]] == ["done", "done"]
    assert p["reply"]["text"] == "Done. 2 steps finished."
    ws.__exit__(None, None, None)


def test_a_step_needing_a_tap_waits_and_the_rest_runs_after_approve(client, groq):
    groq["answer"] = {"steps": [{"action": "send_file", "file": "alnoor-report", "to": "Omar"},
                                {"action": "mac_volume", "op": "up"}]}
    ws = connect_helper(client)
    r = say(client, "send the al noor report to omar and turn the volume up")
    p = plan_until(client, r["plan"], done=("waiting",))
    assert [s["state"] for s in p["steps"]] == ["needs_approval", "waiting"]
    assert "Omar" in p["steps"][0]["question"] and "tap" in p["reply"]["text"]
    client.post(f"/api/approve/{p['steps'][0]['approval']}")
    m = ws.receive_json()
    assert m["type"] == "mac" and m["action"] == "up"
    done(ws, m, after=60)
    p = plan_until(client, r["plan"])
    assert [s["state"] for s in p["steps"]] == ["done", "done"]
    ws.__exit__(None, None, None)


def test_a_failed_step_stops_the_rest(client, groq):
    groq["answer"] = {"steps": [{"action": "mac_volume", "op": "up"}, {"action": "open_app", "app": "youtube", "target": "phone"}]}
    r = say(client, "turn up the mac and open youtube", person="visitor")
    p = plan_until(client, r["plan"])
    assert [s["state"] for s in p["steps"]] == ["failed", "skipped"]
    assert "Visitor may not" in p["steps"][0]["detail"] and p["reply"]["text"].startswith("I stopped at step 1")


def test_a_step_off_the_menu_is_skipped_not_run(client, groq):
    groq["answer"] = {"steps": [{"action": "open_app", "app": "youtube", "target": "phone"},
                                {"action": "run_shell", "cmd": "rm -rf /"}]}
    r = say(client, "open youtube and do something odd")
    p = plan_until(client, r["plan"])
    assert [s["state"] for s in p["steps"]] == ["phone", "skipped"]
    assert p["steps"][0]["link"] == "https://www.youtube.com/"


def test_stop_the_rest_cancels_the_waiting_tap(client, groq):
    groq["answer"] = {"steps": [{"action": "send_file", "file": "alnoor-report", "to": "Omar"},
                                {"action": "mac_volume", "op": "up"}]}
    r = say(client, "send it and turn it up")
    p = plan_until(client, r["plan"], done=("waiting",))
    aid = p["steps"][0]["approval"]
    p = client.post(f"/api/plan/{r['plan']}/cancel").json()
    assert p["state"] == "cancelled" and [s["state"] for s in p["steps"]] == ["skipped", "skipped"]
    assert client.post(f"/api/approve/{aid}").json()["status"] == "cancelled"


def test_at_most_five_steps(groq):
    raw = {"steps": [{"action": "mac_volume", "op": "up"}] * 7}
    steps, _, skipped = understand.to_plan(raw, "louder", [], "mac")
    assert len(steps) == 5 and skipped == 2


# ---------------- memory ----------------

def test_it_means_the_last_file_and_memory_is_sent_to_groq(client, groq):
    groq["answer"] = {"steps": [{"action": "open_file", "file": "alnoor-report"}]}
    r = say(client, "open the al noor report")
    assert r["status"] == "no_helper" or r["status"] == "sent"
    groq["answer"] = {"steps": [{"action": "send_file", "file": "alnoor-report", "to": "Omar"}]}
    r = say(client, "now send it to omar")
    assert r["status"] == "needs_approval" and "Al Noor" in r["question"]
    recent = groq["menus"][-1]["recent"]
    assert any("alnoor-report" in t and "open the al noor report" in t for t in recent)


def test_memory_is_forgotten_after_ten_minutes_and_on_request(client, groq):
    server.remember("mac", "open notes", "open Notes on the Mac: done")
    assert server.recent_for("mac")
    server.hub.memory["mac"][-1]["at"] -= 601
    assert server.recent_for("mac") == [] and "mac" not in server.hub.memory
    server.remember("mac", "open notes", "done")
    groq["answer"] = {"steps": [{"action": "forget"}]}
    r = say(client, "forget that")
    assert r["reply"]["text"].startswith("Okay, I've forgotten") and server.recent_for("mac") == []


def test_memory_is_never_written_to_disk(client, groq, tmp_path):
    server.remember("mac", "open the secret plan", "done")
    assert not list(Path(server.RUN_DIR).glob("memory*")) and "secret plan" not in str(server.hub.log.list())


# ---------------- answers ----------------

def test_a_question_gets_an_answer_and_nothing_is_done(client, groq):
    groq["answer"] = {"steps": [], "answer": "15% of 2,000 is 300."}
    r = say(client, "what's 15 percent of 2000")
    assert r["status"] == "answer" and r["reply"]["text"] == "15% of 2,000 is 300."
    assert "nothing was done" in r["steps"][-1]["t"]


def test_an_answer_that_pretends_it_did_something_is_dropped(client, groq):
    groq["answer"] = {"steps": [], "answer": "Done, I've ordered your pizza."}
    r = say(client, "order a pizza")
    assert r["status"] == "not_found" and "didn't understand" in r["reply"]["text"]
    assert understand.claims_done("I've opened Notes") and understand.claims_done("تم فتح الملف")
    assert not understand.claims_done("I can't order food, but I can open Maps on your Mac.")


def test_fresh_reply_is_fact_checked():
    facts = "step 1: set the Mac's volume to 30 -> done (Volume 20 → 30)"
    assert understand.fact_checked("Done, the Mac is at 30.", facts)
    assert not understand.fact_checked("Done, the Mac is at 40.", facts)
    assert not understand.fact_checked("I opened Safari and set it to 30.", facts, names=["Safari", "Notes"])
    assert understand.fact_checked("تم، الصوت الآن ٣٠.", facts)


def test_fresh_reply_is_used_when_groq_writes_one(client, groq):
    groq["answer"] = {"steps": [{"action": "open_app", "app": "youtube", "target": "phone"},
                                {"action": "open_app", "app": "maps", "target": "phone"}]}
    groq["reply"] = "YouTube and Google Maps are ready: tap to open them."
    p = plan_until(client, say(client, "open youtube and maps")["plan"])
    assert p["reply"]["text"] == "YouTube and Google Maps are ready: tap to open them."


# ---------------- questions about live state (read only) ----------------

def test_whats_the_mac_volume_only_reads(client, groq):
    groq["answer"] = {"steps": [{"action": "status", "what": "mac_volume"}]}
    ws = connect_helper(client)
    r = say(client, "what's the mac volume")
    m = ws.receive_json()
    assert m["type"] == "mac" and m["action"] == "get"
    done(ws, m, before=46, after=46, muted=False)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        s = client.get(f"/api/status/{r['command']}").json()
        if s["reply"]:
            break
        time.sleep(0.05)
    assert s["reply"]["text"] == "The Mac's volume is 46."
    ws.__exit__(None, None, None)


def test_helper_reads_the_volume_without_changing_it():
    calls = []

    def runner(cmd, timeout=10):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "output volume:46, input volume:50, output muted:false", "")
    h = Helper(runner=runner, plug=object(), app_map=mac_map.AppMap([]))
    r = h.mac({"type": "mac", "action": "get", "command_id": "0123456789ab"})
    assert r["confirmed"] and r["after"] == 46 and calls == [["osascript", "-e", "get volume settings"]]


def test_which_devices_and_websites(client, groq):
    groq["answer"] = {"steps": [{"action": "status", "what": "devices"}]}
    r = say(client, "which devices are on")
    assert r["status"] == "answer" and r["reply"]["text"].startswith("Devices:") and "not used yet" in r["reply"]["text"]
    groq["answer"] = {"steps": [{"action": "status", "what": "websites"}]}
    assert "no websites" in say(client, "what websites do I have")["reply"]["text"]


# ---------------- the live map: apps ----------------

def test_installing_and_deleting_an_app_updates_the_map_at_once(tmp_path):
    seen = []
    m = mac_map.AppMap([tmp_path], on_change=lambda a, r: seen.append((a, r))).watch()
    try:
        time.sleep(0.2)
        (tmp_path / "Fake Notes.app").mkdir()
        until = time.monotonic() + 5
        while not seen and time.monotonic() < until:
            time.sleep(0.05)
        assert seen[-1] == (["Fake Notes"], []) and m.has("Fake Notes")
        (tmp_path / "Fake Notes.app").rmdir()
        while len(seen) < 2 and time.monotonic() < until + 5:
            time.sleep(0.05)
        assert seen[-1] == ([], ["Fake Notes"]) and not m.has("Fake Notes")
    finally:
        m.stop()


def test_hub_follows_the_map_and_logs_installs(client):
    ws = connect_helper(client, apps=("Notes",))
    ws.send_json({"type": "map", "added": ["Spotify"], "removed": ["Notes"]})
    until = time.monotonic() + 2
    while "Spotify" not in server.hub.mac_apps and time.monotonic() < until:
        time.sleep(0.02)
    assert server.hub.mac_apps == {"Spotify"}
    types = [e["type"] for e in server.hub.log.list()]
    assert "map.added" in types and "map.removed" in types
    ws.__exit__(None, None, None)
    assert server.hub.mac_apps == set()  # helper gone: no map


def test_helper_opens_only_apps_in_its_map(tmp_path):
    (tmp_path / "Notes.app").mkdir()
    calls = []

    def runner(cmd, timeout=10):
        calls.append(cmd)
        if cmd[:2] == ["lsappinfo", "info"]:
            return subprocess.CompletedProcess(cmd, 0, '"LSDisplayName"="Notes"', "")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    h = Helper(runner=runner, plug=object(), wait=0.2, app_map=mac_map.AppMap([tmp_path]))
    h.screenshot = lambda: "proof"
    msg = {"type": "mac_app", "command_id": "0123456789ab", "name": "Notes"}
    assert h.open_mac_app(msg)["confirmed"] and calls[0] == ["open", "-a", "Notes"]
    calls.clear()
    assert "not an app installed" in h.open_mac_app(msg | {"name": "Terminal; rm -rf ~"})["detail"]
    assert "only by name" in h.open_mac_app(msg | {"path": "/bin/sh"})["detail"]
    assert calls == []


def test_unknown_mac_app_name_from_groq_is_thrown_away():
    assert understand.to_intent({"action": "open_mac_app", "app": "Spotify"}, "open spotify", [], "mac", ("Notes",)) is None
    i = understand.to_intent({"action": "open_mac_app", "app": "Notes"}, "open notes", [], "mac", ("Notes",))
    assert (i.action, i.mac_app) == ("mac_app", "Notes")
    i = understand.to_intent({"action": "open_mac_app", "app": "Mail"}, "open mail", [], "mac", ("Mail",))
    assert (i.action, i.app) == ("app", "mail")  # the built-in Mail keeps its own checks


# ---------------- the live map: files (whole Mac, Owner only) ----------------

def fake_home(tmp_path):
    home = tmp_path / "home"
    for rel in ("Documents/Invoices/march invoice.pdf", "Downloads/invoice old.pdf", "Library/Mail/invoice.pdf",
                ".hidden/invoice.pdf", "Documents/.env", "Documents/invoice-key.pem", "code/app/.git/HEAD",
                "code/app/invoice.pdf", "Documents/invoice data"):
        p = home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    return home


def test_find_files_never_shows_hidden_secret_or_code_files(tmp_path):
    home = fake_home(tmp_path)
    every = [str(p) for p in home.rglob("*") if p.is_file()]

    def runner(cmd, timeout=6):
        return subprocess.CompletedProcess(cmd, 0, "\n".join(every), "")
    names = sorted(p.name for p in mac_map.find_files("invoice", home=home, runner=runner))
    assert names == ["invoice old.pdf", "march invoice.pdf"]


def test_spotlight_query_is_plain_words_only(tmp_path):
    sent = []

    def runner(cmd, timeout=6):
        sent.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    mac_map.find_files('invoice" || kMDItemFSName == "*', home=tmp_path, runner=runner)
    assert all('||' not in c[-1] and c[:3] == ["mdfind", "-onlyin", str(tmp_path)] for c in sent)
    assert sent[0][-1] == 'kMDItemFSName == "*invoice*"cd && kMDItemFSName == "*kmditemfsname*"cd'


def test_owner_searches_the_mac_and_picks_one(client, groq):
    groq["answer"] = {"steps": [{"action": "search_files", "words": "march invoice", "mode": "find"}]}
    ws = connect_helper(client)
    import threading
    out = {}
    t = threading.Thread(target=lambda: out.update(r=say(client, "find my march invoice")))
    t.start()
    m = ws.receive_json()
    assert m["type"] == "find" and m["words"] == "march invoice"
    ws.send_json({"type": "found", "request_id": m["request_id"],
                  "items": [{"id": "aaaaaaaaaaaa", "name": "march invoice.pdf", "folder": "Documents › Invoices"},
                            {"id": "bbbbbbbbbbbb", "name": "invoice old.pdf", "folder": "Downloads"}]})
    t.join(5)
    r = out["r"]
    assert r["status"] == "choose" and r["options"][0] == {"id": "mac:aaaaaaaaaaaa", "title": "march invoice.pdf",
                                                           "snippet": "Documents › Invoices"}
    r = client.post("/api/command", json={"text": "find my march invoice", "person": "layla", "choose": "mac:aaaaaaaaaaaa"}).json()
    m = ws.receive_json()
    assert m == {"type": "open_found", "found_id": "aaaaaaaaaaaa", "command_id": m["command_id"]}
    ws.__exit__(None, None, None)


def test_broker_and_visitor_never_search_the_whole_mac(client, groq):
    groq["answer"] = {"steps": [{"action": "search_files", "words": "invoice", "mode": "find"}]}
    ws = connect_helper(client)
    for who in ("omar", "visitor"):
        r = say(client, "find invoice", person=who)
        assert r["status"] in ("not_found", "refused")
    assert not server.hub.finds and all(e["content"].get("mode") != "mac" for e in server.hub.log.list())
    r = client.post("/api/command", json={"text": "x", "person": "omar", "choose": "mac:aaaaaaaaaaaa"}).json()
    assert r["status"] == "refused"
    ws.__exit__(None, None, None)


def test_helper_opens_only_a_file_it_just_found(tmp_path, monkeypatch):
    home = fake_home(tmp_path)
    monkeypatch.setattr(mac_map, "HOME", home)
    monkeypatch.setattr(mac_map.hidden, "__defaults__", (home,))
    calls = []

    def runner(cmd, timeout=10):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    target = home / "Documents/Invoices/march invoice.pdf"
    h = Helper(runner=runner, plug=object(), wait=0.1, app_map=mac_map.AppMap([]), find=lambda words: [target])
    h.screenshot = lambda: None
    items = h.find_files({"type": "find", "request_id": "0123456789ab", "words": "march"})["items"]
    assert items[0]["name"] == "march invoice.pdf" and "path" not in items[0] and str(home) not in str(items)
    msg = {"type": "open_found", "command_id": "0123456789ab", "found_id": items[0]["id"]}
    assert h.open_found(msg)["ok"] and ["open", str(target)] in calls
    assert "Refused" in h.open_found(msg)["detail"]  # each id works once
    assert "Refused" in h.open_found(msg | {"found_id": "ffffffffffff"})["detail"]
    assert "Refused" in h.open_found(msg | {"path": "/etc/passwd"})["detail"]


# ---------------- the shared folder follows file changes at once ----------------

def test_watcher_sees_a_new_file_in_a_subfolder(tmp_path):
    (tmp_path / "sub").mkdir()
    hits = []
    w = mac_map.Watcher([tmp_path], lambda: hits.append(1), recursive=True, settle=0.1).start()
    try:
        time.sleep(0.2)
        (tmp_path / "sub" / "new.txt").write_text("hello")
        until = time.monotonic() + 5
        while not hits and time.monotonic() < until:
            time.sleep(0.05)
        assert hits
    finally:
        w.stop()


# ---------------- the lamp with an infrared remote ----------------

class FakeBroadlink:
    def __init__(self):
        self.sent, self.learning, self.polls = [], False, 0

    def enter_learning(self):
        self.learning = True

    def check_data(self):
        self.polls += 1
        if self.polls < 2:
            raise OSError("nothing yet")
        return b"\x26\x00\x10\x00power"

    def send_data(self, raw):
        self.sent.append(raw)


def test_blaster_learns_and_plays_back_a_button():
    fake = FakeBroadlink()
    b = IRBlaster("10.0.0.9", device=fake)
    code = b.learn(wait=2, poll=0.01, sleep=lambda s: None)
    assert base64.b64decode(code) == b"\x26\x00\x10\x00power"
    b.send(code)
    assert fake.sent == [b"\x26\x00\x10\x00power"]
    with pytest.raises(IRError):
        b.send("not base64!!")


def test_add_a_lamp_teach_buttons_and_press_them(client, groq, monkeypatch):
    fake = FakeBroadlink()
    monkeypatch.setattr(server, "blaster_for", lambda dev: IRBlaster(dev.address, device=fake))
    monkeypatch.setattr(IRBlaster, "learn", lambda self, **k: base64.b64encode(b"power-code").decode())
    r = client.post("/api/devices/add-ir", json={"name": "Lamp", "room": "Office", "address": "10.0.0.9",
                                                 "roles": ["owner", "broker"]}).json()
    dev_id = r["device"]
    assert client.post(f"/api/devices/{dev_id}/learn", json={"button": "toggle"}).json()["buttons"] == ["toggle"]
    assert client.post(f"/api/devices/{dev_id}/learn", json={"button": "rm -rf"}).status_code == 400
    dev = devices.by_id(dev_id)
    assert dev.kind == "ir" and dev.actions == ("toggle",)
    # "turn on the lamp" with only a power button: it presses power
    ws = connect_helper(client)
    r = say(client, "turn on the lamp", person="omar")
    m = ws.receive_json()
    assert m["type"] == "device" and m["device_id"] == dev_id and m["action"] == "toggle"
    ws.__exit__(None, None, None)


def test_helper_presses_only_taught_buttons():
    dev = devices.Device("ir-1", "the lamp", "المصباح", "Office", "ir", ("lamp",), ("owner",), address="10.0.0.9",
                         buttons=(("on", base64.b64encode(b"on-code").decode()),))
    fake = FakeBroadlink()
    h = Helper(runner=lambda c, timeout=10: subprocess.CompletedProcess(c, 1, "", ""), plug=object(), settle=0,
               device_list=lambda: [dev], app_map=mac_map.AppMap([]), ir_for=lambda d: IRBlaster(d.address, device=fake))
    h.photo = lambda: None
    msg = {"type": "device", "command_id": "0123456789ab", "device_id": "ir-1"}
    r = h.device(msg | {"action": "on"})
    assert r["ok"] and not r["confirmed"] and "can't report back" in r["detail"] and fake.sent == [b"on-code"]
    assert "can't do that" in h.device(msg | {"action": "off"})["detail"] and len(fake.sent) == 1


# ---------------- Groq's free plan: a busy model hands over to the next ----------------

def test_a_busy_model_hands_over_to_the_next(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    tried = []

    class R:
        def __init__(self, code, content=None):
            self.status_code, self._c = code, content
            self.text = "Rate limit reached for model" if code == 429 else ""

        def json(self):
            return {"choices": [{"message": {"content": self._c}}]}

    def post(body):
        tried.append(body["model"])
        return R(429) if body["model"] == "openai/gpt-oss-120b" else R(200, '{"steps":[],"answer":"300"}')
    assert understand.ask("what's 15% of 2000", {}, post) == {"steps": [], "answer": "300"}
    assert tried == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]


def test_replies_use_the_small_model(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    tried = []

    class R:
        status_code, text = 200, ""

        def json(self):
            return {"choices": [{"message": {"content": '{"reply":"Volume is 30."}'}}]}
    assert understand.write_reply("en", ["volume -> done (Volume 20 → 30)"], post=lambda b: tried.append(b["model"]) or R()) \
        == "Volume is 30."
    assert tried == ["openai/gpt-oss-20b"]


def test_an_answer_wins_over_ask_back(groq):
    steps, answer, _ = understand.to_plan({"steps": [{"action": "unclear", "question": "Which?"}], "answer": "It's 300."},
                                          "what's 15% of 2000", [], "mac")
    assert steps == [] and answer == "It's 300."


def test_word_match_backup_never_searches_the_mac_for_a_plain_sentence(client, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    ws = connect_helper(client)
    r = say(client, "what's 15 percent of 2000")
    assert r["status"] == "not_found" and not server.hub.finds
    ws.__exit__(None, None, None)


def test_after_a_busy_minute_the_main_model_is_used_again(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    tried, busy = [], [True]

    class R:
        def __init__(self, code):
            self.status_code, self.text = code, "Rate limit reached for model"

        def json(self):
            return {"choices": [{"message": {"content": '{"steps":[],"answer":"ok"}'}}]}

    def post(body):
        tried.append(body["model"])
        return R(429 if busy[0] and body["model"] == "openai/gpt-oss-120b" else 200)
    understand.ask("one", {}, post)
    busy[0] = False
    understand.ask("two", {}, post)
    assert tried == ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "openai/gpt-oss-120b"]


def test_a_reply_saying_sent_while_a_tap_waits_is_replaced(client, groq):
    groq["answer"] = {"steps": [{"action": "send_file", "file": "marina-quote", "to": "Omar"},
                                {"action": "open_app", "app": "youtube", "target": "phone"}]}
    groq["reply"] = "Sent the Marina Court quote to Omar."
    p = plan_until(client, say(client, "send the marina quote to omar and open youtube")["plan"], done=("waiting",))
    assert p["reply"]["text"].startswith("The first step is waiting for your tap on Approve")
