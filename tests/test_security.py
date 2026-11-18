"""Phase 1 security: a phone is its person, other websites can't drive the hub, and owner-level actions from a
phone need a fresh check (Face ID passkey, or a tap on the Mac)."""
import base64
import hashlib
import json
import struct
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from phone import join
from sitewitness import passkeys, people, server


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(server, "hub", server.Hub())
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})
    return TestClient(server.app)


@pytest.fixture
def phone(monkeypatch, mac):
    """Same TestClient address as the Mac, so once `as_phone()` runs, it isn't local any more."""
    return TestClient(server.app, headers={"user-agent": "Mozilla/5.0 (iPhone)"})


def as_phone(monkeypatch):
    monkeypatch.setattr(server, "LOCAL_HOSTS", {"127.0.0.1"})


def as_mac(monkeypatch):
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})


# ---------------- a phone is its person ----------------

def test_a_phone_waits_for_allow_then_is_its_person(mac, phone, monkeypatch):
    as_phone(monkeypatch)
    token = phone.post("/api/pair", json={"code": server.hub.pair_code}).json()["session"]
    h = {"X-Session": token}
    assert phone.get("/api/info", headers=h).json()["waiting"] is True
    assert phone.post("/api/command", headers=h, json={"text": "open the Al Noor slides"}).status_code == 403
    as_mac(monkeypatch)
    sid = mac.get("/api/sessions").json()[0]["id"]
    assert mac.post(f"/api/sessions/{sid}/allow", json={"person": "nobody"}).status_code == 400
    assert mac.post(f"/api/sessions/{sid}/allow", json={"person": "omar"}).json()["status"] == "allowed"
    as_phone(monkeypatch)
    info = phone.get("/api/info", headers=h).json()
    assert info["paired"] and info["me"] == "omar" and [p["id"] for p in info["people"]] == ["omar"]
    # it says it is Layla (the owner); the hub ignores that: Omar may not open the signed report
    r = phone.post("/api/command", headers=h, json={"text": "open the Al Noor signed report", "person": "layla"}).json()
    assert r["status"] == "refused" and any("Omar" in s["t"] for s in r["steps"])


def test_only_the_mac_can_allow(mac, phone, monkeypatch):
    as_phone(monkeypatch)
    token = join(phone, "omar")
    other = phone.post("/api/pair", json={"code": server.hub.pair_code}).json()["session"]
    sid = server.session_id(other)
    r = phone.post(f"/api/sessions/{sid}/allow", headers={"X-Session": token}, json={"person": "layla"})
    assert r.status_code == 403


def test_removing_a_person_logs_their_phone_out(mac, phone, monkeypatch):
    as_phone(monkeypatch)
    token = join(phone, "omar")
    assert phone.get("/api/events", headers={"X-Session": token}).status_code == 200
    as_mac(monkeypatch)
    assert mac.delete("/api/people/omar").json()["phones"] == 1
    as_phone(monkeypatch)
    assert phone.get("/api/events", headers={"X-Session": token}).status_code == 401


def test_sessions_survive_a_restart_hashed_and_expire(tmp_path, mac, phone, monkeypatch):
    f = tmp_path / "sessions.json"
    server.hub.sessions_file = f
    as_phone(monkeypatch)
    token = join(phone, "omar")
    server.save_sessions()
    assert token not in f.read_text() and server.token_hash(token) in f.read_text()
    assert oct(f.stat().st_mode)[-3:] == "600"
    monkeypatch.setattr(server, "hub", server.Hub(sessions_file=f))  # the hub restarts
    assert phone.get("/api/events", headers={"X-Session": token}).status_code == 200
    server.hub.sessions[server.token_hash(token)]["created"] = time.time() - 31 * 86400
    assert phone.get("/api/events", headers={"X-Session": token}).status_code == 401


def test_the_code_is_new_each_start_and_never_from_settings(monkeypatch):
    monkeypatch.setenv("SW_PAIR_CODE", "123456")
    codes = {server.Hub().pair_code for _ in range(5)}
    assert "123456" not in codes or len(codes) > 1


def test_first_run_sets_up_the_owner(mac):
    people.PEOPLE.clear()
    info = mac.get("/api/info").json()
    assert info["setup"] is True and info["people"] == []
    assert mac.post("/api/command", json={"text": "open the Al Noor slides"}).status_code == 409
    assert mac.post("/api/setup", json={"name": ""}).status_code == 400
    pid = mac.post("/api/setup", json={"name": "Layla Mansour", "email": "layla@example.com"}).json()["id"]
    assert people.PEOPLE[pid]["role"] == "owner" and json.loads(people.FILE.read_text())["people"][pid]
    assert mac.post("/api/setup", json={"name": "Someone else"}).status_code == 409
    assert mac.post("/api/people", json={"name": "Omar Khan", "role": "broker"}).status_code == 200
    assert mac.post("/api/people", json={"name": "X", "role": "king"}).status_code == 400
    assert mac.delete(f"/api/people/{pid}").status_code == 400  # keep at least one owner


# ---------------- other websites and wrong addresses ----------------

def test_other_websites_cannot_post_to_the_hub(mac):
    body = {"text": "open the Al Noor slides"}
    assert mac.post("/api/command", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert mac.post("/api/command", json=body, headers={"Origin": "http://localhost:3000", "Host": "localhost:8040"}).status_code == 403
    assert mac.post("/api/command", json=body, headers={"Origin": "null"}).status_code == 403
    assert mac.post("/api/command", json=body, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert mac.post("/api/sessions/reset", content="x", headers={"Content-Type": "text/plain"}).status_code == 415
    assert mac.post("/api/command", content=json.dumps(body),
                    headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 415
    # the hub's own page is fine
    ok = mac.post("/api/command", json=body, headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"})
    assert ok.status_code == 200
    assert any(e["type"] == "request.refused" for e in server.hub.log.latest(30))


def test_a_wrong_host_is_refused(mac):
    """DNS rebinding: evil.example points at 127.0.0.1, but the browser still sends Host: evil.example."""
    assert mac.get("/api/info", headers={"Host": "evil.example:8040"}).status_code == 403
    assert mac.get("/", headers={"Host": "evil.example"}).status_code == 403
    assert mac.get("/api/info", headers={"Host": "localhost:8040"}).status_code == 200


def test_page_headers(mac):
    r = mac.get("/")
    csp = r.headers["content-security-policy"]
    html = r.text
    script = html.split("<script>")[1].split("</script>")[0]
    want = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"'sha256-{want}'" in csp and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert "frame-ancestors 'none'" in csp and r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert ' onclick="' not in html and ' onload="' not in html  # inline handlers would be blocked


def test_too_many_commands_from_one_phone(mac, phone, monkeypatch):
    as_phone(monkeypatch)
    h = {"X-Session": join(phone, "visitor")}
    codes = [phone.post("/api/command", headers=h, json={"text": "what time is it"}).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30 and codes[30] == 429


# ---------------- fresh checks: approvals and whole-Mac files ----------------

def test_approvals_only_by_the_phone_that_asked_after_a_check(mac, phone, monkeypatch):
    as_phone(monkeypatch)
    mine, other = join(phone, "layla"), join(phone, "layla")
    r = phone.post("/api/command", headers={"X-Session": mine}, json={"text": "send the Al Noor slides to Omar"}).json()
    aid = r["approval"]
    assert phone.post(f"/api/approve/{aid}", headers={"X-Session": other}).status_code == 403
    r = phone.post(f"/api/approve/{aid}", headers={"X-Session": mine})
    assert r.status_code == 403 and r.json()["detail"] == "needs_check"
    # IP address: no passkeys, so confirm on the Mac
    start = phone.post("/api/check/start", headers={"X-Session": mine}).json()
    assert start["how"] == "mac"
    as_mac(monkeypatch)
    assert mac.get("/api/checks").json()[0]["id"] == start["id"]
    assert mac.post(f"/api/checks/{start['id']}/allow").json()["checked"]
    assert mac.post(f"/api/checks/{start['id']}/allow").status_code == 404  # one use
    as_phone(monkeypatch)
    assert phone.get("/api/info", headers={"X-Session": mine}).json()["checked"] is True
    assert phone.post(f"/api/approve/{aid}", headers={"X-Session": mine}).json()["status"] == "approved"
    server.hub.sessions[server.token_hash(mine)]["checked"] = time.time() - 301  # 5 minutes later
    assert phone.get("/api/info", headers={"X-Session": mine}).json()["checked"] is False


def test_the_mac_can_always_approve(mac, phone, monkeypatch):
    as_phone(monkeypatch)
    token = join(phone, "layla")
    aid = phone.post("/api/command", headers={"X-Session": token}, json={"text": "send the Al Noor slides to Omar"}).json()["approval"]
    as_mac(monkeypatch)
    assert mac.post(f"/api/approve/{aid}").json()["status"] == "approved"


def test_a_whole_mac_file_from_a_phone_needs_a_check(mac, phone, monkeypatch):
    as_phone(monkeypatch)
    h = {"X-Session": join(phone, "layla")}
    r = phone.post("/api/command", headers=h, json={"text": "x", "choose": "mac:aaaaaaaaaaaa"}).json()
    assert r["status"] == "needs_check" and r["reply"]["text"]
    server.hub.sessions[server.token_hash(h["X-Session"])]["checked"] = time.time()
    r = phone.post("/api/command", headers=h, json={"text": "x", "choose": "mac:aaaaaaaaaaaa"}).json()
    assert r["status"] != "needs_check"


def test_the_mac_cannot_be_checked(mac):
    assert mac.post("/api/check/start").status_code == 400


# ---------------- passkeys (a pretend authenticator with a real key pair) ----------------

def cbor(v) -> bytes:
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        for info, size in ((24, 1), (25, 2), (26, 4)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | info]) + n.to_bytes(size, "big")
        raise ValueError
    if isinstance(v, int):
        return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, bytes):
        return head(2, len(v)) + v
    if isinstance(v, str):
        return head(3, len(v.encode())) + v.encode()
    if isinstance(v, dict):
        return head(5, len(v)) + b"".join(cbor(k) + cbor(x) for k, x in v.items())
    raise TypeError


class Authenticator:
    def __init__(self, rp: str):
        self.rp, self.key, self.count, self.cid = rp, ec.generate_private_key(ec.SECP256R1()), 0, b"cred-123456"

    def _ad(self, flags: int, extra: bytes = b"") -> bytes:
        self.count += 1
        return hashlib.sha256(self.rp.encode()).digest() + bytes([flags]) + struct.pack(">I", self.count) + extra

    def create(self, challenge: str, origin: str) -> dict:
        n = self.key.public_key().public_numbers()
        cose = cbor({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})
        ad = self._ad(0x45, b"\0" * 16 + len(self.cid).to_bytes(2, "big") + self.cid + cose)
        cd = json.dumps({"type": "webauthn.create", "challenge": challenge, "origin": origin}).encode()
        return {"kind": "create", "challenge": challenge, "clientDataJSON": passkeys.b64u(cd),
                "attestationObject": passkeys.b64u(cbor({"fmt": "none", "attStmt": {}, "authData": ad}))}

    def get(self, challenge: str, origin: str, flags: int = 0x05) -> dict:
        ad = self._ad(flags)
        cd = json.dumps({"type": "webauthn.get", "challenge": challenge, "origin": origin}).encode()
        sig = self.key.sign(ad + hashlib.sha256(cd).digest(), ec.ECDSA(hashes.SHA256()))
        return {"kind": "get", "challenge": challenge, "id": passkeys.b64u(self.cid), "clientDataJSON": passkeys.b64u(cd),
                "authenticatorData": passkeys.b64u(ad), "signature": passkeys.b64u(sig)}


def test_face_id_passkey_register_then_check(monkeypatch, tmp_path):
    rp, origin = "hub.example.ts.net", "https://hub.example.ts.net:8443"
    monkeypatch.setenv("SW_HOSTS", rp)
    monkeypatch.setattr(server, "hub", server.Hub(passkeys_file=tmp_path / "passkeys.json"))
    as_phone(monkeypatch)
    phone = TestClient(server.app, base_url=origin)
    token = join(phone, "layla")
    h = {"X-Session": token}
    auth = Authenticator(rp)
    start = phone.post("/api/check/start", headers=h).json()
    assert start["how"] == "register" and start["rp"] == rp
    assert phone.post("/api/check/passkey", headers=h, json=auth.create(start["challenge"], origin)).json()["checked"]
    assert "public" in (tmp_path / "passkeys.json").read_text()
    server.hub.sessions[server.token_hash(token)]["checked"] = 0
    start = phone.post("/api/check/start", headers=h).json()
    assert start["how"] == "passkey" and start["ids"] == [passkeys.b64u(auth.cid)]
    ans = auth.get(start["challenge"], origin)
    assert phone.post("/api/check/passkey", headers=h, json=ans).json()["checked"]
    assert phone.post("/api/check/passkey", headers=h, json=ans).status_code == 403  # a challenge works once
    # a wrong site, no Face ID, or a forged signature all fail
    for bad in (auth.get(phone.post("/api/check/start", headers=h).json()["challenge"], "https://evil.example"),
                auth.get(phone.post("/api/check/start", headers=h).json()["challenge"], origin, flags=0x01)):
        assert phone.post("/api/check/passkey", headers=h, json=bad).status_code == 403
    forged = auth.get(phone.post("/api/check/start", headers=h).json()["challenge"], origin)
    forged["signature"] = passkeys.b64u(ec.generate_private_key(ec.SECP256R1()).sign(b"x", ec.ECDSA(hashes.SHA256())))
    assert phone.post("/api/check/passkey", headers=h, json=forged).status_code == 403
    assert any(e["type"] == "check.failed" for e in server.hub.log.latest(30))


def test_adding_a_passkey_late_needs_a_mac_check_first(monkeypatch):
    rp, origin = "hub.example.ts.net", "https://hub.example.ts.net:8443"
    monkeypatch.setenv("SW_HOSTS", rp)
    monkeypatch.setattr(server, "hub", server.Hub())
    as_phone(monkeypatch)
    phone = TestClient(server.app, base_url=origin)
    token = join(phone, "layla")
    server.hub.sessions[server.token_hash(token)]["allowed"] = time.time() - 3600  # allowed an hour ago
    assert phone.post("/api/check/start", headers={"X-Session": token}).json()["how"] == "mac"


def test_a_counter_going_back_means_a_copied_passkey(tmp_path):
    store, rp, origin = passkeys.Store(tmp_path / "k.json"), "hub.example.ts.net", "https://hub.example.ts.net"
    auth = Authenticator(rp)
    store.register("s1", "layla", auth.create(store.challenge("s1", "create"), origin), rp, origin)
    store.verify("s1", "layla", auth.get(store.challenge("s1", "get"), origin), rp, origin)
    auth.count = 0
    with pytest.raises(passkeys.PasskeyError):
        store.verify("s1", "layla", auth.get(store.challenge("s1", "get"), origin), rp, origin)
    with pytest.raises(passkeys.PasskeyError):  # another phone's challenge
        store.verify("s2", "layla", auth.get(store.challenge("s1", "get"), origin), rp, origin)
