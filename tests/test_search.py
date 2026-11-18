import json
from pathlib import Path

import docx
import pytest
from fastapi.testclient import TestClient

from phone import join
from sitewitness import library, server
from sitewitness.commands import parse
from sitewitness.devices import LAMP
from sitewitness.library import FolderError, Library, check_folder


def tiny_pdf(text: str) -> bytes:
    """A one-page PDF with real text in it (no tools needed)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


@pytest.fixture
def folder(tmp_path):
    home = tmp_path / "home"
    share = home / "Documents" / "Diwan Shared"
    share.mkdir(parents=True)
    (share / "marina-balcony.pdf").write_bytes(tiny_pdf("Cracked balcony slab on level 7, rust stains"))
    (share / "lift.txt").write_text("Al Noor lift maintenance note\nThe lift door sensor is slow.")
    d = docx.Document()
    d.add_paragraph("تقرير تسرب المياه")
    d.add_paragraph("يوجد تسرب للمياه من السقف.")
    d.save(share / "leak.docx")
    (share / ".hidden.txt").write_text("cracked balcony hidden")
    (tmp_path / "outside.txt").write_text("cracked balcony outside")
    (share / "escape.txt").symlink_to(tmp_path / "outside.txt")
    with open(share / "big.txt", "wb") as f:  # over the 20 MB limit (sparse: no real disk space)
        f.write(b"cracked balcony ")
        f.truncate(21 * 1024 * 1024)
    return home, share


def test_reads_pdf_word_text_and_skips_the_rest(folder, tmp_path):
    home, share = folder
    lib = Library(share, tmp_path / "idx.db")
    counts = lib.index()
    assert counts["files"] == 3 and counts["skipped"] == 2  # the link and the big file; hidden files are not counted
    assert [r["title"] for r in lib.search("cracked balcony")] == ["marina balcony"]
    assert lib.search("ابحث عن تسرب المياه")[0]["title"] == "تقرير تسرب المياه"
    hit = lib.search("lift")[0]
    assert hit["title"] == "Al Noor lift maintenance note" and "lift" in hit["snippet"]
    assert lib.search("nothing like this") == []


def test_changes_are_picked_up(folder, tmp_path):
    _, share = folder
    lib = Library(share, tmp_path / "idx.db")
    lib.index()
    (share / "lift.txt").unlink()
    (share / "new.txt").write_text("Fire alarm panel fault")
    counts = lib.index()
    assert counts["changed"] == 1 and lib.search("lift") == [] and lib.search("fire alarm")


def test_a_file_moved_out_cant_be_opened(folder, tmp_path):
    _, share = folder
    lib = Library(share, tmp_path / "idx.db")
    lib.index()
    fid = lib.search("lift")[0]["id"]
    assert lib.path_of(fid) == share / "lift.txt"
    (share / "lift.txt").rename(tmp_path / "lift.txt")
    assert lib.path_of(fid) is None


@pytest.mark.parametrize("bad", ["", "~", ".ssh", "Library/Keys", "Desktop", "Downloads/x", "/etc", "../../etc"])
def test_folders_that_cant_be_shared(folder, bad):
    home, _ = folder
    if bad in ("", "~"):
        bad = str(home)
    with pytest.raises(FolderError):
        check_folder(bad, home=home)


def test_a_folder_inside_home_is_fine(folder):
    home, share = folder
    assert check_folder("Documents/Diwan Shared", home=home) == share.resolve()


def test_words():
    i = parse("open the report about the cracked balcony", [LAMP])
    assert i.search_mode == "open" and i.search == "the cracked balcony"
    assert parse("ابحث عن تسرب المياه", [LAMP]).search_mode == "find"
    assert [r.id for r in parse("open the Al Noor slides", [LAMP]).matches] == ["alnoor-slides"]
    assert parse("send the Al Noor report to Karim", [LAMP]).search_mode is None


# ---- the hub ----

@pytest.fixture
def client(folder, tmp_path, monkeypatch):
    home, share = folder
    monkeypatch.setattr(library, "SETTINGS", tmp_path / "shared.json")
    monkeypatch.setattr(library, "INDEX", tmp_path / "search.db")
    monkeypatch.setattr(library.Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(library, "DEFAULT_FOLDER", share)
    monkeypatch.setattr(server, "hub", server.Hub())
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})
    monkeypatch.setattr(server.voice, "_cache", {})
    return TestClient(server.app)


def share_it(client, roles=("owner", "broker")):
    r = client.post("/api/folder", json={"folder": "", "roles": list(roles)})
    assert r.status_code == 200, r.text
    return r.json()


def test_no_folder_shared_says_so(client):
    r = client.post("/api/command", json={"text": "find cracked balcony", "person": "layla"}).json()
    assert r["status"] == "not_found" and "No folder is shared" in r["reply"]["text"]
    r = client.post("/api/command", json={"text": "open the lift note", "person": "layla"}).json()
    assert r["status"] == "not_found" and r["reply"]["text"] == "I couldn't find that file."


def test_open_the_report_about_opens_the_best_match(client):
    assert share_it(client)["files"] == 3
    with client.websocket_connect(f"/helper/ws?token={server.hub.helper_token}") as ws:
        r = client.post("/api/command", json={"text": "open the report about the cracked balcony", "person": "layla"}).json()
        assert r["status"] in ("sent", "choose")
        if r["status"] == "choose":  # big.txt also says cracked balcony: pick the PDF
            pdf = next(o for o in r["options"] if o["title"] == "marina balcony")
            r = client.post("/api/command", json={"text": "x", "person": "layla", "choose": pdf["id"]}).json()
        m = ws.receive_json()
        assert m["type"] == "open_file" and m["filename"].startswith("lib-") and m["filename"].endswith(".pdf")
        got = client.get(f"/helper/file/{m['file_id']}?t={m['token']}")
        assert got.content.startswith(b"%PDF") and client.get(f"/helper/file/{m['file_id']}?t={m['token']}").status_code == 403
        ws.send_json({"type": "result", "command_id": r["command"], "ok": True, "confirmed": True, "detail": "ok"})
        client.get("/api/events")
    assert client.get(f"/api/status/{r['command']}").json()["reply"]["text"] == "Done. I've opened “marina balcony” on your Mac."
    log = json.dumps(server.hub.log.list())
    assert "rust stains" not in log and "slab" not in log  # contents never logged


def test_find_lists_with_snippets(client):
    share_it(client)
    r = client.post("/api/command", json={"text": "ابحث عن تسرب المياه", "person": "omar"}).json()
    assert r["status"] == "choose" and r["options"][0]["title"] == "تقرير تسرب المياه" and r["options"][0]["snippet"]
    assert "وجدت" in r["reply"]["text"]
    r = client.post("/api/command", json={"text": "find unicorns", "person": "omar"}).json()
    assert r["status"] == "not_found" and "unicorns" in r["reply"]["text"]


def test_visitor_needs_to_be_ticked(client):
    share_it(client, roles=("owner",))
    r = client.post("/api/command", json={"text": "find lift", "person": "visitor"}).json()
    assert r["status"] == "refused"


def test_folder_choice_is_mac_only_and_checked(client, monkeypatch):
    assert client.post("/api/folder", json={"folder": "/etc", "roles": ["owner"]}).status_code == 400
    assert client.post("/api/folder", json={"folder": "", "roles": []}).status_code == 400
    monkeypatch.setattr(server, "LOCAL_HOSTS", {"127.0.0.1"})
    assert client.post("/api/folder", json={"folder": "", "roles": ["owner"]}).status_code == 403
    assert client.get("/api/folder").status_code == 403


def test_records_still_come_first(client):
    share_it(client)
    with client.websocket_connect(f"/helper/ws?token={server.hub.helper_token}") as ws:
        r = client.post("/api/command", json={"text": "open the Al Noor slides", "person": "layla"}).json()
        assert ws.receive_json()["file_id"] == "alnoor-slides"


# ---- pairing ----

def test_wrong_codes_lock_then_change_the_code(client, monkeypatch):
    monkeypatch.setattr(server, "LOCAL_HOSTS", {"127.0.0.1"})  # a phone, not the Mac
    for _ in range(5):
        assert client.post("/api/pair", json={"code": "000000" if server.hub.pair_code != "000000" else "111111"}).status_code == 403
    assert client.post("/api/pair", json={"code": server.hub.pair_code}).status_code == 429  # locked, even with the right code
    server.hub.pair_fails.clear()
    old = server.hub.pair_code
    server.hub.pair_fail_total = 19
    client.post("/api/pair", json={"code": "nope"})
    assert server.hub.pair_code != old  # 20 wrong in all: a new code


def test_joined_phones_listed_and_removed(client, monkeypatch):
    phone = TestClient(server.app, headers={"user-agent": "Mozilla/5.0 (iPhone)"})
    monkeypatch.setattr(server, "LOCAL_HOSTS", {"127.0.0.1"})
    token = join(phone)
    assert phone.get("/api/events", headers={"X-Session": token}).status_code == 200
    assert phone.get("/api/sessions", headers={"X-Session": token}).status_code == 403  # the list is Mac only
    monkeypatch.setattr(server, "LOCAL_HOSTS", server.LOCAL_HOSTS | {"testclient"})
    listed = client.get("/api/sessions").json()
    assert listed[0]["name"] == "iPhone" and token not in json.dumps(listed)
    client.delete(f"/api/sessions/{listed[0]['id']}")
    monkeypatch.setattr(server, "LOCAL_HOSTS", {"127.0.0.1"})
    assert phone.get("/api/events", headers={"X-Session": token}).status_code == 401
