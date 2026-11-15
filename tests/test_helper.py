import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "helper"))
from diwan_helper import Helper  # noqa: E402


class FakeMac:
    """Records commands instead of running them. Preview 'has' whatever was opened."""
    def __init__(self, preview_ok=True):
        self.calls, self.opened, self.preview_ok = [], [], preview_ok

    def __call__(self, cmd, timeout=10):
        self.calls.append(cmd)
        if cmd[0] == "open":
            self.opened.append(Path(cmd[-1]).name)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[0] == "osascript":
            if not self.preview_ok:
                return subprocess.CompletedProcess(cmd, 1, "", "not allowed")
            return subprocess.CompletedProcess(cmd, 0, ", ".join(self.opened), "")
        if cmd[0] == "screencapture":
            Path(cmd[-1]).write_bytes(b"\xff\xd8jpg")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")


def msg(**kw):
    return {"type": "open_file", "command_id": "0123456789ab", "file_id": "alnoor-slides",
            "filename": "al-noor-law3-slides.pdf", "token": "t1"} | kw


def make(tmp_path, mac):
    return Helper(runner=mac, fetch=lambda fid, tok: b"%PDF-1.7 sample", opened_dir=tmp_path, wait=0.1)


def test_opens_confirms_and_sends_proof(tmp_path):
    mac = FakeMac()
    r = make(tmp_path, mac).open_file(msg())
    assert r["ok"] and r["confirmed"] and r["proof_b64"]
    assert ["open", "-a", "Preview", str(tmp_path / "al-noor-law3-slides.pdf")] in mac.calls


def test_refuses_unknown_file_and_paths(tmp_path):
    mac = FakeMac()
    h = make(tmp_path, mac)
    assert "Refused" in h.open_file(msg(file_id="passwords"))["detail"]
    assert "Refused" in h.open_file(msg(filename="../../etc/passwd"))["detail"]
    assert "Refused" in h.open_file(msg(type="run_shell"))["detail"]
    assert not any(c[0] == "open" for c in mac.calls)


def test_a_token_works_once(tmp_path):
    h = make(tmp_path, FakeMac())
    assert h.open_file(msg())["ok"]
    assert "already used" in h.open_file(msg())["detail"]


def test_a_hanging_tool_does_not_crash_the_helper(tmp_path, monkeypatch):
    import diwan_helper

    def hang(*a, **kw):
        raise subprocess.TimeoutExpired(a[0], 10)
    monkeypatch.setattr(diwan_helper.subprocess, "run", hang)
    assert diwan_helper.run(["osascript", "-e", "x"]).returncode == 124


def test_says_so_when_it_cannot_confirm(tmp_path):
    r = make(tmp_path, FakeMac(preview_ok=False)).open_file(msg())
    assert r["ok"] and not r["confirmed"] and "couldn't confirm" in r["detail"]
