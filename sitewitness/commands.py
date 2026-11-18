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
- "open WhatsApp" / «افتح واتساب» / "WhatsApp message: …" / "open Mail" / "open Calendar" ->
  an app from the approved list, on the Mac if you say "on my Mac" / «على الماك», on the phone if you say
  "on my phone", otherwise on the device you spoke on ("open YouTube" goes to the TV when one is added,
  unless you name the Mac or the phone). "write an email saying …" opens a draft: you add who and press send.
- "clean the kitchen", "robot go to the meeting room", "stop", «نظف المطبخ», «وقف» -> a robot.
- "turn up the volume on my Mac" / «ارفع الصوت على الماك» -> the Mac's own volume (a TV only if "TV" is said
  or a TV is added and the Mac isn't named)
- "open Cosmique website" -> a website you saved on the Mac (never an address someone says); not saved yet ->
  it asks for the address
- "find cracked balcony", «ابحث عن تسرب المياه" -> list files in the shared folder with those words inside
- "open the report about the cracked balcony" -> open the best match from the shared folder
  (the 4 Records files still come first: "open the Al Noor slides" is unchanged)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import devices as device_list
from . import apps, sites
from .devices import KIND_WORDS, Device
from .records import Record, active

OPEN_WORDS = ("open", "show", "display", "pull up", "put up", "افتح", "اعرض", "شغل", "شغّل")
SEND_WORDS = ("send", "email", "share", "forward", "ارسل", "أرسل", "شارك")
OFF_WORDS = ("off", "turn off", "switch off", "shut", "طفي", "طفى", "اطفي", "أطفئ", "اطفئ", "اطفىء", "سكر", "اقفل")
PRINT_WORDS = ("print", "print out", "اطبع", "أطبع", "طباعة")
VOLUME_UP = ("volume up", "turn up", "louder", "turn it up", "raise the volume", "ارفع الصوت", "علي الصوت", "زود الصوت", "ارفع")
VOLUME_DOWN = ("volume down", "turn down", "quieter", "softer", "lower the volume", "turn it down",
               "اخفض الصوت", "وطي الصوت", "قلل الصوت", "اخفض", "نزل الصوت")
MUTE_WORDS = ("mute", "unmute", "اكتم", "كتم", "اكتم الصوت")
HDMI_WORDS = ("hdmi", "input", "source", "المدخل")
ROBOT_PAUSE = ("pause", "وقف مؤقت", "إيقاف مؤقت", "ايقاف مؤقت", "استراحة")
ROBOT_STOP = ("stop", "halt", "وقف", "توقف", "اوقف", "أوقف", "قف")
ROBOT_DOCK = ("go home", "home", "dock", "charge", "go back", "return home", "back to base", "البيت", "ارجع", "اشحن", "عود", "ارجع للشحن")
ROBOT_GOTO = ("go to", "drive to", "move to", "head to", "come to", "روح", "اذهب", "توجه", "روح الى", "روح إلى", "اذهب الى", "اذهب إلى")
ROBOT_CLEAN = ("clean", "vacuum", "hoover", "نظف", "كنس")
ROBOT_START = ("start", "begin", "ابدأ", "ابدا", "شغل")
FIND_WORDS = ("search for", "look for", "find", "search", "ابحث عن", "ابحث", "دور على", "فتش عن")
ABOUT_WORDS = ("that mentions", "that says", "mentioning", "regarding", "about", "بخصوص", "يذكر", "عن")
FILLER = {"the", "a", "to", "please", "pls", "robot", "vacuum", "hoover", "room", "and", "ال", "من", "فضلك", "الروبوت"}
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
    place: str | None = None          # robots: the room or spot meant
    place_unknown: str | None = None  # robots: a place name the robot doesn't know
    app: str | None = None            # apps: which app (key in apps.APPS)
    target: str | None = None         # apps: "mac" | "phone"
    message: str | None = None        # WhatsApp: text to have ready (you still press send)
    search: str | None = None         # shared folder: the words to look for inside files
    search_mode: str | None = None    # "find" (list them) | "open" (open the best) | None (only if Records has none)
    site: str | None = None           # websites: a saved site id
    site_name: str | None = None      # websites: a name said that isn't saved yet (we ask for the address)
    volume_op: str | None = None      # Mac volume: up | down | mute | unmute | set
    level: int | None = None          # Mac volume: 0-100 for "set"
    question: str | None = None       # "unclear": what to ask back
    mac_app: str | None = None        # any app installed on the Mac, by its exact name (from the live map)
    what: str | None = None           # "status": what to read (mac_volume | devices | websites | apps | files | history)


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
    by_name = [d for d in devs if any_of(text, d.words)]  # a device's own name ("the oven"), or a robot's room
    kinds = list(dict.fromkeys([k for k, words in KIND_WORDS.items() if any_of(text, words)] + [d.kind for d in by_name]))
    if not kinds and any_of(text, ROBOT_STOP + ROBOT_PAUSE + ROBOT_DOCK + ROBOT_CLEAN + ROBOT_GOTO) \
            and any(d.kind == "robot" for d in devs):
        kinds = ["robot"]  # "stop!" or "clean the bathroom" on its own means the robot
    if kinds and kinds[0] == "robot":
        return robot_intent(text, [d for d in devs if d.kind == "robot"])
    if tv_only and "tv" not in kinds:
        kinds.append("tv")
    if not kinds:
        return None
    kinds = [k for k in kinds if any(d.kind == k for d in devs)] or kinds  # "lamp": the plug or the learned remote
    kind = kinds[0]
    fits = [d for d in devs if d.kind == kind]
    if len(fits) > 1:  # several of that kind: the name narrows it ("the bedroom TV")
        def own_words(d):
            return [w for w in d.name.lower().replace("the ", "", 1).split() if w not in KIND_WORDS[d.kind]]
        named = [d for d in fits if any_of(text, own_words(d))]
        fits = named or fits
    action = tv_only if kind == "tv" and tv_only else ("off" if any_of(text, OFF_WORDS) else "on")
    place = None
    if kind == "ble_lamp":  # "make the strip blue", "brighter", «اجعل الشريط أزرق»
        from .connectors.ble_lamp import COLOURS, COLOURS_AR
        place = next((c for c in COLOURS if has(text, c)), None) or \
            next((COLOURS_AR[w] for w in COLOURS_AR if has(text, w)), None)
        if place:
            action = "colour"
        elif any_of(text, ("brighter", "brighten", "more light", "أكثر سطوعا", "زد الإضاءة")):
            action = "brighter"
        elif any_of(text, ("dimmer", "dim", "less light", "أخفت", "خفف الإضاءة")):
            action = "dimmer"
    if kind == "switchbot" and any_of(text, ("press", "push", "اضغط")):
        action = "press"
    return Intent(action=action, text=text, kind=kind, device=fits[0] if len(fits) == 1 else None,
                  device_options=fits, place=place)


def robot_verb(text: str) -> str | None:
    if any_of(text, ROBOT_PAUSE):
        return "pause"
    if any_of(text, ROBOT_STOP + OFF_WORDS):
        return "stop"
    if any_of(text, ROBOT_DOCK):
        return "dock"
    if any_of(text, ROBOT_GOTO):
        return "goto"
    if any_of(text, ROBOT_CLEAN):
        return "clean"
    if any_of(text, ROBOT_START + ("on", "turn on", "switch on")):
        return "start"
    return None


def after_verb(text: str, verbs) -> str:
    """The words after "clean" / "go to", without filler: the place someone named."""
    for v in sorted(verbs, key=len, reverse=True):
        key = f" {normalise(v).strip()} "
        if key in text:
            rest = text.split(key, 1)[1]
            return " ".join(w for w in rest.split() if w not in FILLER).strip()
    return ""


def robot_intent(text: str, robots) -> Intent:
    verb = robot_verb(text) or "start"
    if len(robots) > 1 and any_of(text, ("vacuum", "hoover", "roborock", "المكنسة", "مكنسة")):
        robots = [d for d in robots if d.sub == "vacuum"] or robots
    if verb == "stop" and len(robots) > 1 and not any_of(text, [w for d in robots for w in d.name.lower().split()
                                                               if w not in KIND_WORDS["robot"] + ("the",)]):
        return Intent(action="stop", text=text, kind="robot", device=None, device_options=list(robots))  # stop them all
    place_of = {d.id: next((p[0] for p in d.places if any_of(text, p)), None) for d in robots}
    fits = robots
    if len(fits) > 1:
        named = [d for d in fits if any_of(text, [w for w in d.name.lower().replace("the ", "", 1).split()
                                                 if w not in KIND_WORDS["robot"]])]
        with_place = [d for d in fits if place_of[d.id]]
        can = [d for d in fits if ("clean" if verb in ("clean", "start", "pause") else verb) in d.actions
               or (verb == "goto" and "clean" in d.actions and place_of[d.id])]
        fits = named or with_place or can or fits
    dev = fits[0] if len(fits) == 1 else None
    place, unknown = (place_of.get(dev.id) if dev else None), None
    action = verb
    if dev:
        if verb in ("clean", "goto"):
            action = "clean" if "clean" in dev.actions else "goto"
            if action == "clean" and not place:
                action = "start"  # "clean" with no room: clean everything
            if action == "goto" and place == "Dock":
                action = "dock"
            if not place and action in ("clean", "goto"):
                unknown = after_verb(text, ROBOT_CLEAN + ROBOT_GOTO) or "?"
            if verb == "clean" and not place:
                rest = after_verb(text, ROBOT_CLEAN)
                if rest:
                    unknown, action = rest, "clean"
        elif verb == "start" and "start" not in dev.actions:
            action = "goto"
            unknown = after_verb(text, ROBOT_GOTO) or "?"
    return Intent(action=action, text=text, kind="robot", device=dev, device_options=fits, place=place,
                  place_unknown=unknown)


def app_intent(said: str, text: str, devs, spoke_from: str = "phone") -> Intent | None:
    """An app from the approved list, and where to open it: the Mac or the phone."""
    draft = apps.EMAIL_DRAFT.search(said or "")
    app = "mail" if draft else next((k for k, a in apps.APPS.items() if any_of(text, a.words)), None)
    if not app:
        return None
    on_mac, on_phone = any_of(text, apps.ON_MAC), any_of(text, apps.ON_PHONE)
    if app == "youtube" and not (on_mac or on_phone) and any(d.kind == "tv" for d in devs):
        return None  # "open YouTube" means the TV once there is one
    if app == "maps" and not (on_mac or on_phone or any_of(text, OPEN_WORDS)):
        return None
    target = "mac" if on_mac else "phone" if on_phone else ("mac" if spoke_from == "mac" else "phone")
    message = apps.message_text(said, app) if app in ("whatsapp", "mail") else None
    return Intent(action="app", text=text, app=app, target=target, message=message)


def words_after(text: str, verbs) -> str:
    """Everything said after the first of these words ("about the cracked balcony" -> "the cracked balcony")."""
    for v in sorted(verbs, key=len, reverse=True):
        key = f" {normalise(v).strip()} "
        if key in text:
            return text.split(key, 1)[1].strip()
    return ""


def search_part(text: str, action: str) -> tuple[str | None, str | None]:
    if action == "send":
        return text.strip() or None, None  # searched in the shared folders when no Record matches
    if any_of(text, FIND_WORDS):
        return words_after(text, FIND_WORDS) or None, "find"
    if any_of(text, ABOUT_WORDS):
        return words_after(text, ABOUT_WORDS) or None, "open"
    return text.strip(), None


HEARD_AS = [  # things Whisper writes for "on my Mac"
    (r"\bon (?:melmah|mel mah|my mack|my mac book|mac book|my macbook|the mack|my mag|my mic|mimac|my max)\b", "on my mac"),
]
SITE_WORDS = ("website", "web site", "site", "webpage", "الموقع", "موقع")
MAC_WORDS = ("mac", "laptop", "computer", "الماك", "اللابتوب", "الكمبيوتر")
VOLUME_SET = re.compile(r"(?:volume|الصوت)\s+(?:to|at|الى|إلى)?\s*(\d{1,3})\b")
MUTE_ONLY = ("mute", "اكتم", "كتم", "اكتم الصوت")
UNMUTE = ("unmute", "sound on", "turn the sound back on", "شغل الصوت", "ارجع الصوت")


def fix_hearing(said: str) -> str:
    out = said or ""
    for pat, rep in HEARD_AS:
        out = re.sub(pat, rep, out, flags=re.IGNORECASE)
    return out


def mac_volume_intent(said: str, text: str, devs) -> Intent | None:
    """The Mac's own sound: when the Mac is named, or no TV is added and "TV" isn't said."""
    has_tv = any(d.kind == "tv" for d in devs)
    if any_of(text, KIND_WORDS["tv"]) or (has_tv and not any_of(text, MAC_WORDS)):
        return None
    m = VOLUME_SET.search(text)
    if m and int(m.group(1)) <= 100:
        return Intent(action="mac_volume", text=text, volume_op="set", level=int(m.group(1)))
    if any_of(text, UNMUTE):
        return Intent(action="mac_volume", text=text, volume_op="unmute")
    if any_of(text, MUTE_ONLY):
        return Intent(action="mac_volume", text=text, volume_op="mute")
    up = VOLUME_UP + ("increase the volume", "increase volume", "volume higher", "make it louder")
    down = VOLUME_DOWN + ("decrease the volume", "reduce the volume", "decrease volume")
    if any_of(text, up):
        return Intent(action="mac_volume", text=text, volume_op="up")
    if any_of(text, down):
        return Intent(action="mac_volume", text=text, volume_op="down")
    return None


def site_intent(said: str, text: str, spoke_from: str) -> Intent | None:
    saved = sites.load()
    target = "mac" if any_of(text, apps.ON_MAC) else "phone" if any_of(text, apps.ON_PHONE) else \
        ("mac" if spoke_from == "mac" else "phone")
    for s in saved:
        if any_of(text, s["words"]):
            return Intent(action="site", text=text, site=s["id"], target=target)
    if not any_of(text, SITE_WORDS):
        return None
    before = text.split(next(f" {normalise(w).strip()} " for w in SITE_WORDS if has(text, w)), 1)[0]
    name = " ".join(w for w in before.split() if w not in FILLER and not any_of(f" {w} ", OPEN_WORDS)
                    and w not in {"can", "you", "could", "would", "the", "my", "our", "please", "open"})
    return Intent(action="site_unknown", text=text, site_name=(name.title() + " website").strip() if name else "our website",
                  target=target)


def parse(said: str, devs=None, spoke_from: str = "phone") -> Intent:
    """spoke_from: "mac" when the command came from the Mac's own page, else "phone"."""
    said = fix_hearing(said)
    text = normalise(said)
    devs = device_list.current() if devs is None else devs
    site = site_intent(said, text, spoke_from)
    if site:
        return site
    volume = mac_volume_intent(said, text, devs)
    if volume:
        return volume
    app = app_intent(said, text, devs, spoke_from)
    if app:
        return app
    found = device_intent(text, devs)
    if found:  # a device word wins: "turn on the lamp" never opens a file
        return found
    action = "send" if any(has(text, w) for w in SEND_WORDS) else "open"
    recipient = None
    if action == "send":
        m = re.search(r" (?:to|الى|إلى) (.+)$", text)
        if m:
            recipient = m.group(1).strip().title()
            text = text[: m.start()] + " "  # the recipient's name is not part of the file name
    search, mode = search_part(text, action)
    return Intent(action=action, text=text, recipient=recipient, matches=[] if mode else match(text),
                  search=search, search_mode=mode)


def match(text: str) -> list[Record]:
    """Files whose words appear in the text. Only the best-scoring files are returned:
    one file means go ahead, several mean ask which one, none means not found."""
    records = active()
    scores = {r.id: sum(1 for w in r.words if has(text, w)) for r in records}
    best = max(scores.values(), default=0)
    if best == 0:
        return []
    return [r for r in records if scores[r.id] == best]
