"""Join a test phone the real way: the code on the phone, then Allow on the Mac (done here straight on the hub)."""
from sitewitness import server


def join(client, person: str = "layla", **headers) -> str:
    r = client.post("/api/pair", json={"code": server.hub.pair_code}, headers=headers or None)
    assert r.status_code == 200, r.text
    token = r.json()["session"]
    import time
    server.hub.sessions[server.token_hash(token)].update(status="allowed", person=person, allowed=time.time())
    return token
