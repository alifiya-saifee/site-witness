"""Understanding what someone meant, with Groq (a fast hosted language model), when GROQ_API_KEY is set.

The model gets the sentence and a short **menu** of what is possible right now (file titles, app names, website
names, device names and their actions). It answers with JSON naming one menu item. Its answer is only a
suggestion: every id, action and number is checked here, and anything not on the menu is thrown away. A checked
answer becomes the same Intent the word matcher makes, so every rule (roles, Approve taps, checks, proof) still
applies. If Groq is off, slow, rate-limited or wrong, the word matcher in commands.py is used instead.

Sent to Groq: the sentence, and names from the menu. Never: file contents, addresses, tokens or keys.
Draft text (WhatsApp, email) must appear in the sentence word for word, so the model can't invent a message.
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
MODELS = ("llama-3.3-70b-versatile", "openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.1-8b-instant")
TIMEOUT = 4.0
_cache: dict[str, dict] = {}
_working_model: list[str] = []
_lock = threading.Lock()
_last_calls: list[float] = []

SYSTEM = """You turn one spoken command for an office assistant into exactly one action from the MENU.
Reply with JSON only, no other text. Pick from these shapes:
{"action":"open_file","file":"<file id>"}
{"action":"send_file","file":"<file id>","to":"<name said>"}
{"action":"search_files","words":"<words to look for inside files>","mode":"find|open"}
{"action":"open_app","app":"<app key>","target":"mac|phone|here","text":"<message text, copied word for word, or empty>"}
{"action":"open_site","site":"<site id>","target":"mac|phone|here"}
{"action":"new_site","name":"<website name said>","target":"mac|phone|here"}
{"action":"mac_volume","op":"up|down|mute|unmute|set","level":<0-100 or null>}
{"action":"device","device":"<device id>","do":"<one of that device's actions>","place":"<one of its places or empty>"}
{"action":"print","file":"<file id>"}
{"action":"unclear","question":"<one short question to ask back>"}
Rules: "here" means the device the person is speaking on. "on my Mac"/"on the laptop"/"على الماك" means mac.
Use new_site only when the person asks for a website that is not in the menu. Mac volume is the computer's own
sound; a TV's volume is a device action. Ignore filler words ("uh", "yes", "one two three"). If you are not sure,
use unclear. Never make up ids, addresses or message text."""


def enabled() -> bool:
    return bool(os.environ.get("GROQ_API_KEY"))


def menu(devs, spoke_from: str) -> dict:
    return {
        "speaking_on": spoke_from,
        "files": [{"id": r.id, "title": r.title} for r in RECORDS],
        "apps": [{"key": a.key, "name": a.name, "on_mac": a.on_mac, "on_phone": bool(a.phone)} for a in apps.APPS.values()],
        "websites": [{"id": s["id"], "name": s["name"]} for s in sites.load()],
        "devices": [{"id": d.id, "name": d.name, "kind": d.kind, "actions": [a for a in d.actions if a != "pair"],
                     "places": list(d.place_names)} for d in devs],
    }


def _rate_ok() -> bool:
    """Stay well under free-tier limits: at most 25 calls a minute."""
    now = time.monotonic()
    with _lock:
        _last_calls[:] = [t for t in _last_calls if now - t < 60]
        if len(_last_calls) >= 25:
            return False
        _last_calls.append(now)
        return True


def ask(sentence: str, the_menu: dict, post=None) -> dict | None:
    """The model's JSON answer, or None if Groq can't be used right now."""
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None
    cache_key = json.dumps([sentence, the_menu], sort_keys=True, ensure_ascii=False)
    if cache_key in _cache:
        return _cache[cache_key]
    if not _rate_ok():
        return None
    post = post or (lambda body: httpx.post(URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=TIMEOUT))
    preferred = [os.environ["SW_GROQ_MODEL"]] if os.environ.get("SW_GROQ_MODEL") else []
    for model in list(dict.fromkeys(preferred + _working_model + list(MODELS))):
        body = {"model": model, "temperature": 0, "response_format": {"type": "json_object"}, "max_tokens": 200,
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": json.dumps({"menu": the_menu, "said": sentence}, ensure_ascii=False)}]}
        try:
            r = post(body)
        except Exception:
            return None  # network trouble: use the word matcher
        if r.status_code in (400, 404) and "model" in r.text.lower():
            continue  # that model was retired: try the next
        if r.status_code != 200:
            return None
        try:
            answer = json.loads(r.json()["choices"][0]["message"]["content"])
        except (KeyError, IndexError, ValueError, TypeError):
            return None
        if model not in _working_model:
            _working_model[:] = [model]
        if isinstance(answer, dict):
            _cache[cache_key] = answer
            return answer
        return None
    return None


def _in_sentence(text: str, sentence: str) -> bool:
    return bool(text) and normalise(text).strip() in normalise(sentence)


def to_intent(a: dict, sentence: str, devs, spoke_from: str) -> Intent | None:
    """Check the model's answer against the menu. Anything off the menu gives None."""
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
    if act == "open_site" and sites.get(str(a.get("site", ""))):
        return Intent(action="site", text=text, site=a["site"], target=where(a.get("target")))
    if act == "new_site" and isinstance(a.get("name"), str) and sites.clean_name(a["name"]):
        return Intent(action="site_unknown", text=text, site_name=sites.clean_name(a["name"]), target=where(a.get("target")))
    if act == "mac_volume" and a.get("op") in ("up", "down", "mute", "unmute", "set"):
        level = a.get("level")
        if a["op"] == "set":
            if not isinstance(level, (int, float)) or not 0 <= level <= 100:
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
    if act == "unclear":
        q = re.sub(r"[^\w\s?,.'’-]", "", str(a.get("question") or ""))[:150].strip()
        return Intent(action="unclear", text=text, question=q or None)
    return None


def understand(sentence: str, devs, spoke_from: str, post=None) -> Intent | None:
    answer = ask(sentence, menu(devs, spoke_from), post)
    return to_intent(answer, sentence, devs, spoke_from) if answer is not None else None
