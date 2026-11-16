"""Turn what someone said into an action and a file. No AI: a plain word match, so it is predictable.

- "open the Al Noor slides"            -> open,  Al Noor slides
- "open the report"                    -> open,  two files match -> ask which one
- "send the Al Noor report to Karim"   -> send,  Al Noor report, to "Karim" (always needs a tap)
- Arabic works for the same words: "افتح عرض النور"
- "turn on the lamp" / «شغّل المصباح»  -> on,    the meeting-room lamp (devices are checked first)
- "switch the light off" / «طفّي الضوء» -> off,   the meeting-room lamp
- "turn off the TV", "volume up", "mute", "open YouTube" -> the TV (only once a TV has been added on the Mac)
- "print the Al Noor report" / «اطبع تقرير النور»        -> print that file on the added printer (always a tap)
- A device word with no such device added -> "no TV/printer is added yet", never a file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import devices as device_list
from .devices import KIND_WORDS, Device
from .records import RECORDS, Record

OPEN_WORDS = ("open", "show", "display", "pull up", "put up", "افتح", "اعرض", "شغل", "شغّل")
SEND_WORDS = ("send", "email", "share", "forward", "ارسل", "أرسل", "شارك")
OFF_WORDS = ("off", "turn off", "switch off", "shut", "طفي", "طفى", "اطفي", "أطفئ", "اطفئ", "اطفىء", "سكر", "اقفل")
PRINT_WORDS = ("print", "print out", "اطبع", "أطبع", "طباعة")
VOLUME_UP = ("volume up", "turn up", "louder", "turn it up", "raise the volume", "ارفع الصوت", "علي الصوت", "زود الصوت", "ارفع")
VOLUME_DOWN = ("volume down", "turn down", "quieter", "softer", "lower the volume", "turn it down",
               "اخفض الصوت", "وطي الصوت", "قلل الصوت", "اخفض", "نزل الصوت")
MUTE_WORDS = ("mute", "unmute", "اكتم", "كتم", "اكتم الصوت")
HDMI_WORDS = ("hdmi", "input", "source", "المدخل")
APP_WORDS = {"app:youtube": ("youtube", "you tube", "يوتيوب", "اليوتيوب"), "app:netflix": ("netflix", "نتفلكس", "نتفليكس")}


def normalise(text: str) -> str:
    text = text.lower().replace("ّ", "")  # drop the Arabic shadda so "شغّل" == "شغل"
    text = re.sub(r"[^\w\s]", " ", text)    # \w keeps Arabic letters
    return " " + re.sub(r"\s+", " ", text).strip() + " "


def has(text: str, phrase: str) -> bool:
    return f" {normalise(phrase).strip()} " in text


@dataclass
class Intent:
    action: str                  # "open" | "send" (a file) or "on" | "off" (a device)
    text: str                    # the words used to find the file or device
    recipient: str | None = None
    matches: list[Record] = field(default_factory=list)
    device: Device | None = None
    kind: str | None = None                                       # plug | tv | printer, when a device is meant
    device_options: list[Device] = field(default_factory=list)   # several devices fit: ask which one


def any_of(text: str, words) -> bool:
    return any(has(text, w) for w in words)


def tv_action(text: str) -> str | None:
    """A TV-only action named in the words, or None."""
    for action, words in APP_WORDS.items():
        if any_of(text, words):
            return action
    if any_of(text, VOLUME_UP):
        return "volume_up"
    if any_of(text, VOLUME_DOWN):
        return "volume_down"
    if any_of(text, MUTE_WORDS):
        return "mute"
    if any_of(text, HDMI_WORDS):
        return "hdmi"
    return None


def device_intent(text: str, devs) -> Intent | None:
    if any_of(text, PRINT_WORDS):
        printers = [d for d in devs if d.kind == "printer"]
        return Intent(action="print", text=text, kind="printer", matches=match(text),
                      device=printers[0] if len(printers) == 1 else None, device_options=printers)
    tv_only = tv_action(text)
    by_name = [d for d in devs if any_of(text, d.words)]  # a device's own name ("the oven") or its kind's words
    kinds = list(dict.fromkeys([d.kind for d in by_name] + [k for k, words in KIND_WORDS.items() if any_of(text, words)]))
    if tv_only and "tv" not in kinds:
        kinds.append("tv")
    if not kinds:
        return None
    kind = kinds[0]
    fits = [d for d in devs if d.kind == kind]
    if len(fits) > 1:  # several of that kind: the name narrows it ("the bedroom TV")
        def own_words(d):
            return [w for w in d.name.lower().replace("the ", "", 1).split() if w not in KIND_WORDS[d.kind]]
        named = [d for d in fits if any_of(text, own_words(d))]
        fits = named or fits
    action = tv_only if kind == "tv" and tv_only else ("off" if any_of(text, OFF_WORDS) else "on")
    return Intent(action=action, text=text, kind=kind, device=fits[0] if len(fits) == 1 else None,
                  device_options=fits)


def parse(said: str, devs=None) -> Intent:
    text = normalise(said)
    found = device_intent(text, device_list.current() if devs is None else devs)
    if found:  # a device word wins: "turn on the lamp" never opens a file
        return found
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
