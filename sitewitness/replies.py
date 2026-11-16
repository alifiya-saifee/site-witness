"""What the agent says back, out loud, after each command. One short sentence per outcome, in the language
the person used (Arabic written by hand, not machine-translated). File names are said in short spoken form."""
from __future__ import annotations

import re

ARABIC = re.compile(r"[؀-ۿ]")

# how each file is said out loud
SPOKEN = {
    "alnoor-slides": ("the Al Noor slides", "عرض النور"),
    "alnoor-report": ("the Al Noor signed report", "تقرير النور الموقّع"),
    "marina-quote": ("the Marina Court quote", "عرض سعر مارينا كورت"),
    "clinic-dha": ("the clinic inspection report", "تقرير فحص العيادة"),
}

TEXT = {
    "sent":        ("Opening {file} on your Mac.", "جارٍ فتح {file} على جهاز الماك."),
    "confirmed":   ("Done. I've opened {file} on your Mac.", "تم. فتحتُ {file} على جهاز الماك."),
    "unconfirmed": ("I opened it, but I couldn't check the screen.", "فتحته، لكن لم أتمكن من التحقق من الشاشة."),
    "failed":      ("Sorry, the Mac couldn't open it.", "عذرًا، لم يتمكن الماك من فتحه."),
    "refused":     ("Sorry, {person} isn't allowed to open that file.", "عذرًا، {person} لا يملك صلاحية فتح هذا الملف."),
    "choose":      ("I found {n} files. Which one do you mean?", "وجدت {n} ملفات. أيّها تقصد؟"),
    "needs_approval": ("Send {file} to {to}? Tap Approve.", "هل أرسل {file} إلى {to}؟ اضغط موافقة."),
    "not_found":   ("I couldn't find that file.", "لم أجد هذا الملف."),
    "no_helper":   ("The Mac helper isn't connected.", "مساعد الماك غير متصل."),
    "approved":    ("Approved. In this demo nothing is sent.", "تمت الموافقة. في هذا العرض لا يُرسل شيء."),
}

ARABIC_NAMES = {"Visitor": "الزائر", "Layla Mansour": "ليلى منصور", "Omar Khan": "عمر خان", "Karim": "كريم"}


def lang_of(said: str, heard_lang: str | None = None) -> str:
    return "ar" if heard_lang == "ar" or ARABIC.search(said or "") else "en"


def reply(outcome: str, lang: str, *, file: str | None = None, person: str = "", to: str = "", n: int = 2) -> str:
    en, ar = TEXT[outcome]
    if lang == "ar":
        name = SPOKEN[file][1] if file else ""
        return ar.format(file=name, person=ARABIC_NAMES.get(person, person),
                         to=ARABIC_NAMES.get(to, to), n=n)
    name = SPOKEN[file][0] if file else ""
    return en.format(file=name, file_cap=name[:1].upper() + name[1:], person=person, to=to, n=n)
