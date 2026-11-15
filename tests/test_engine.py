import sqlite3

import pytest

from sitewitness.commands import parse
from sitewitness.events import EventLog
from sitewitness.records import BY_ID, allowed


# ---- event log ----

def test_unknown_event_type_is_refused():
    with pytest.raises(ValueError):
        EventLog().append("file.deleted", actor="x")


def test_same_key_returns_the_stored_event():
    log = EventLog()
    a = log.append("command.heard", actor="Layla", content={"said": "open"}, key="tap-1")
    b = log.append("command.heard", actor="Layla", content={"said": "something else"}, key="tap-1")
    assert a == b and len(log.list()) == 1


def test_events_cannot_be_changed_or_deleted():
    log = EventLog()
    log.append("command.heard", actor="Layla")
    with pytest.raises(sqlite3.DatabaseError):
        log.db.execute("update events set actor='someone else'")
    with pytest.raises(sqlite3.DatabaseError):
        log.db.execute("delete from events")
    assert log.list()[0]["actor"] == "Layla"


# ---- matching what was said to a file ----

def ids(said):
    return [r.id for r in parse(said).matches]


def test_one_match_goes_ahead():
    i = parse("Open the Al Noor slides, please")
    assert i.action == "open" and ids("Open the Al Noor slides, please") == ["alnoor-slides"]


def test_several_matches_ask_which_one():
    assert ids("open the report") == ["alnoor-report", "clinic-dha"]


def test_nothing_matches():
    assert ids("open the weather") == []


def test_send_finds_file_and_recipient_and_ignores_the_name_when_matching():
    i = parse("send the Al Noor report to Karim")
    assert i.action == "send" and i.recipient == "Karim" and [r.id for r in i.matches] == ["alnoor-report"]


def test_arabic_works():
    i = parse("افتح عرض النور")
    assert i.action == "open" and [r.id for r in i.matches] == ["alnoor-slides"]
    assert parse("شغّل العرض").action == "open"


# ---- who may open what ----

def test_permissions():
    assert allowed("layla", BY_ID["alnoor-report"])
    assert not allowed("omar", BY_ID["alnoor-report"])      # brokers can't open the signed report
    assert not allowed("visitor", BY_ID["alnoor-slides"])
    assert not allowed("nobody", BY_ID["alnoor-slides"])
