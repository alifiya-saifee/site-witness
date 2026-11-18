"""Understanding what someone meant, with Groq (a fast hosted language model), when GROQ_API_KEY is set.

The model gets the sentence, the last few turns of the conversation, and a **menu** of what is possible right now
(file titles, app names (the built-in ones and every app installed on the Mac), website names, device names and
their actions). It answers with JSON: a list of **steps** (up to 5, run in order), and optionally a short
**answer** when the person asked a question or asked for something that isn't on the menu.

Its answer is only a suggestion: every step is checked here, and anything not on the menu is thrown away. A
checked step becomes the same Intent the word matcher makes, so every rule (roles, Approve taps, checks, proof)
still applies. If Groq is off, slow, rate-limited or wrong, the word matcher in commands.py is used instead.

Sent to Groq: the sentence, the recent conversation (what was said and what happened, e.g. "opened Notes"), and
names from the menu. Never: file contents, file paths, addresses, tokens or keys.
Draft text (WhatsApp, email) must appear in the sentence word for word, so the model can't invent a message.
An answer may never claim something was done that no step did (`claims_done`).

`write_reply` asks Groq for one short spoken reply from the real results; `fact_checked` keeps it only if every
number and every name in it appears in those results.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

import httpx

from . import apps, sites
from .commands import Intent, normalise
from .records import BY_ID, RECORDS

URL = "https://api.groq.com/openai/v1/chat/completions"
MODELS = ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b")
TIMEOUT = 4.0
MAX_STEPS = 5
_cache: dict[str, dict] = {}
_working_model: list[str] = []
_lock = threading.Lock()
_last_calls: list[float] = []

REPLY_MODELS = ("openai/gpt-oss-20b", "qwen/qwen3.8-27b")
STATUS_WHAT = ("mac_volume", "devices", "websites", "apps", "files", "history")

SYSTEM = """You are the voice assistant for an office. You turn what the person said into STEPS taken only from the
MENU, and you may add a short ANSWER. Reply with JSON only:
{"steps":[<step>, ...], "answer":"<short spoken answer, or empty>"}
Each step is one of:
{"action":"open_file","file":"<file id>"}
{"action":"send_file","file":"<file id>","to":"<name said>"}
{"action":"search_files","words":"<words to look for in file names or inside files>","mode":"find|open"}
{"action":"open_app","app":"<built-in app key>","target":"mac|phone|here","text":"<message text, copied word for word, or empty>"}
{"action":"open_mac_app","app":"<exact name from mac_apps>"}
{"action":"open_site","site":"<site id>","target":"mac|phone|here"}
{"action":"new_site","name":"<website name said>","target":"mac|phone|here"}
{"action":"mac_volume","op":"up|down|mute|unmute|set","level":<0-100 or null>}
{"action":"device","device":"<device id>","do":"<one of that device's actions>","place":"<one of its places or empty>"}
{"action":"print","file":"<file id>"}
{"action":"status","what":"mac_volume|devices|websites|apps|files|history"}
{"action":"forget"}
{"action":"unclear","question":"<one short question to ask back>"}
Rules:
- Several things asked in one sentence = several steps, in the order said (at most 5).
- "here" means the device the person is speaking on. "on my Mac"/"on the laptop"/"على الماك" means mac.
- Built-in apps (WhatsApp, YouTube, Maps, Mail, Calendar, Phone) use open_app. Any other app on the Mac uses
  open_mac_app with its exact name from mac_apps (e.g. "notes" -> "Notes").
- To find or open a file that isn't in "files", use search_files with the key words.
- Questions about the current state (the Mac's volume, which devices are on, what websites/apps/files there are,
  what was just done) use status. Do not guess the answer to those yourself.
- Use RECENT to understand "it", "that", "again", "the same", "more": e.g. "send it to Omar" after a file was opened
  means that file.
- "forget that" / "انسَ" = forget.
- If the person asks a general question (maths, a word, advice) or for something not on the MENU at all, give no
  steps and put a short helpful answer in "answer" (at most 2 sentences, in the language they spoke). Say plainly
  if it's something you can't do. Never say you did something unless it is a step.
- Use new_site only for a website not in the menu. Mac volume is the computer's own sound; a TV's volume is a device
  action. Ignore filler words ("uh", "yes", "one two three").
- If you are not sure what they want, use unclear. Never make up ids, names, addresses or message text."""

REPLY_SYSTEM = """You write the one short sentence a voice assistant says back after doing things. Use ONLY the facts
given. Every number and every name you say must appear in the facts. Don't add anything. Be warm and brief (at most
2 sentences). A step that is "NOT done yet" or "NOT started" has NOT happened: never say it was done or sent; say it
is waiting for their tap on Approve. If a step failed, say which and why.
Write in the language given ("en" English, "ar" Arabic). Reply with JSON only: {"reply":"..."}"""


def enabled() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def menu(devs, spoke_from: str, mac_apps=(), recent=()) -> dict:
    m = {
        "speaking_on": spoke_from,
        "files": [{"id": r.id, "title": r.title} for r in RECORDS],
        "apps": [{"key": a.key, "name": a.name, "on_mac": a.on_mac, "on_phone": bool(a.phone)} for a in apps.APPS.values()],
        "websites": [{"id": s["id"], "name": s["name"]} for s in sites.load()],
        "devices": [{"id": d.id, "name": d.name, "kind": d.kind, "actions": [a for a in d.actions if a != "pair"],
                     "places": list(d.place_names)} for d in devs],
    }
    if mac_apps:
        m["mac_apps"] = sorted(mac_apps)
    if recent:
        m["recent"] = list(recent)
    return m


def _rate_ok() -> bool:
    """Stay well under free-tier limits: at most 25 calls a minute."""
    now = time.monotonic()
    with _lock:
        _last_calls[:] = [t for t in _last_calls if now - t < 60]
        if len(_last_calls) >= 25:
            return False
        _last_calls.append(now)
        return True


def _chat(system: str, user: dict, post=None, max_tokens: int = 1200, timeout: float = TIMEOUT,
          models=None) -> dict | None:
    """One JSON chat call, trying the working model first. A model that is busy (its per-minute limit on the free
    plan) or retired is skipped for the next one. None if Groq can't be used right now."""
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None
    cache_key = json.dumps([system[:40], user], sort_keys=True, ensure_ascii=False)
    if cache_key in _cache:
        return _cache[cache_key]
    if not _rate_ok():
        return None
    post = post or (lambda body: httpx.post(URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=timeout))
    preferred = [os.environ["SW_GROQ_MODEL"]] if os.environ.get("SW_GROQ_MODEL") else []
    order = list(models) if models else preferred + _working_model + list(MODELS)
    busy = False
    for model in list(dict.fromkeys(order)):
        body = {"model": model, "temperature": 0, "response_format": {"type": "json_object"}, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]}
        if model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"  # these models think before answering; keep it short and fast
        try:
            r = post(body)
        except Exception:
            return None  # network trouble: use the word matcher
        if r.status_code in (400, 404) and "model" in r.text.lower() and "json" not in r.text.lower():
            continue  # that model was retired: try the next
        if r.status_code in (429, 503):
            busy = True
            continue  # busy (free-plan limit per minute): the next model has its own limit
        if r.status_code != 200:
            return None
        try:
            answer = json.loads(r.json()["choices"][0]["message"]["content"])
        except (KeyError, IndexError, ValueError, TypeError):
            return None
        if model not in _working_model and not models and not busy:
            _working_model[:] = [model]  # remember a model that works (not one used only because another was busy)
        if isinstance(answer, dict):
            _cache[cache_key] = answer
            return answer
        return None
    return None


def ask(sentence: str, the_menu: dict, post=None) -> dict | None:
    """The model's JSON answer, or None if Groq can't be used right now."""
    return _chat(SYSTEM, {"menu": the_menu, "said": sentence}, post)


def _in_sentence(text: str, sentence: str) -> bool:
    return bool(text) and normalise(text).strip() in normalise(sentence)


def to_intent(a: dict, sentence: str, devs, spoke_from: str, mac_apps=()) -> Intent | None:
    """Check one step against the menu. Anything off the menu gives None."""
    if not isinstance(a, dict):
        return None
    act = a.get("action")
    text = normalise(sentence)

    def where(t):
        return "mac" if t == "mac" else "phone" if t == "phone" else ("mac" if spoke_from == "mac" else "phone")

    if act == "open_file" and a.get("file") in BY_ID:
        return Intent(action="open", text=text, matches=[BY_ID[a["file"]]])
    if act == "send_file" and a.get("file") in BY_ID:
        to = sites.clean_name(a.get("to", ""), 40).title() or None
        return Intent(action="send", text=text, recipient=to, matches=[BY_ID[a["file"]]])
    if act == "search_files" and isinstance(a.get("words"), str) and a["words"].strip():
        words = sites.clean_name(a["words"], 120)
        return Intent(action="open", text=text, search=words, search_mode="find" if a.get("mode") == "find" else "open")
    if act == "open_app" and a.get("app") in apps.APPS:
        msg = a.get("text") or None
        if msg and not _in_sentence(msg, sentence):
            msg = None  # the message must be what the person said, word for word
        return Intent(action="app", text=text, app=a["app"], target=where(a.get("target")), message=apps.clean_text(msg))
    if act == "open_mac_app":
        name = str(a.get("app") or "")
        builtin = next((k for k, x in apps.APPS.items() if x.on_mac and x.name.lower() == name.lower()), None)
        if builtin:  # "Mail" / "Calendar" from the Mac list: the built-in app (it has its own checks)
            return Intent(action="app", text=text, app=builtin, target="mac")
        if name in mac_apps:
            return Intent(action="mac_app", text=text, mac_app=name, target="mac")
        return None
    if act == "open_site" and sites.get(str(a.get("site", ""))):
        return Intent(action="site", text=text, site=a["site"], target=where(a.get("target")))
    if act == "new_site" and isinstance(a.get("name"), str) and sites.clean_name(a["name"]):
        return Intent(action="site_unknown", text=text, site_name=sites.clean_name(a["name"]), target=where(a.get("target")))
    if act == "mac_volume" and a.get("op") in ("up", "down", "mute", "unmute", "set"):
        level = a.get("level")
        if a["op"] == "set":
            if not isinstance(level, (int, float)) or isinstance(level, bool) or not 0 <= level <= 100:
                return None
            level = int(level)
        return Intent(action="mac_volume", text=text, volume_op=a["op"], level=level if a["op"] == "set" else None)
    if act == "device":
        dev = next((d for d in devs if d.id == a.get("device")), None)
        if dev is None or a.get("do") not in dev.actions or a.get("do") == "pair":
            return None
        place = a.get("place") or None
        if place and place not in dev.place_names:
            return None
        if a["do"] in ("clean", "goto") and not place:
            return None
        return Intent(action=a["do"], text=text, kind=dev.kind, device=dev, device_options=[dev], place=place)
    if act == "print" and a.get("file") in BY_ID:
        printers = [d for d in devs if d.kind == "printer"]
        return Intent(action="print", text=text, kind="printer", matches=[BY_ID[a["file"]]],
                      device=printers[0] if len(printers) == 1 else None, device_options=printers)
    if act == "status" and a.get("what") in STATUS_WHAT:
        return Intent(action="status", text=text, what=a["what"])
    if act == "forget":
        return Intent(action="forget", text=text)
    if act == "unclear":
        q = re.sub(r"[^\w\s?,.'’-]", "", str(a.get("question") or ""))[:150].strip()
        return Intent(action="unclear", text=text, question=q or None)
    return None


CLAIM = re.compile(r"\b(i(?:'ve| have)?\s+(?:opened|sent|turned|switched|set|started|printed|played|muted|unmuted|"
                   r"saved|closed|launched|changed|ordered|booked|called)|(?:it'?s|is) (?:now )?(?:open|on|off|done|sent)|"
                   r"^done\b)|(?:^|\s)(?:تم|فتحت|أرسلت|شغلت|شغّلت|أطفأت)(?:\s|$|[.،])", re.I)


def claims_done(answer: str) -> bool:
    """True if a spoken answer says something was done (only steps may do things)."""
    return bool(CLAIM.search(answer or ""))


def clean_answer(text) -> str:
    t = re.sub(r"[<>`{}\[\]\\]", "", str(text or "")).strip()
    return re.sub(r"\s+", " ", t)[:300]


def to_plan(a, sentence: str, devs, spoke_from: str, mac_apps=()) -> tuple[list[Intent], str, int] | None:
    """(checked steps, answer, how many steps were thrown away). Accepts {"steps":[…],"answer":…} or one step."""
    if not isinstance(a, dict):
        return None
    raw = a.get("steps") if isinstance(a.get("steps"), list) else ([a] if "action" in a else [])
    steps, skipped = [], 0
    for step in raw[:MAX_STEPS]:
        i = to_intent(step, sentence, devs, spoke_from, mac_apps)
        if i is None:
            skipped += 1
        else:
            steps.append(i)
    skipped += max(0, len(raw) - MAX_STEPS)
    if any(i.action == "unclear" for i in steps) and len(steps) > 1:
        steps = [i for i in steps if i.action != "unclear"]  # something clear was asked too: do that
    answer = clean_answer(a.get("answer"))
    if answer and all(i.action == "unclear" for i in steps):
        steps = []  # it answered the question: say the answer rather than ask back
    if answer and not steps and claims_done(answer):
        answer = ""  # it said it did something, but nothing was done: don't let it pretend
    if not steps and not answer:
        return None
    return steps, answer, skipped


def understand(sentence: str, devs, spoke_from: str, post=None) -> Intent | None:
    """The first checked step (kept for callers that do one thing)."""
    plan = understand_plan(sentence, devs, spoke_from, post=post)
    return plan[0][0] if plan and plan[0] else None


def understand_plan(sentence: str, devs, spoke_from: str, mac_apps=(), recent=(), post=None):
    answer = ask(sentence, menu(devs, spoke_from, mac_apps, recent), post)
    return to_plan(answer, sentence, devs, spoke_from, mac_apps) if answer is not None else None


# ---------------- a fresh spoken reply, fact-checked ----------------

NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def fact_checked(reply: str, facts: str, names=()) -> bool:
    """Every number in the reply is in the facts, and every known name in the reply is in the facts."""
    r, f = reply.translate(AR_DIGITS), facts.translate(AR_DIGITS)
    fact_numbers = {n.replace(",", "") for n in NUMBER.findall(f)}
    if any(n.replace(",", "") not in fact_numbers for n in NUMBER.findall(r)):
        return False
    low_r, low_f = r.lower(), f.lower()
    return all(not (n and n.lower() in low_r) or n.lower() in low_f for n in names)


def write_reply(lang: str, facts: list[str], names=(), post=None) -> str | None:
    """One short reply from what really happened, or None (then the fixed sentence is used)."""
    if not facts:
        return None
    a = _chat(REPLY_SYSTEM, {"language": lang, "facts": facts}, post, max_tokens=600, timeout=3.0,
              models=REPLY_MODELS)  # the small model: it keeps the main model's per-minute allowance for understanding
    text = clean_answer((a or {}).get("reply"))
    if not text or not fact_checked(text, " ".join(facts), names):
        return None
    return text
