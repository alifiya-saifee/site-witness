"""Phase 2: the home-screen app, Tailscale, and files that come to the phone (one-time links, 5 minutes, 100 MB)."""
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from phone import join
from sitewitness import mac_map, server, tailnet
from sitewitness.records import BY_ID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "helper"))
import diwan_helper  # noqa: E402
from diwan_helper import Helper  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "hub", server.Hub())
    monkeypatch.setattr(server, "LOCAL_HOSTS", {"127.0.0.1"})  # this TestClient is a phone
    return TestClient(server.app)


def cmd(client, token, text, **kw):
    return client.post("/api/command", headers={"X-Session": token}, json={"text": text, **kw}).json()


# ---------------- the home-screen app ----------------

def test_manifest_icons_and_service_worker_are_served(client):
    m = client.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.headers["content-type"].startswith("application/manifest+json")
    data = m.json()
    assert data["display"] == "standalone" and data["start_url"] == "/"
    for i in data["icons"]:
        r = client.get(i["src"])
        assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert client.get("/apple-touch-icon.png").status_code == 200
    assert client.get("/icon-../../.env.png").status_code == 404
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
    page = client.get("/").text
    assert 'rel="manifest"' in page and "serviceWorker.register('/sw.js')" in page


def test_the_service_worker_never_keeps_api_answers_or_files():
    sw = (server.WEB / "sw.js").read_text()
    keep = json.loads(sw.split("const KEEP = ")[1].split(";")[0].replace("'", '"'))
    assert not any(k.startswith(("/api", "/helper")) for k in keep)
    assert "url.pathname.startsWith('/api/')" in sw and "url.pathname.startsWith('/helper/')" in sw


# ---------------- a file from Records or the shared folder, to the phone ----------------

def test_a_file_comes_to_the_phone_once(client):
    token = join(client, "layla")
    r = cmd(client, token, "open the Al Noor slides")
    assert r["status"] == "file" and r["name"] == BY_ID["alnoor-slides"].filename and r["reply"]["text"]
    assert str(server.ROOT) not in json.dumps(r)  # never a path
    h = {"X-Session": token}
    other = join(client, "layla")
    assert client.get(f"/api/file/{r['download']}", headers={"X-Session": other}).status_code == 403
    got = client.get(f"/api/file/{r['download']}", headers=h)
    assert got.status_code == 200 and got.content == BY_ID["alnoor-slides"].path.read_bytes()
    assert got.headers["content-type"] == "application/pdf" and "attachment" in got.headers["content-disposition"]
    assert client.get(f"/api/file/{r['download']}", headers=h).status_code == 410  # once
    log = json.dumps(server.hub.log.latest(30))
    assert "file.sent_to_phone" in log and str(server.ROOT) not in log


def test_a_link_dies_after_5_minutes(client):
    token = join(client, "layla")
    r = cmd(client, token, "open the Al Noor slides")
    server.hub.downloads[r["download"]]["at"] = time.time() - 301
    assert client.get(f"/api/file/{r['download']}", headers={"X-Session": token}).status_code == 410


def test_on_my_mac_still_opens_on_the_mac(client):
    token = join(client, "layla")
    assert cmd(client, token, "open the Al Noor slides on my mac")["status"] == "no_helper"
    assert cmd(client, token, "open the Al Noor slides", where="mac")["status"] == "no_helper"


def test_roles_still_apply_to_files_for_the_phone(client):
    token = join(client, "omar")
    assert cmd(client, token, "open the Al Noor signed report")["status"] == "refused"
    assert cmd(client, token, "x", choose="mac:aaaaaaaaaaaa")["status"] == "refused"  # whole-Mac files: owner only


# ---------------- a file from the whole Mac, to the phone ----------------

class FakeHelper:
    """Does what the real helper + upload do: the file lands in run/outbox and the hub's wait ends."""
    def __init__(self, data: bytes = b"%PDF cv", fail: str = ""):
        self.data, self.fail, self.sent = data, fail, []

    async def send_json(self, msg):
        self.sent.append(msg)
        u = server.hub.uploads[msg["request_id"]]
        if self.fail:
            u["future"].set_result(self.fail)
            return
        server.OUTBOX.mkdir(exist_ok=True)
        dest = server.OUTBOX / "abc123"
        dest.write_bytes(self.data)
        u["future"].set_result({"path": dest, "name": "CV 2026.pdf", "size": len(self.data)})


def test_a_whole_mac_file_comes_to_the_phone_after_a_check(client):
    token = join(client, "layla")
    server.hub.helper = FakeHelper()
    assert cmd(client, token, "x", choose="mac:aaaaaaaaaaaa")["status"] == "needs_check"
    assert server.hub.helper.sent == []  # nothing asked of the Mac before the check
    server.hub.sessions[server.token_hash(token)]["checked"] = time.time()
    r = cmd(client, token, "x", choose="mac:aaaaaaaaaaaa")
    assert r["status"] == "file" and r["name"] == "CV 2026.pdf"
    sent = server.hub.helper.sent[0]
    assert sent["type"] == "send_found" and sent["found_id"] == "aaaaaaaaaaaa" and "path" not in sent
    got = client.get(f"/api/file/{r['download']}", headers={"X-Session": token})
    assert got.content == b"%PDF cv"
    assert not (server.OUTBOX / "abc123").exists()  # the copy is deleted once the phone has it


def test_when_the_mac_refuses_the_phone_is_told(client):
    token = join(client, "layla")
    server.hub.sessions[server.token_hash(token)]["checked"] = time.time()
    server.hub.helper = FakeHelper(fail="That file is over 100 MB")
    r = cmd(client, token, "x", choose="mac:aaaaaaaaaaaa")
    assert r["status"] == "failed" and "100 MB" in r["steps"][-1]["t"]


def test_the_upload_door_is_local_one_time_and_capped(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "hub", server.Hub())
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})
    mac = TestClient(server.app)
    loop = asyncio.new_event_loop()
    try:
        fut = loop.create_future()
        server.hub.uploads["0123456789ab"] = {"token": "tok", "future": fut}
        h = {"Content-Type": "application/octet-stream", "X-Name": "..%2F..%2Fsecret%20plan.pdf"}
        assert mac.post("/helper/upload/0123456789ab?t=bad", content=b"x", headers=h).status_code == 403
        assert mac.post("/helper/upload/0123456789ab?t=tok", content=b"hello", headers=h).status_code == 200
        got = fut.result()
        assert got["name"] == "secret plan.pdf" and got["path"].read_bytes() == b"hello"  # no folders in the name
        assert oct(got["path"].stat().st_mode)[-3:] == "600"
        assert mac.post("/helper/upload/0123456789ab?t=tok", content=b"again", headers=h).status_code == 403  # once
        monkeypatch.setattr(server, "MAX_FILE", 10)
        fut2 = loop.create_future()
        server.hub.uploads["0123456789ac"] = {"token": "tok2", "future": fut2}
        assert mac.post("/helper/upload/0123456789ac?t=tok2", content=b"x" * 50, headers=h).status_code == 413
        assert fut2.result() == "That file is over 100 MB"
        assert list(server.OUTBOX.glob("*")) == [got["path"]]  # the too-big one was not kept
    finally:
        loop.close()
    monkeypatch.setattr(server, "LOCAL_HOSTS", {"127.0.0.1"})  # from a phone: refused
    assert TestClient(server.app).post("/helper/upload/0123456789ab?t=tok", content=b"x",
                                       headers={"Content-Type": "application/octet-stream"}).status_code == 403


def test_the_helper_sends_only_files_it_found(tmp_path, monkeypatch):
    home = tmp_path / "home"
    for rel in ("Documents/CV 2026.pdf", "Documents/.env", "Documents/big.pdf"):
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text("x")
    monkeypatch.setattr(mac_map, "HOME", home)
    monkeypatch.setattr(mac_map.hidden, "__defaults__", (home,))
    sent = []
    h = Helper(runner=lambda cmd, timeout=10: subprocess.CompletedProcess(cmd, 0, "", ""), plug=object(),
               app_map=mac_map.AppMap([]), send_up=lambda rid, tok, path: sent.append((rid, tok, path)))
    cv, env = home / "Documents/CV 2026.pdf", home / "Documents/.env"
    ok_id, env_id = h.found.add(cv), h.found.add(env)
    msg = {"type": "send_found", "request_id": "0123456789ab", "upload": "tok"}
    r = h.send_found(msg | {"found_id": ok_id})
    assert r["ok"] and sent == [("0123456789ab", "tok", cv)] and str(home) not in json.dumps(r)
    assert "Refused" in h.send_found(msg | {"found_id": ok_id})["detail"]       # each id once
    assert "Refused" in h.send_found(msg | {"found_id": env_id})["detail"]      # secrets never
    assert "Refused" in h.send_found(msg | {"found_id": h.found.add(cv), "path": "/etc/passwd"})["detail"]
    monkeypatch.setattr(diwan_helper, "MAX_SEND", 0)
    assert "100 MB" in h.send_found(msg | {"found_id": h.found.add(home / "Documents/big.pdf")})["detail"]


# ---------------- Tailscale ----------------

def fake_run(status: dict | None, cert_ok: bool = True, calls: list | None = None):
    def run(args, **kw):
        if calls is not None:
            calls.append(args)
        if args[1] == "status":
            return subprocess.CompletedProcess(args, 0, json.dumps(status or {}), "")
        if cert_ok:
            Path(args[3]).write_text("cert")
            Path(args[5]).write_text("key")
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 1, "", "HTTPS certificates are not enabled")
    return run


def test_tailscale_name_only_when_running():
    up = {"BackendState": "Running", "Self": {"DNSName": "alifiyas-mac.tail1234.ts.net."}}
    assert tailnet.name(fake_run(up), tool="ts") == "alifiyas-mac.tail1234.ts.net"
    assert tailnet.name(fake_run({"BackendState": "NeedsLogin"}), tool="ts") is None
    assert tailnet.name(fake_run({"BackendState": "Running", "Self": {"DNSName": "evil.example."}}), tool="ts") is None



def test_no_tailscale_means_wifi_only(monkeypatch):
    monkeypatch.setattr(tailnet, "cli", lambda: None)
    assert tailnet.name(fake_run({"BackendState": "Running"})) is None
    assert tailnet.cert("mac.tail1234.ts.net", Path("/nonexistent"), run=fake_run({})) is None


def test_tailscale_cert_made_once_and_kept_private(tmp_path):
    calls = []
    got = tailnet.cert("mac.tail1234.ts.net", tmp_path, run=fake_run({}, calls=calls), tool="ts")
    assert got and oct(got[1].stat().st_mode)[-3:] == "600"
    assert tailnet.cert("mac.tail1234.ts.net", tmp_path, run=fake_run({}, calls=calls), tool="ts") == got
    assert len(calls) == 1  # reused, not asked again
    assert tailnet.cert("other.tail1234.ts.net", tmp_path / "x", run=fake_run({}, cert_ok=False), tool="ts") is None


def test_the_tailscale_name_is_one_of_the_hubs_names(client, monkeypatch):
    name = "mac.tail1234.ts.net"
    assert client.get("/api/info", headers={"Host": f"{name}:8443"}).status_code == 403
    server.EXTRA_NAMES.add(name)
    assert client.get("/api/info", headers={"Host": f"{name}:8443"}).status_code == 200
