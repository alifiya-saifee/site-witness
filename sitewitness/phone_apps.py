"""Apps the agent may open on the phone you spoke on. Only these; never a link someone says.

Phones only let a web page open another app straight after a tap, so the page shows an "Open WhatsApp" button.
WhatsApp can open with a message already typed, but **you pick the chat and press send yourself**: nothing is
ever sent for you, and no phone numbers or contacts are stored here.
"""
from __future__ import annotations

import re
from urllib.parse import quote

APPS = {
    "whatsapp": ("WhatsApp", "واتساب", "https://wa.me/", ("whatsapp", "whats app", "واتساب", "الواتساب", "واتس اب", "واتس")),
    "youtube": ("YouTube", "يوتيوب", "https://www.youtube.com/", ("youtube", "you tube", "يوتيوب", "اليوتيوب")),
    "maps": ("Google Maps", "خرائط جوجل", "https://maps.google.com/", ("google maps", "maps", "the map", "خرائط", "الخرائط")),
    "phone": ("Phone", "الهاتف", "tel:", ("dialler", "dialer", "phone app", "تطبيق الهاتف")),
}
ON_PHONE = ("on my phone", "on the phone", "on this phone", "on my mobile", "على جوالي", "على الجوال", "على تلفوني",
            "على هاتفي", "على موبايلي")
# "WhatsApp message: I've sent the report" / "send a WhatsApp saying …" / «رسالة واتساب: …»
MESSAGE = re.compile(r"(?:whats ?app|واتساب|الواتساب|واتس)\b[^:：]*?(?:[:：]|\bsaying\b|\bthat says\b|يقول|تقول|نصها)\s*(.+)$",
                     re.IGNORECASE)


def link(app: str, text: str | None = None) -> str:
    base = APPS[app][2]
    if app == "whatsapp" and text:
        return f"{base}?text={quote(text)}"
    return base


def message_text(said: str) -> str | None:
    m = MESSAGE.search(said or "")
    text = m.group(1).strip().strip("\"'“”«»") if m else ""
    return text[:500] or None
