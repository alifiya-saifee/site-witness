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
    # phone apps (you always press send yourself)
    "phone_app":   ("Tap Open {app}.", "اضغط فتح {app}."),
    "phone_message": ("Tap Open WhatsApp, pick the chat, then press send yourself.",
                      "اضغط فتح واتساب، اختر المحادثة، ثم اضغط إرسال بنفسك."),
    "mail_draft_phone": ("Tap Open Mail. Add who it's to, then press send yourself.",
                         "اضغط فتح البريد. أضف المستلم، ثم اضغط إرسال بنفسك."),
    "app_mac":     ("Done. {app} is open on your Mac.", "تم. فتحتُ {app} على جهاز الماك."),
    "app_draft_mac": ("A new email is ready in Mail on your Mac. Add who it's to, then press send yourself.",
                      "جهّزتُ رسالة بريد جديدة في تطبيق البريد على الماك. أضف المستلم، ثم اضغط إرسال بنفسك."),
    "whatsapp_draft_mac": ("WhatsApp Web is open on your Mac with your message typed. Pick the chat, then press send yourself.",
                           "فتحتُ واتساب ويب على الماك والرسالة مكتوبة. اختر المحادثة، ثم اضغط إرسال بنفسك."),
    "app_unconfirmed": ("I opened it, but I couldn't check it's in front.", "فتحته، لكن لم أتمكن من التحقق من أنه في المقدمة."),
    "app_failed":  ("Sorry, the Mac couldn't open {app}.", "عذرًا، لم يتمكن الماك من فتح {app}."),
    "app_not_on_phone": ("{app} can't be opened on a phone from here. Say ‘open {app} on my Mac’.",
                         "لا يمكن فتح {app} على الجوال من هنا. قل: افتح {app} على الماك."),
    "app_not_on_mac": ("The {app} app is only on your phone.", "تطبيق {app} موجود على جوالك فقط."),
    "refused_mac_app": ("Sorry, {person} isn't allowed to open apps on the Mac.",
                        "عذرًا، {person} لا يملك صلاحية فتح التطبيقات على الماك."),
    # robots
    "approve_robot": ("{Robot_action} with {device}? Tap Approve.", "هل أنفّذ: {robot_action}؟ ({device}) اضغط موافقة."),
    "robot_start": ("Done. {Device} is cleaning.", "تم. بدأ التنظيف ({device})."),
    "robot_clean": ("Done. {Device} is cleaning the {place}.", "تم. جارٍ تنظيف {place} ({device})."),
    "robot_pause": ("Paused.", "توقف مؤقتًا."),
    "robot_stop":  ("Stopped.", "توقف."),
    "robot_dock":  ("It's going back to charge.", "يعود الآن للشحن."),
    "robot_goto":  ("{Device} is at the {place}.", "{device} وصل إلى {place}."),
    "robot_on_way": ("{Device} is on its way to the {place}.", "{device} في الطريق إلى {place}."),
    "robot_stopped_early": ("{Device} stopped before getting to the {place}.", "توقف {device} قبل الوصول إلى {place}."),
    "robot_unsure": ("I sent it, but {device} didn't confirm it.", "أرسلتُ الأمر، لكن لم يصل تأكيد من {device}."),
    "robot_problem": ("{Device} says: {problem}.", "رسالة من {device}: {problem}."),
    "robot_failed": ("Sorry, I couldn't reach {device}.", "عذرًا، لم أتمكن من الوصول إلى {device}."),
    "unknown_place": ("I don't know a room called {place}. Rooms: {places}.", "لا أعرف غرفة اسمها {place}. الغرف: {places}."),
    "search_found": ("I found {n} files about {q}. Which one?", "وجدت {n} ملفات عن {q}. أيّها تقصد؟"),
    "search_one":  ("I found one file about {q}: {file}.", "وجدت ملفًا واحدًا عن {q}: {file}."),
    "search_none": ("I couldn't find a file mentioning {q}.", "لم أجد ملفًا يذكر {q}."),
    "no_folder":   ("No folder is shared for searching yet. Share one on the Mac.",
                    "لا يوجد مجلد مشترك للبحث بعد. شارك مجلدًا من الماك."),
    "file_gone":   ("That file isn't in the shared folder any more.", "هذا الملف لم يعد في المجلد المشترك."),
    "stop_all":    ("Stopping all the robots.", "أوقفتُ كل الروبوتات."),
}

ROBOT_ACTION_EN = {"start": "Start cleaning", "clean": "Clean the {place}", "pause": "Pause", "dock": "Send it home to charge",
                   "goto": "Go to the {place}", "stop": "Stop"}
ROBOT_ACTION_AR = {"start": "بدء التنظيف", "clean": "تنظيف {place}", "pause": "إيقاف مؤقت", "dock": "العودة للشحن",
                   "goto": "الذهاب إلى {place}", "stop": "إيقاف"}
PLACE_AR = {"Kitchen": "المطبخ", "Living room": "غرفة المعيشة", "Office": "المكتب", "Meeting room": "غرفة الاجتماعات",
            "Reception": "الاستقبال", "Dock": "محطة الشحن"}

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
          problem: str = "", place: str = "", places=(), title: str = "", q: str = "") -> str:
    """device: a Device or a device id. Numbers and names are filled in; nothing is left as {…}."""
    en, ar = TEXT[outcome]
    dev = device_list.by_id(device) if isinstance(device, str) else device
    if lang == "ar":
        name = SPOKEN[file][1] if file in SPOKEN else (f"«{title}»" if title else "")
        problems = "، ".join(PROBLEM_AR.get(p.strip(), p.strip()) for p in problem.split(",")) if problem else ""
        place_ar = PLACE_AR.get(place, place)
        return ar.format(file=name, File=name, person=ARABIC_NAMES.get(person, person), to=ARABIC_NAMES.get(to, to),
                         n=n, device=dev.name_ar if dev else "الجهاز", action=ARABIC_ACTION.get(action, action),
                         kind=KIND_AR.get(kind, kind), before=before, after=after,
                         app={"YouTube": "يوتيوب", "Netflix": "نتفلكس", "WhatsApp": "واتساب",
                              "Google Maps": "خرائط جوجل", "Phone": "الهاتف", "Mail": "البريد",
                              "Calendar": "التقويم"}.get(app, app), problem=problems,
                         place=place_ar, places="، ".join(PLACE_AR.get(x, x) for x in places),
                         robot_action=ROBOT_ACTION_AR.get(action, action).format(place=place_ar), q=q)
    name = SPOKEN[file][0] if file in SPOKEN else (f"“{title}”" if title else "")
    dname = dev.name if dev else "the device"
    place_en = place.lower() if place else ""
    return en.format(file=name, File=cap(name), person=person, to=to, n=n, device=dname, Device=cap(dname),
                     action=action, kind=KIND_EN.get(kind, kind), before=before, after=after, app=app, problem=problem,
                     place=place_en, places=", ".join(places),
                     Robot_action=ROBOT_ACTION_EN.get(action, action).format(place=place_en), q=q)
