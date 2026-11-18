"""Phase 3: nothing static. Records are the owner's shared folders (several, each with its own roles), "send" ends
in a Mail draft or the phone's share sheet (a person presses send), and pretend devices appear only with SW_DEMO=1."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phone import join
from sitewitness import devices, library, server, understand
from sitewitness.records import active

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "helper"))
import diwan_helper  # noqa: E402
from diwan_helper import Helper  # noqa: E402


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.delenv("SW_DEMO", raising=False)  # a normal run
    h = tmp_path / "home"
    team, private = h / "Team files", h / "Owner only"
    team.mkdir(parents=True)
    private.mkdir(parents=True)
    (team / "lift-note.txt").write_text("Lift note\nThe lift in tower B needs a new door sensor.")
    (team / "balcony.md").write_text("# Balcony report\nThe balcony on floor 7 has a crack.")
    (private / "salaries.txt").write_text("Salaries 2026\nPrivate numbers about the lift team.")
    monkeypatch.setattr(library.Path, "home", staticmethod(lambda: h))
    monkeypatch.setattr(server, "hub", server.Hub())
    return h


@pytest.fixture
def mac(monkeypatch, home):
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})
    c = TestClient(server.app)
    assert c.post("/api/folder", json={"folder": str(home / "Team files"), "roles": ["owner", "broker"]}).status_code == 200
    assert c.post("/api/folder", json={"folder": str(home / "Owner only"), "roles": ["owner"]}).status_code == 200
    return c


def as_phone(monkeypatch):
    monkeypatch.setattr(server, "LOCAL_HOSTS", {"127.0.0.1"})


def as_mac(monkeypatch):
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})


def cmd(c, text, person="layla", headers=None, **kw):
    return c.post("/api/command", json={"text": text, "person": person, **kw}, headers=headers).json()


# ---------------- no demo parts in a normal run ----------------

def test_no_sample_records_or_pretend_devices_without_demo(monkeypatch, home):
    assert active() == () and devices.current() == ()
    assert understand.menu([], "mac")["files"] == []
    monkeypatch.setenv("SW_DEMO", "1")
    assert len(active()) == 4 and {d.id for d in devices.current()} >= {"room-lamp", "robot-vacuum-pretend"}


def test_a_sample_record_cant_be_reached_without_demo(mac):
    r = cmd(mac, "open the Al Noor slides")
    assert r["status"] in ("not_found", "choose") and "al-noor" not in json.dumps(r)
    r = cmd(mac, "x", choose="alnoor-slides")
    assert r["status"] != "no_helper" and "al-noor" not in json.dumps(r)
    assert mac.get("/api/devices").json() == []
    assert mac.get("/api/info").json()["demo"] is False


# ---------------- several shared folders, each with its own roles ----------------

def test_each_folder_has_its_own_roles(mac, monkeypatch):
    info = mac.get("/api/folder").json()
    assert [(f["name"], f["files"], f["roles"]) for f in info["folders"]] == [
        ("Team files", 2, ["owner", "broker"]), ("Owner only", 1, ["owner"])]
    owner = cmd(mac, "find lift")
    assert {o["title"] for o in owner["options"]} == {"Lift note", "Salaries 2026"}
    broker = cmd(mac, "find lift", person="omar")
    assert broker["status"] == "choose" and [o["title"] for o in broker["options"]] == ["Lift note"]
    assert "Salaries" not in json.dumps(broker)
    salaries = next(o["id"] for o in owner["options"] if o["title"] == "Salaries 2026")
    r = cmd(mac, "find lift", person="omar", choose=salaries)
    assert r["status"] == "refused"  # even with the id of a file from the owner-only folder
    assert cmd(mac, "find lift", person="visitor")["status"] == "refused"


def test_changing_who_and_stopping_one_folder(mac, home):
    mac.post("/api/folder", json={"folder": str(home / "Owner only"), "roles": ["owner", "broker"]})
    assert "Salaries" in json.dumps(cmd(mac, "find salaries", person="omar"))
    mac.delete("/api/folder", params={"folder": str(home / "Owner only")})
    assert [f["name"] for f in mac.get("/api/folder").json()["folders"]] == ["Team files"]
    assert "Salaries" not in json.dumps(cmd(mac, "find salaries"))
    assert (home / "Owner only" / "salaries.txt").exists()  # the files themselves are never touched


def test_the_old_one_folder_setting_still_reads(home):
    library.SETTINGS.write_text(json.dumps({"folder": str(home / "Team files"), "roles": ["owner"]}))
    assert library.folders() == [{"folder": str(home / "Team files"), "roles": ["owner"]}]


# ---------------- send: approve, then a Mail draft (Mac) or the share sheet (phone) ----------------

class FakeHelper:
    def __init__(self):
        self.sent = []

    async def send_json(self, msg):
        self.sent.append(msg)


def test_send_from_a_shared_folder_makes_a_mail_draft_on_the_mac(mac):
    server.hub.helper = FakeHelper()
    r = cmd(mac, "send the lift note to Omar")
    assert r["status"] == "needs_approval" and "Lift note" in r["question"] and "Omar" in r["question"]
    assert server.hub.helper.sent == []  # nothing before the tap
    a = mac.post(f"/api/approve/{r['approval']}").json()
    assert a["status"] == "approved" and a["then"] == "sent" and "omar@example.com" in a["steps"][-1]["t"]
    m = server.hub.helper.sent[0]
    assert m["type"] == "mail_draft" and m["to_email"] == "omar@example.com" and m["attach_name"] == "lift-note.txt"
    assert m["file_id"].startswith("lib-") and str(Path.home()) not in json.dumps(m)
    # the helper fetches the file once with its token, like opening one
    got = mac.get(f"/helper/file/{m['file_id']}", params={"t": m["token"]})
    assert got.status_code == 200 and b"door sensor" in got.content
    assert mac.post(f"/api/approve/{r['approval']}").json()["repeat"] is True
    assert len(server.hub.helper.sent) == 1  # a second tap makes no second draft


def test_a_broker_cannot_send_from_the_owner_folder(mac):
    assert cmd(mac, "send the salaries to Layla", person="omar")["status"] != "needs_approval"


def test_send_approved_on_the_phone_comes_to_its_share_sheet(mac, monkeypatch):
    as_phone(monkeypatch)
    token = join(mac, "omar")
    h = {"X-Session": token}
    r = cmd(mac, "send the lift note to Layla", headers=h)
    assert r["status"] == "needs_approval"
    assert mac.post(f"/api/approve/{r['approval']}", headers=h).json()["detail"] == "needs_check"
    server.hub.sessions[server.token_hash(token)]["checked"] = time.time()
    a = mac.post(f"/api/approve/{r['approval']}", headers=h).json()
    assert a["status"] == "approved" and a["then"] == "file" and a["name"] == "lift-note.txt"
    assert "Share" in a["reply"]["text"] and "Layla" in a["reply"]["text"]
    got = mac.get(f"/api/file/{a['download']}", headers=h)
    assert b"door sensor" in got.content


# ---------------- the helper's Mail draft ----------------

def test_the_mail_draft_is_only_shown_never_sent(tmp_path):
    calls = []

    def runner(cmd, timeout=10):
        calls.append(cmd)
        out = '"LSDisplayName"="Mail"' if cmd[0] == "lsappinfo" else ""
        return subprocess.CompletedProcess(cmd, 0, out, "")
    h = Helper(runner=runner, plug=object(), opened_dir=tmp_path, wait=0.1, fetch=lambda fid, tok: b"%PDF-1.4 x")
    h.screenshot = lambda: None
    msg = {"type": "mail_draft", "command_id": "0123456789ab", "file_id": "lib-3", "filename": "lib-3.pdf",
           "token": "t1", "attach_name": "../Q3 report.pdf", "subject": "Q3 report\ninjected", "to_email": "omar@example.com",
           "to_name": 'Omar" & do shell script "x'}
    r = h.mail_draft(msg)
    assert r["ok"] and r["confirmed"] and "Nothing was sent" in r["detail"]
    osa = next(c for c in calls if c[0] == "osascript")
    assert osa[2] == diwan_helper.MAIL_SCRIPT and "send" not in diwan_helper.MAIL_SCRIPT.replace("sent", "")
    path, subject, email, name = osa[3:]
    assert Path(path).name == "Q3 report.pdf" and Path(path).read_bytes() == b"%PDF-1.4 x"
    assert subject == "Q3 report injected" and email == "omar@example.com" and '"' not in name
    assert "Refused" in h.mail_draft(msg)["detail"]  # the token works once
    r = h.mail_draft(msg | {"token": "t2", "to_email": "a@b.c\" , evil@x.y"})
    assert r["ok"] and next(c for c in reversed(calls) if c[0] == "osascript")[5] == ""  # a bad address is dropped
    assert "Refused" in h.mail_draft(msg | {"token": "t3", "type": "open_file"})["detail"]
