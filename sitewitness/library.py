"""Shared folders: the folders the Mac's owner chose, each with the roles that may open its files, searchable by
the words inside them. These are the Records: there are no built-in files (the 4 sample PDFs are demo only).

Consent is the owner's choice of folders on the Mac itself; nothing outside them is ever read.
- Reads .pdf (pypdf), .docx (python-docx), .txt and .md. Skips hidden files, symlinks and anything that leaves the
  folder; at most 2,000 files of 20 MB each.
- The index is SQLite's built-in full-text search (FTS5) in run/search.db. Arabic is matched after light
  normalising (no diacritics, one alef, no leading "ال"), so «المياه» finds «مياه».
- File contents never go into the event log; only counts do.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from pathlib import Path

from .records import ROOT

RUN_DIR = ROOT / "run"
SETTINGS = RUN_DIR / "shared.json"
INDEX = RUN_DIR / "search.db"
DEFAULT_FOLDER = Path.home() / "Documents" / "Diwan Shared"
TYPES = {".pdf", ".docx", ".txt", ".md"}
MAX_FILES, MAX_BYTES = 2000, 20 * 1024 * 1024

STOP = set("""a an the of to for on in at by with and or my me your our please pls can you could would i want need
open show display find search look get pull up put file files document documents doc report reports pdf
about mentioning mention mentions regarding that says say which where is are was it this these those some any
send email mail share forward ارسل أرسل شارك
افتح اعرض ابحث دور عن على في من الى إلى ملف الملف ملفات التقرير تقرير المستند مستند بخصوص يذكر الذي التي""".split())
TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
ARABIC = re.compile(r"[؀-ۿ]")


class FolderError(ValueError):
    pass


# ---------------- which folder (the owner's choice) ----------------

def check_folder(text: str, home: Path | None = None) -> Path:
    """The folder the owner typed, if it is a safe one to share; otherwise why not."""
    home = (home or Path.home()).resolve()
    raw = Path(os.path.expanduser(str(text or "").strip() or str(DEFAULT_FOLDER)))
    if not raw.is_absolute():
        raw = home / raw
    folder = raw.resolve()
    if folder == home or home not in folder.parents:
        raise FolderError("Pick a folder inside your home folder (not the whole home folder)")
    rel = folder.relative_to(home).parts
    if any(p.startswith(".") for p in rel):
        raise FolderError("Hidden folders (like .ssh) can't be shared")
    if rel[0] in ("Library", "Desktop", "Downloads") or "Mobile Documents" in rel:
        raise FolderError(f"{rel[0]} can't be shared: pick or make a folder just for Diwan")
    return folder


def folders() -> list[dict]:
    """[{"folder": "/Users/…/Diwan Shared", "roles": ["owner", "broker"]}, …] in the order they were shared."""
    try:
        d = json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return []
    if d.get("folder"):  # the old one-folder file
        d = {"folders": [{"folder": d["folder"], "roles": d.get("roles", [])}]}
    return [f for f in d.get("folders", []) if isinstance(f, dict) and f.get("folder")]


def settings() -> dict | None:
    """The first shared folder (kept for older callers), or None when nothing is shared."""
    fs = folders()
    return {**fs[0], "folders": fs} if fs else None


def _save(fs: list[dict]) -> None:
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps({"folders": fs}))


def share(folder: Path, roles) -> dict:
    """Share a folder (or change who may open it)."""
    folder.mkdir(parents=True, exist_ok=True)
    fs = folders()
    old = next((f for f in fs if f["folder"] == str(folder)), None)
    if old:
        old["roles"] = list(roles)
    else:
        fs.append({"folder": str(folder), "roles": list(roles)})
        INDEX.unlink(missing_ok=True)  # a new folder: start a new index
    _save(fs)
    return {"folder": str(folder), "roles": list(roles)}


def unshare(folder: str | None = None) -> None:
    """Stop sharing one folder, or all of them."""
    fs = [f for f in folders() if folder is not None and f["folder"] != folder]
    if fs:
        _save(fs)
    else:
        SETTINGS.unlink(missing_ok=True)
    INDEX.unlink(missing_ok=True)


def roles_by_folder() -> list[list[str]]:
    return [list(f.get("roles", [])) for f in folders()]


# ---------------- reading files ----------------

def normalise(text: str) -> str:
    """For matching only: lower case; Arabic without diacritics, one alef, ة→ه, ى→ي, no leading ال/وال/بال."""
    t = TASHKEEL.sub("", (text or "").lower())
    t = t.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"}))
    return " ".join(re.sub(r"^(?:وال|بال|فال|كال|لل|ال)(?=\w{2,})", "", w) if ARABIC.search(w) else w
                    for w in re.findall(r"\w+", t))


def read_text(path: Path) -> tuple[str, str]:
    """(title, text) of one file. A scanned PDF gives no text."""
    ext = path.suffix.lower()
    title, text = "", ""
    if ext == ".pdf":
        from pypdf import PdfReader
        r = PdfReader(str(path))
        text = "\n".join((p.extract_text() or "") for p in r.pages[:200])
        # letter-spaced headings come out as "R E S I D E N C E": join the letters back into words
        text = re.sub(r"\b(?:\w ){2,}\w\b", lambda m: m.group(0).replace(" ", ""), text)
        meta = r.metadata or {}
        title = str(meta.get("/Title") or "").strip()
    elif ext == ".docx":
        import docx
        d = docx.Document(str(path))
        text = "\n".join(p.text for p in d.paragraphs)
        title = (d.core_properties.title or "").strip()
    else:
        text = path.read_text(errors="replace")
    if not title:
        first = next((ln.strip(" #") for ln in text.splitlines() if ln.strip()), "")
        title = first[:80] if first and ext in (".md", ".txt", ".docx") else path.stem.replace("-", " ").replace("_", " ")
    return title[:120], text


# ---------------- the index ----------------

class Library:
    """One index over all shared folders. A file is kept as "<folder number>/<path inside it>"."""

    def __init__(self, folder, db_path: Path | None = None):
        roots = folder if isinstance(folder, (list, tuple)) else [folder]
        self.folders = [Path(f).resolve() for f in roots]
        self.folder = self.folders[0]
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(db_path or INDEX), check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, rel TEXT UNIQUE, title TEXT, mtime REAL,
                                             size INTEGER, has_text INTEGER);
            CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(norm, tokenize='unicode61 remove_diacritics 2');
            CREATE TABLE IF NOT EXISTS bodies(id INTEGER PRIMARY KEY, body TEXT);""")

    def candidates(self) -> tuple[list[tuple[int, Path]], int]:
        """Files that may be read: inside a shared folder, not hidden, not links, right type and size."""
        found, skipped = [], 0
        for i, root in enumerate(self.folders):
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and not os.path.islink(os.path.join(dirpath, d)))
                for name in sorted(filenames):
                    p = Path(dirpath) / name
                    if name.startswith(".") or p.suffix.lower() not in TYPES:
                        continue
                    if p.is_symlink() or not self.inside(p, i) or p.stat().st_size > MAX_BYTES or len(found) >= MAX_FILES:
                        skipped += 1
                        continue
                    found.append((i, p))
        return found, skipped

    def inside(self, p: Path, i: int = 0) -> bool:
        real = Path(os.path.realpath(p))
        return self.folders[i] in real.parents

    @staticmethod
    def split(rel: str) -> tuple[int, str]:
        n, _, rest = rel.partition("/")
        return (int(n), rest) if n.isdigit() else (0, rel)

    def index(self) -> dict:
        """Bring the index up to date: new or changed files are read, removed ones dropped."""
        with self.lock:
            files, skipped = self.candidates()
            seen, changed = set(), 0
            for i, p in files:
                rel = f"{i}/{p.relative_to(self.folders[i])}"
                seen.add(rel)
                st = p.stat()
                row = self.db.execute("SELECT id, mtime, size FROM files WHERE rel=?", (rel,)).fetchone()
                if row and row[1] == st.st_mtime and row[2] == st.st_size:
                    continue
                try:
                    title, text = read_text(p)
                except Exception:
                    title, text = p.stem, ""
                norm = normalise(f"{title} {p.stem} {text}")
                if row:
                    fid = row[0]
                    self.db.execute("UPDATE files SET title=?, mtime=?, size=?, has_text=? WHERE id=?",
                                    (title, st.st_mtime, st.st_size, int(bool(text.strip())), fid))
                    self.db.execute("DELETE FROM docs WHERE rowid=?", (fid,))
                else:
                    fid = self.db.execute("INSERT INTO files(rel, title, mtime, size, has_text) VALUES (?,?,?,?,?)",
                                          (rel, title, st.st_mtime, st.st_size, int(bool(text.strip())))).lastrowid
                self.db.execute("INSERT INTO docs(rowid, norm) VALUES (?,?)", (fid, norm))
                self.db.execute("INSERT OR REPLACE INTO bodies(id, body) VALUES (?,?)", (fid, text[:200_000]))
                changed += 1
            for fid, rel in self.db.execute("SELECT id, rel FROM files").fetchall():
                if rel not in seen:
                    for t in ("files", "bodies"):
                        self.db.execute(f"DELETE FROM {t} WHERE id=?", (fid,))
                    self.db.execute("DELETE FROM docs WHERE rowid=?", (fid,))
            self.db.commit()
            total, no_text = self.db.execute("SELECT count(*), sum(has_text=0) FROM files").fetchone()
            return {"files": total, "no_text": no_text or 0, "skipped": skipped, "changed": changed}

    @staticmethod
    def terms(words: str) -> list[str]:
        return [t for t in normalise(words).split() if t not in {normalise(s) for s in STOP} and len(t) > 1]

    def search(self, words: str, n: int = 5, only: set[int] | None = None) -> list[dict]:
        """Best files for these words: all words first; if none, any word. Each with a snippet.
        `only`: the folder numbers this person may open (others are never returned)."""
        terms = self.terms(words)
        if not terms:
            return []
        quoted = [f'"{t}"*' for t in terms]
        with self.lock:
            rows = []
            for q in (" AND ".join(quoted), " OR ".join(quoted)):
                rows = self.db.execute(
                    "SELECT f.id, f.rel, f.title, f.has_text, bm25(docs) FROM docs JOIN files f ON f.id = docs.rowid "
                    "WHERE docs MATCH ? ORDER BY bm25(docs) LIMIT ?", (q, n * 10)).fetchall()
                if only is not None:
                    rows = [r for r in rows if self.split(r[1])[0] in only]
                rows = rows[:n]
                if rows:
                    break
            out = []
            for fid, rel, title, has_text, score in rows:
                body = (self.db.execute("SELECT body FROM bodies WHERE id=?", (fid,)).fetchone() or [""])[0]
                out.append({"id": fid, "rel": self.split(rel)[1], "folder": self.split(rel)[0], "title": title,
                            "score": score, "has_text": bool(has_text),
                            "snippet": snippet(body, terms) if has_text else "No text inside (a scan): found by its name"})
            return out

    def get(self, fid: int) -> dict | None:
        row = self.db.execute("SELECT id, rel, title FROM files WHERE id=?", (fid,)).fetchone()
        if not row:
            return None
        i, rel = self.split(row[1])
        return {"id": row[0], "rel": rel, "folder": i, "title": row[2]}

    def path_of(self, fid: int) -> Path | None:
        """The file's real path, only if it is still a plain file inside its shared folder."""
        f = self.get(fid)
        if not f or f["folder"] >= len(self.folders):
            return None
        p = self.folders[f["folder"]] / f["rel"]
        if p.is_symlink() or not p.is_file() or not self.inside(p, f["folder"]):
            return None
        return p

    def count(self, i: int) -> int:
        return self.db.execute("SELECT count(*) FROM files WHERE rel LIKE ?", (f"{i}/%",)).fetchone()[0]

    def close(self) -> None:
        self.db.close()


def snippet(body: str, terms: list[str], width: int = 70) -> str:
    """A short piece of the text around the first matching word."""
    flat = re.sub(r"\s+", " ", body).strip()
    norm_words = flat.split(" ")
    for i, w in enumerate(norm_words):
        nw = normalise(w)
        if any(nw.startswith(t) for t in terms):
            start = max(0, len(" ".join(norm_words[:i])) - width // 2)
            if start:  # begin at a whole word
                start = flat.find(" ", start) + 1 or start
            piece = flat[start:start + width * 2].strip()
            return ("…" if start else "") + piece + ("…" if start + width * 2 < len(flat) else "")
    return flat[:width * 2] + ("…" if len(flat) > width * 2 else "")
