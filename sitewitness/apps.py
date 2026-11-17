"""Apps the agent may open: on the phone you spoke on, or on this Mac. Only these; never a link someone says.

Where: "on my Mac" / «على الماك» -> the Mac; "on my phone" -> the phone; nothing said -> the device you spoke on.
- Phone: phones only let a page open another app right after a tap, so the page shows an "Open …" button.
- Mac: the helper runs the command built here (`mac_command`), then checks with `lsappinfo` that the app is in
  front, and takes a screenshot. Only an app key and plain text are ever sent to the helper, never a command.

Drafts: WhatsApp and email can open with your text already typed, but **you add who it's to and press send
yourself**. Nothing is ever sent for you, and no phone numbers, addresses or contacts are stored here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

BROWSERS = ("Safari", "Google Chrome", "Chrome", "Firefox", "Arc", "Microsoft Edge", "Brave Browser", "Opera")


@dataclass(frozen=True)
class App:
    key: str
    name: str
    name_ar: str
    words: tuple[str, ...]
    phone: str | None              # link the phone opens, or None (not possible from a web page)
    mac_app: str | None = None     # a Mac app to open by name ("Mail"), or
    mac_url: str | None = None     # an https address to open in the default browser
    front: tuple[str, ...] = ()    # which app should be in front afterwards (browsers if empty and mac_url)

    @property
    def on_mac(self) -> bool:
        return bool(self.mac_app or self.mac_url)


APPS = {a.key: a for a in (
    App("whatsapp", "WhatsApp", "واتساب", ("whatsapp", "whats app", "واتساب", "الواتساب", "واتس اب", "واتس"),
        phone="https://wa.me/", mac_url="https://web.whatsapp.com/"),
    App("youtube", "YouTube", "يوتيوب", ("youtube", "you tube", "يوتيوب", "اليوتيوب"),
        phone="https://www.youtube.com/", mac_url="https://www.youtube.com/"),
    App("maps", "Google Maps", "خرائط جوجل", ("google maps", "maps", "the map", "خرائط", "الخرائط"),
        phone="https://maps.google.com/", mac_url="https://maps.google.com/"),
    App("mail", "Mail", "البريد", ("mail", "my email", "my emails", "inbox", "email app", "mail app", "البريد",
                                   "الايميل", "الإيميل", "ايميلي", "إيميلي"),
        phone="mailto:", mac_app="Mail", front=("Mail",)),
    App("calendar", "Calendar", "التقويم", ("calendar", "my diary", "my schedule", "schedule", "التقويم", "الرزنامة",
                                           "رزنامة", "تقويم", "جدولي"),
        phone=None, mac_app="Calendar", front=("Calendar",)),
    App("phone", "Phone", "الهاتف", ("dialler", "dialer", "phone app", "تطبيق الهاتف", "تطبيق الاتصال"), phone="tel:"),
)}

ON_PHONE = ("on my phone", "on the phone", "on this phone", "on my mobile", "على جوالي", "على الجوال", "على تلفوني",
            "على هاتفي", "على موبايلي")
ON_MAC = ("on my mac", "on the mac", "on this mac", "on my laptop", "on the laptop", "on my computer", "on the computer",
          "on mac", "على الماك", "على جهاز الماك", "على اللابتوب", "على الكمبيوتر", "على الحاسوب", "على ماك")

# "WhatsApp message: I've sent the report" / "send a WhatsApp saying …" / «رسالة واتساب: …»
WHATSAPP_TEXT = re.compile(r"(?:whats ?app|واتساب|الواتساب|واتس)\b[^:：]*?(?:[:：]|\bsaying\b|\bthat says\b|يقول|تقول|نصها)\s*(.+)$",
                           re.IGNORECASE)
# "write an email saying the report is ready" / "email draft: …" / «اكتب إيميل: …»
EMAIL_TEXT = re.compile(r"(?:\b(?:write|draft|compose|new)\s+(?:an?\s+)?e-?mail\b|\be-?mail\s+draft\b|"
                        r"اكتب (?:ايميل|إيميل|رسالة بريد|بريد)|مسودة (?:ايميل|إيميل|بريد))"
                        r"[^:：]*?(?:[:：]|\bsaying\b|\bthat says\b|يقول|تقول|نصها)\s*(.+)$", re.IGNORECASE)
EMAIL_DRAFT = re.compile(r"\b(?:write|draft|compose|new)\s+(?:an?\s+)?e-?mail\b|\be-?mail\s+draft\b|"
                         r"اكتب (?:ايميل|إيميل|رسالة بريد|بريد)|مسودة (?:ايميل|إيميل|بريد)", re.IGNORECASE)


def clean_text(text: str | None) -> str | None:
    """Plain text for a draft: no control characters, at most 1,000 characters."""
    if not text:
        return None
    t = re.sub(r"[\x00-\x1f\x7f]", " ", str(text)).strip().strip("\"'“”«»")
    return t[:1000] or None


def message_text(said: str, app: str = "whatsapp") -> str | None:
    m = (WHATSAPP_TEXT if app == "whatsapp" else EMAIL_TEXT).search(said or "")
    return clean_text(m.group(1)) if m else None


def link(app: str, text: str | None = None) -> str:
    """The phone's link (as before)."""
    base = APPS[app].phone or ""
    text = clean_text(text)
    if app == "whatsapp" and text:
        return f"{base}?text={quote(text)}"
    if app == "mail" and text:
        return f"mailto:?body={quote(text)}"
    return base


def whatsapp_installed() -> bool:
    return Path("/Applications/WhatsApp.app").exists()


def mac_command(app: str, text: str | None = None) -> list[str]:
    """The exact command the helper runs on the Mac. Built only from this list, never from what was said."""
    a = APPS[app]
    text = clean_text(text)
    if app == "mail" and text:
        return ["open", f"mailto:?body={quote(text)}"]  # a new draft in Mail; no address filled in
    if app == "whatsapp":
        if whatsapp_installed():
            return ["open", f"whatsapp://send?text={quote(text)}"] if text else ["open", "-a", "WhatsApp"]
        return ["open", f"https://web.whatsapp.com/send?text={quote(text)}"] if text else ["open", a.mac_url]
    if a.mac_app:
        return ["open", "-a", a.mac_app]
    return ["open", a.mac_url]


def expected_front(app: str) -> tuple[str, ...]:
    a = APPS[app]
    if app == "whatsapp" and whatsapp_installed():
        return ("WhatsApp",)
    return a.front or BROWSERS
