import base64

import pytest
from fastapi.testclient import TestClient

from sitewitness import server
from sitewitness.records import BY_ID


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "hub", server.Hub())
    return TestClient(server.app)


@pytest.fixture
def local(monkeypatch):
    """Pretend the test client is this Mac (localhost)."""
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})


def cmd(client, text, person="layla", **kw):
    return client.post("/api/command", json={"text": text, "person": person, **kw}).json()


def test_a_device_on_the_wifi_must_pair_first(client):
    assert client.post("/api/command", json={"text": "open the Al Noor slides", "person": "layla"}).status_code == 401
    assert client.post("/api/pair", json={"code": "000000" if server.hub.pair_code != "000000" else "111111"}).status_code == 403
    s = client.post("/api/pair", json={"code": server.hub.pair_code}).json()["session"]
    r = client.post("/api/command", json={"text": "open the Al Noor slides", "person": "layla"}, headers={"X-Session": s})
    assert r.status_code == 200


def test_visitor_is_refused(client, local):
    r = cmd(client, "open the Al Noor slides", person="visitor")
    assert r["status"] == "refused"
    assert server.hub.log.latest(1)[0]["type"] == "access.refused"


def test_several_matches_then_choose(client, local):
    r = cmd(client, "open the report")
    assert r["status"] == "choose" and {o["id"] for o in r["options"]} == {"alnoor-report", "clinic-dha"}
    r = cmd(client, "open the report", choose="clinic-dha")
    assert r["status"] == "no_helper"  # no helper in this test: it says so instead of pretending


def test_send_never_sends_it_asks_for_a_tap(client, local):
    r = cmd(client, "send the Al Noor report to Karim")
    assert r["status"] == "needs_approval" and "Karim" in r["question"]
    assert not any(e["type"].startswith("device.") for e in server.hub.log.list())
    a = client.post(f"/api/approve/{r['approval']}").json()
    assert "Nothing was emailed" in a["note"]
    client.post(f"/api/approve/{r['approval']}")  # a second tap changes nothing
    assert [e["type"] for e in server.hub.log.list()].count("approval.given") == 1


def test_helper_must_be_on_this_mac_with_the_token(client):
    with pytest.raises(Exception):
        with client.websocket_connect(f"/helper/ws?token={server.hub.helper_token}") as ws:
            ws.receive_json()


def test_open_flow_with_a_helper_and_repeated_tap(client, local):
    with pytest.raises(Exception):  # wrong token: turned away at the door
        with client.websocket_connect("/helper/ws?token=wrong") as bad:
            bad.receive_json()
    with client.websocket_connect(f"/helper/ws?token={server.hub.helper_token}") as ws:
        r = cmd(client, "open the Al Noor slides", key="tap-1")
        assert r["status"] == "sent"
        msg = ws.receive_json()
        assert msg["type"] == "open_file" and msg["file_id"] == "alnoor-slides"

        # the same tap again: same answer, nothing new sent to the helper
        again = cmd(client, "open the Al Noor slides", key="tap-1")
        assert again["command"] == r["command"] and again["repeat"]

        # the one-time file token works once, for that file only
        assert client.get(f"/helper/file/alnoor-report?t={msg['token']}").status_code == 403
        r2 = cmd(client, "open the Al Noor slides", key="tap-2")
        msg2 = ws.receive_json()
        f = client.get(f"/helper/file/alnoor-slides?t={msg2['token']}")
        assert f.status_code == 200 and f.content[:4] == b"%PDF"
        assert client.get(f"/helper/file/alnoor-slides?t={msg2['token']}").status_code == 403

        ws.send_json({"type": "result", "command_id": r["command"], "ok": True, "confirmed": True,
                      "detail": "Opened in Preview and confirmed", "proof_b64": base64.b64encode(b"\xff\xd8jpg").decode()})
        ws.send_json({"type": "result", "command_id": r2["command"], "ok": True, "confirmed": False,
                      "detail": "Opened in Preview, but I couldn't confirm it"})
        client.get("/api/events")  # let the hub read the messages
    assert client.get(f"/api/status/{r['command']}").json()["state"] == "confirmed"
    assert client.get(f"/api/status/{r2['command']}").json()["state"] == "unconfirmed"
    assert client.get(f"/api/proof/{r['command']}").content == b"\xff\xd8jpg"
    types = [e["type"] for e in server.hub.log.list()]
    assert types.count("device.confirmed") == 1 and types.count("device.failed") == 1
