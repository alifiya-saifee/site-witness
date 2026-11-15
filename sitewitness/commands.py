"""Turn what someone said into an action and a file. No AI: a plain word match, so it is predictable.

- "open the Al Noor slides"            -> open,  Al Noor slides
- "open the report"                    -> open,  two files match -> ask which one
- "send the Al Noor report to Karim"   -> send,  Al Noor report, to "Karim" (always needs a tap)
- Arabic works for the same words: "افتح عرض النور"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .records import RECORDS, Record

OPEN_WORDS = ("open", "show", "display", "pull up", "put up", "افتح", "اعرض", "شغل", "شغّل")
SEND_WORDS = ("send", "email", "share", "forward", "ارسل", "أرسل", "شارك")


def normalise(text: str) -> str:
    text = text.lower().replace("ّ", "")  # drop the Arabic shadda so "شغّل" == "شغل"
    text = re.sub(r"[^\w\s]", " ", text)    # \w keeps Arabic letters
    return " " + re.sub(r"\s+", " ", text).strip() + " "


def has(text: str, phrase: str) -> bool:
    return f" {normalise(phrase).strip()} " in text


@dataclass
class Intent:
    action: str                  # "open" | "send"
    text: str                    # the words used to find the file
    recipient: str | None = None
    matches: list[Record] = field(default_factory=list)


def parse(said: str) -> Intent:
    text = normalise(said)
    action = "send" if any(has(text, w) for w in SEND_WORDS) else "open"
    recipient = None
    if action == "send":
        m = re.search(r" (?:to|الى|إلى) (.+)$", text)
        if m:
            recipient = m.group(1).strip().title()
            text = text[: m.start()] + " "  # the recipient's name is not part of the file name
    return Intent(action=action, text=text, recipient=recipient, matches=match(text))


def match(text: str) -> list[Record]:
    """Files whose words appear in the text. Only the best-scoring files are returned:
    one file means go ahead, several mean ask which one, none means not found."""
    scores = {r.id: sum(1 for w in r.words if has(text, w)) for r in RECORDS}
    best = max(scores.values(), default=0)
    if best == 0:
        return []
    return [r for r in RECORDS if scores[r.id] == best]
