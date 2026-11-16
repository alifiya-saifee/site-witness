"""What the agent says back, out loud, after each command. One short sentence per outcome, in the language
the person used (Arabic written by hand, not machine-translated). File names are said in short spoken form."""
from __future__ import annotations

import re

from . import devices as device_list

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
    # devices
    "on":          ("Done. {Device} is on.", "تم. {device} يعمل الآن."),
    "off":         ("Done. {Device} is off.", "تم. أطفأتُ {device}."),
    "switch_unseen": ("I switched it, but the camera couldn't see the change.", "نفّذتُ الأمر، لكن الكاميرا لم ترَ التغيير."),
    "switch_failed": ("Sorry, I couldn't reach {device}.", "عذرًا، لم أتمكن من الوصول إلى {device}."),
    "refused_device": ("Sorry, {person} isn't allowed to use {device}.", "عذرًا، {person} لا يملك صلاحية استخدام {device}."),
    "approve_device": ("Switch {device} {action}? Tap Approve.", "هل {action} {device}؟ اضغط موافقة."),
    "choose_device": ("I found {n} devices. Which one do you mean?", "وجدت {n} أجهزة. أيّها تقصد؟"),
    "no_device":   ("There's no {kind} added yet. Add it on the Mac with Scan my Wi-Fi.",
                    "لم تتم إضافة {kind} بعد. أضِف الجهاز من الماك عبر «فحص الشبكة»."),
    # TV
    "volume_up":   ("Turned the volume up, from {before} to {after}.", "رفعتُ الصوت من {before} إلى {after}."),
    "volume_down": ("Turned the volume down, from {before} to {after}.", "خفّضتُ الصوت من {before} إلى {after}."),
    "muted":       ("Done. {Device} is muted.", "تم. كتمتُ صوت {device}."),
    "unmuted":     ("Sound is back on {device}.", "أعدتُ الصوت إلى {device}."),
    "app":         ("{app} is open on {device}.", "تم فتح {app} على {device}."),
    "hdmi":        ("I switched the input on {device}.", "غيّرتُ المدخل على {device}."),
    "tv_unsure":   ("I sent it, but {device} didn't confirm it.", "أرسلتُ الأمر، لكن {device} لم يؤكده."),
    "tv_failed":   ("Sorry, I couldn't get {device} to do that. The page says why.",
                    "عذرًا، لم أتمكن من تنفيذ ذلك على {device}. التفاصيل على الصفحة."),
    "tv_paired":   ("{Device} is added, and it allowed Diwan.", "تمت إضافة {device}، وقد سمح لـ Diwan بالتحكم."),
    # printer
    "approve_print": ("Print {file} on {device}? Tap Approve.", "هل أطبع {file} على {device}؟ اضغط موافقة."),
    "printed":     ("Done. {File} has printed.", "تم. طُبع {file}."),
    "print_waiting": ("It's at the printer, but it hasn't finished yet.", "أُرسل إلى الطابعة، لكنها لم تنتهِ بعد."),
    "printer_problem": ("The printer says: {problem}.", "الطابعة تقول: {problem}."),
    "print_failed": ("Sorry, the printer couldn't print it.", "عذرًا، لم تتمكن الطابعة من الطباعة."),
}

KIND_EN = {"plug": "lamp", "tv": "TV", "printer": "printer"}
KIND_AR = {"plug": "المصباح", "tv": "التلفزيون", "printer": "الطابعة"}
PROBLEM_AR = {"out of paper": "نفد الورق", "paper jam": "انحشار الورق", "out of toner": "نفد الحبر",
              "a door is open": "باب مفتوح", "a cover is open": "غطاء مفتوح", "offline": "غير متصلة",
              "paused": "متوقفة مؤقتًا"}

ARABIC_NAMES = {"Visitor": "الزائر", "Layla Mansour": "ليلى منصور", "Omar Khan": "عمر خان", "Karim": "كريم"}


def lang_of(said: str, heard_lang: str | None = None) -> str:
    return "ar" if heard_lang == "ar" or ARABIC.search(said or "") else "en"


ARABIC_ACTION = {"on": "أشغّل", "off": "أطفئ"}


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def reply(outcome: str, lang: str, *, file: str | None = None, person: str = "", to: str = "", n: int = 2,
          device=None, action: str = "on", kind: str = "", before="", after="", app: str = "",
          problem: str = "") -> str:
    """device: a Device or a device id. Numbers and names are filled in; nothing is left as {…}."""
    en, ar = TEXT[outcome]
    dev = device_list.by_id(device) if isinstance(device, str) else device
    if lang == "ar":
        name = SPOKEN[file][1] if file else ""
        problems = "، ".join(PROBLEM_AR.get(p.strip(), p.strip()) for p in problem.split(",")) if problem else ""
        return ar.format(file=name, File=name, person=ARABIC_NAMES.get(person, person), to=ARABIC_NAMES.get(to, to),
                         n=n, device=dev.name_ar if dev else "الجهاز", action=ARABIC_ACTION.get(action, action),
                         kind=KIND_AR.get(kind, kind), before=before, after=after,
                         app={"YouTube": "يوتيوب", "Netflix": "نتفلكس"}.get(app, app), problem=problems)
    name = SPOKEN[file][0] if file else ""
    dname = dev.name if dev else "the device"
    return en.format(file=name, File=cap(name), person=person, to=to, n=n, device=dname, Device=cap(dname),
                     action=action, kind=KIND_EN.get(kind, kind), before=before, after=after, app=app, problem=problem)
