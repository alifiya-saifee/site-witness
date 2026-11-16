"""The event log: every step is an event, and events are never changed or deleted.

- Unknown event types are refused, so a typo can't slip into the record.
- An event can carry a key. Appending again with the same key returns the stored event
  instead of a new one, so a double tap or a retry never does the same thing twice.
- The database itself refuses UPDATE and DELETE on the events table.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

TYPES = {
    "command.heard",       # someone said or typed a command
    "file.matched",        # the command was matched to a file in Records
    "device.matched",      # the command was matched to a device in the device list
    "file.not_found",      # nothing matched
    "file.ambiguous",      # several files matched; the person was asked which one
    "access.refused",      # the person may not open or send that file
    "device.command",      # the hub told a helper to do something
    "device.confirmed",    # the helper did it and checked it worked
    "device.failed",       # the helper could not do it, or could not confirm it
    "approval.requested",  # a sensitive action is waiting for a person's tap
    "approval.given",      # the person tapped Approve
    "pairing.joined",      # a phone or browser joined with the pairing code
    "helper.connected",
    "helper.disconnected",
    "reply.spoken",          # the agent's spoken reply was played (where, which voice)
    "voice.sample_saved",    # the owner recorded a voice sample, with consent (the audio is never logged)
    "voice.sample_deleted",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class EventLog:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock, self.db:
            self.db.executescript(
                """
                create table if not exists events (
                  id integer primary key autoincrement,
                  at text not null,
                  type text not null,
                  actor text not null,
                  content text not null,
                  key text unique
                );
                create trigger if not exists events_no_update before update on events
                  begin select raise(abort, 'events are append-only'); end;
                create trigger if not exists events_no_delete before delete on events
                  begin select raise(abort, 'events are append-only'); end;
                """
            )

    @staticmethod
    def _row(r) -> dict:
        return {"id": r[0], "at": r[1], "type": r[2], "actor": r[3], "content": json.loads(r[4]), "key": r[5]}

    def append(self, type: str, *, actor: str, content: dict | None = None, key: str | None = None) -> dict:
        if type not in TYPES:
            raise ValueError(f"unknown event type: {type}")
        with self.lock, self.db:
            if key is not None:
                old = self.db.execute("select * from events where key=?", (key,)).fetchone()
                if old:
                    return self._row(old)
            cur = self.db.execute(
                "insert into events (at, type, actor, content, key) values (?,?,?,?,?)",
                (now(), type, actor, json.dumps(content or {}, ensure_ascii=False), key),
            )
            return self._row(self.db.execute("select * from events where id=?", (cur.lastrowid,)).fetchone())

    def list(self, after: int = 0, limit: int = 200) -> list[dict]:
        with self.lock:
            rows = self.db.execute("select * from events where id>? order by id limit ?", (after, limit)).fetchall()
        return [self._row(r) for r in rows]

    def latest(self, n: int = 30) -> list[dict]:
        with self.lock:
            rows = self.db.execute("select * from events order by id desc limit ?", (n,)).fetchall()
        return [self._row(r) for r in rows]
