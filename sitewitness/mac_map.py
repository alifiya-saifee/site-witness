"""A live map of what's on this Mac, so the assistant can find things the moment you ask.

- **Apps:** every app in /Applications, /System/Applications (and their Utilities) and ~/Applications. When an app
  is installed its node is added at once; when it is deleted its node is removed at once. No timers: the folders
  are watched with macOS's own file-change notices (kqueue, built into Python), and only a change wakes the map.
- **Files (Owner only):** the Mac's Spotlight index is the live file map. macOS keeps it up to date the moment a
  file is added, renamed or deleted, so we don't keep a second copy. `find_files` asks it (`mdfind`, read only).
  Secrets and system data are never returned: ~/Library, hidden folders, .git, node_modules, .env files, keys,
  keychains and password-manager files.
- **The shared folder** uses the same file-change notices (`Watcher`) to update its search index at once.

Paths stay on the Mac (in the helper). The hub only sees app names, file names and a folder label for display;
a found file is opened by a one-time id, never by a path sent from the hub.
"""
from __future__ import annotations

import os
import re
import secrets
import select
import subprocess
import threading
import time
from pathlib import Path

HOME = Path.home()
APP_DIRS = [Path("/Applications"), Path("/Applications/Utilities"), Path("/System/Applications"),
            Path("/System/Applications/Utilities"), HOME / "Applications"]

HIDDEN_PARTS = {"Library", "node_modules", ".git", ".venv", "venv", "__pycache__", ".Trash", "site-packages"}
SECRET_NAME = re.compile(
    r"(^\.env|\.pem$|\.key$|\.p12$|\.pfx$|^id_(rsa|dsa|ecdsa|ed25519)|\.keychain(-db)?$|\.kdbx?$|\.1pif$|"
    r"\.agilekeychain$|\.opvault$|credentials|secret|password|\.ovpn$|\.asc$|\.gpg$|token)", re.I)
MAX_RESULTS = 8
DOC_TYPES = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".ppt", ".pptx", ".key", ".pages", ".numbers", ".txt",
             ".md", ".rtf", ".jpg", ".jpeg", ".png", ".heic", ".gif", ".mp4", ".mov", ".m4v", ".mp3", ".m4a", ".wav",
             ".zip", ".odt", ".ods", ".epub"}  # your documents, pictures and media; not program or app data


# ---------------- watching folders (kqueue: macOS's own file-change notices) ----------------

class Watcher:
    """Calls `on_change()` once shortly after anything in the watched folders changes (added, removed, renamed,
    written). With recursive=True every sub-folder is watched too (re-armed after each change).
    Runs in its own thread; `stop()` ends it."""

    def __init__(self, folders, on_change, recursive: bool = False, settle: float = 0.6, max_dirs: int = 2000):
        self.folders = [Path(f) for f in folders]
        self.on_change, self.recursive, self.settle, self.max_dirs = on_change, recursive, settle, max_dirs
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fds: dict[int, Path] = {}

    def _dirs(self) -> list[Path]:
        out = []
        for f in self.folders:
            if not f.is_dir():
                continue
            out.append(f)
            if self.recursive:
                for root, dirs, _ in os.walk(f):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in HIDDEN_PARTS]
                    out.extend(Path(root) / d for d in dirs)
                    if len(out) >= self.max_dirs:
                        return out[: self.max_dirs]
        return out

    def _arm(self, kq) -> None:
        for fd in self._fds:
            os.close(fd)
        self._fds = {}
        events = []
        for d in self._dirs():
            try:
                fd = os.open(d, os.O_RDONLY | getattr(os, "O_EVTONLY", 0))
            except OSError:
                continue
            self._fds[fd] = d
            events.append(select.kevent(fd, filter=select.KQ_FILTER_VNODE,
                                        flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                                        fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_DELETE |
                                        select.KQ_NOTE_RENAME | select.KQ_NOTE_EXTEND | select.KQ_NOTE_ATTRIB))
        if events:
            kq.control(events, 0, 0)

    def _loop(self) -> None:
        kq = select.kqueue()
        try:
            self._arm(kq)
            while not self._stop.is_set():
                got = kq.control(None, 16, 0.5)
                if not got:
                    continue
                time.sleep(self.settle)  # let a copy or install finish, and gather a burst into one change
                kq.control(None, 64, 0)
                if self._stop.is_set():
                    break
                try:
                    self.on_change()
                except Exception:
                    pass
                self._arm(kq)  # new or removed sub-folders
        finally:
            for fd in self._fds:
                os.close(fd)
            self._fds = {}
            kq.close()

    def start(self) -> "Watcher":
        self._thread = threading.Thread(target=self._loop, daemon=True, name="watcher")
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)


# ---------------- apps ----------------

def list_apps(dirs=None) -> dict[str, Path]:
    """App name -> its .app folder. The first folder wins if two have the same name."""
    found: dict[str, Path] = {}
    for d in dirs or APP_DIRS:
        try:
            entries = sorted(Path(d).iterdir())
        except OSError:
            continue
        for p in entries:
            if p.suffix == ".app" and not p.name.startswith(".") and p.stem not in found:
                found[p.stem] = p
    return found


class AppMap:
    """The installed apps, kept live. `on_change(added, removed)` is called with app names when something is
    installed or deleted."""

    def __init__(self, dirs=None, on_change=None):
        self.dirs = [Path(d) for d in (dirs or APP_DIRS)]
        self.on_change = on_change
        self.apps = list_apps(self.dirs)
        self._lock = threading.Lock()
        self._watcher: Watcher | None = None

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self.apps)

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self.apps

    def refresh(self) -> tuple[list[str], list[str]]:
        new = list_apps(self.dirs)
        with self._lock:
            added = sorted(set(new) - set(self.apps))
            removed = sorted(set(self.apps) - set(new))
            self.apps = new
        if (added or removed) and self.on_change:
            self.on_change(added, removed)
        return added, removed

    def watch(self) -> "AppMap":
        self._watcher = Watcher(self.dirs, self.refresh).start()
        return self

    def stop(self) -> None:
        if self._watcher:
            self._watcher.stop()


# ---------------- files, through Spotlight ----------------

def safe_words(text: str) -> list[str]:
    """Plain words only (letters, digits; English or Arabic): nothing that could change the Spotlight query."""
    words = re.findall(r"[\w؀-ۿ]+", str(text or "").lower())
    stop = {"the", "a", "an", "my", "of", "on", "in", "for", "and", "file", "files", "find", "open", "mac", "from",
            "to", "me", "please", "document", "with", "that", "this", "is", "about", "last", "called", "named"}
    return [w for w in words if w not in stop and len(w) > 1][:6]


def hidden(path: Path, home: Path = HOME) -> bool:
    """True if this path must never be shown: outside home, system or app data, hidden, or a secret."""
    try:
        rel = path.relative_to(home)
    except ValueError:
        return True
    parts = rel.parts
    if not parts or any(p.startswith(".") or p in HIDDEN_PARTS or p.endswith(".app") for p in parts):
        return True
    if SECRET_NAME.search(path.name) or path.suffix.lower() not in DOC_TYPES:
        return True
    return in_code_project(path.parent, home)


def in_code_project(folder: Path, home: Path = HOME) -> bool:
    """Inside a code project (a folder with .git above it): program files, not your documents."""
    for d in (folder, *folder.parents):
        if d == home or d == d.parent:
            return False
        if (d / ".git").exists():
            return True
    return False


def spotlight(query: str, home: Path, runner) -> list[Path]:
    r = runner(["mdfind", "-onlyin", str(home), query])
    if r.returncode != 0:
        return []
    return [Path(line) for line in (r.stdout or "").splitlines() if line.strip()]


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=6)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "")


def find_files(text: str, home: Path = HOME, runner=_run, limit: int = MAX_RESULTS) -> list[Path]:
    """Files whose name has all the words first, then files with the words inside. Never hidden ones."""
    words = safe_words(text)
    if not words:
        return []
    by_name = " && ".join(f'kMDItemFSName == "*{w}*"cd' for w in words)
    found: list[Path] = []
    for query in (by_name, " ".join(words)):  # the second searches inside files too
        for p in spotlight(query, home, runner):
            if p not in found and not hidden(p, home) and not p.is_dir():
                found.append(p)
            if len(found) >= limit:
                return found
    return found


class Found:
    """Results the helper handed out, by one-time id. Only these can be opened, and each id works once."""

    def __init__(self, keep_for: float = 600):
        self.items: dict[str, tuple[Path, float]] = {}
        self.keep_for = keep_for

    def add(self, path: Path) -> str:
        now = time.monotonic()
        self.items = {k: v for k, v in self.items.items() if now - v[1] < self.keep_for}
        fid = secrets.token_hex(6)
        self.items[fid] = (path, now)
        return fid

    def take(self, fid: str) -> Path | None:
        got = self.items.pop(str(fid), None)
        if not got or time.monotonic() - got[1] >= self.keep_for:
            return None
        return got[0]


def label(path: Path, home: Path = HOME) -> str:
    """'Documents › Invoices' for display."""
    try:
        parts = path.parent.relative_to(home).parts
    except ValueError:
        return ""
    return " › ".join(parts[-2:]) if parts else "Home"
