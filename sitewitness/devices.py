"""Devices: the things the agent may control, who may use them, and what each one may do.

Like Records for files: the agent can only ever touch a device on this list, and only with the actions its kind
allows. Nothing is controlled just because it is on the Wi-Fi: a person adds each device on the Mac (after a scan),
with a name, a room and who may use it. Added devices live in run/devices.json (never committed).

- Plug: on / off. The meeting-room lamp is a Tapo plug when SW_PLUG=tapo is set, otherwise a pretend lamp
  that only shows while no real device has been added.
- TV (Samsung): on, off, volume up/down, mute, YouTube, Netflix, HDMI input.
- Printer (IPP): print a file from Records. Printing always waits for an Approve tap (paper; can't be undone).
- Robot (a Roborock vacuum, or a ROS 2 robot via rosbridge): every movement waits for an Approve tap;
  "stop" never does and always goes first. Rooms and spots come from the robot (or the person adding it).
  A pretend vacuum and a pretend ROS robot stand in until a real one of that kind is added.
- risky=True (heats or moves, e.g. an oven): always waits for an Approve tap.

All names here are made up (sample data).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .connectors.plug import PlugError, PretendPlug, TapoPlug  # noqa: F401  (re-exported)
from .records import PEOPLE, ROOT

RUN_DIR = ROOT / "run"
ADDED_FILE = RUN_DIR / "devices.json"
PRETEND_FILE = RUN_DIR / "pretend-plug.json"

KIND_ACTIONS = {
    "plug": ("on", "off"),
    "tv": ("on", "off", "volume_up", "volume_down", "mute", "app:youtube", "app:netflix", "hdmi", "pair"),
    "printer": ("print",),
}
ROBOT_ACTIONS = {"vacuum": ("stop", "pause", "dock", "start", "clean"), "ros": ("stop", "dock", "goto")}
KIND_WORDS = {
    "plug": ("lamp", "light", "lights", "plug", "المصباح", "مصباح", "الضوء", "ضوء", "الاضاءة", "الإضاءة", "اللمبة", "لمبة"),
    "tv": ("tv", "t v", "television", "telly", "screen", "التلفزيون", "تلفزيون", "التلفاز", "تلفاز", "الشاشة", "شاشة"),
    "printer": ("printer", "الطابعة", "طابعة"),
    "robot": ("robot", "vacuum", "hoover", "roborock", "الروبوت", "روبوت", "المكنسة", "مكنسة"),
}
KIND_AR = {"plug": "المصباح", "tv": "التلفزيون", "printer": "الطابعة", "robot": "الروبوت"}
ROLES = tuple(sorted({p["role"] for p in PEOPLE.values()}))


@dataclass(frozen=True)
class Device:
    id: str
    name: str                # how it is said: "the meeting-room lamp"
    name_ar: str
    room: str
    kind: str                # plug | tv | printer
    words: tuple[str, ...]   # what a person might call it (English and Arabic)
    roles: tuple[str, ...]   # roles allowed to use it
    risky: bool = False      # heats or moves: always needs an Approve tap
    address: str | None = None
    uid: str | None = None   # the device's own id (not its IP, which can change)
    mac: str | None = None   # for waking a TV
    path: str | None = None  # a printer's IPP path
    model: str = ""
    sub: str = ""            # robots: "vacuum" | "ros"
    places: tuple = ()       # robots: ((name, alias, …), …) rooms or spots it knows
    spots: tuple = ()        # ROS: ((name, x, y, heading), …) on the robot's map
    port: int | None = None  # ROS: rosbridge port

    @property
    def actions(self) -> tuple[str, ...]:
        return ROBOT_ACTIONS[self.sub] if self.kind == "robot" else KIND_ACTIONS[self.kind]

    @property
    def needs_tap(self) -> bool:
        return self.risky or self.kind in ("printer", "robot")

    def needs_tap_for(self, action: str) -> bool:
        """Stop is never held up by a tap; every other robot action is."""
        return self.needs_tap and not (self.kind == "robot" and action == "stop")

    @property
    def place_names(self) -> tuple[str, ...]:
        return tuple(p[0] for p in self.places)

    def place(self, name: str | None) -> str | None:
        """The place's own name for any of its names (Arabic too), or None."""
        n = (name or "").strip().lower()
        return next((p[0] for p in self.places if n in (a.lower() for a in p)), None)


# "النور" (light) is left out on purpose: it is also the Al Noor building's name.
LAMP = Device("room-lamp", "the meeting-room lamp", "مصباح غرفة الاجتماعات", "Meeting room", "plug",
              KIND_WORDS["plug"], ("owner", "broker"))
VACUUM_ROOMS = (("Kitchen", "المطبخ"), ("Living room", "غرفة المعيشة", "الصالة"), ("Office", "المكتب"))
ROS_SPOTS = (("Meeting room", 4.0, 2.0, 0.0), ("Reception", 0.5, 6.0, 1.57), ("Dock", 0.0, 0.0, 0.0))
ROS_AR = {"Meeting room": ("غرفة الاجتماعات",), "Reception": ("الاستقبال",), "Dock": ("محطة الشحن",)}
PRETEND_VACUUM = Device("robot-vacuum-pretend", "the robot vacuum", "المكنسة الروبوت", "Home", "robot",
                        KIND_WORDS["robot"] + tuple(a.lower() for p in VACUUM_ROOMS for a in p), ("owner", "broker"),
                        sub="vacuum", places=VACUUM_ROOMS, model="pretend")
PRETEND_ROS = Device("robot-ros-pretend", "the office robot", "روبوت المكتب", "Office", "robot",
                     ("office robot", "robot", "الروبوت", "روبوت", "روبوت المكتب") +
                     tuple(a.lower() for s in ROS_SPOTS for a in (s[0], *ROS_AR[s[0]])), ("owner", "broker"),
                     sub="ros", places=tuple((s[0], *ROS_AR[s[0]]) for s in ROS_SPOTS), spots=ROS_SPOTS,
                     model="pretend")
PRETENDS = (PRETEND_VACUUM.id, PRETEND_ROS.id)


def tapo_settings(env=os.environ) -> tuple[str, str, str] | None:
    vals = env.get("SW_PLUG_HOST"), env.get("TAPO_USERNAME"), env.get("TAPO_PASSWORD")
    return vals if env.get("SW_PLUG") == "tapo" and all(vals) else None


def plug_from_env(env=os.environ):
    """The lamp's plug: Tapo if all its settings are there, otherwise the pretend one."""
    s = tapo_settings(env)
    return TapoPlug(*s) if s else PretendPlug(PRETEND_FILE)


def plug_kind(env=os.environ) -> str:
    return "tapo" if tapo_settings(env) else "pretend"


# ---------------- added devices ----------------

def load_added(path: Path | None = None) -> list[Device]:
    try:
        rows = json.loads((path or ADDED_FILE).read_text())
    except (OSError, ValueError):
        return []
    out = []
    for r in rows:
        try:
            out.append(Device(**{**r, "words": tuple(r["words"]), "roles": tuple(r["roles"]),
                                 "places": tuple(tuple(x) for x in r.get("places", ())),
                                 "spots": tuple(tuple(x) for x in r.get("spots", ()))}))
        except (TypeError, KeyError):
            continue  # a row from an older version: skip it rather than crash
    return out


def save_added(devs: list[Device], path: Path | None = None) -> None:
    p = path or ADDED_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([asdict(d) for d in devs], ensure_ascii=False, indent=1))


def current(env=os.environ) -> tuple[Device, ...]:
    """Every device the agent may use right now."""
    added = load_added()
    lamp = [LAMP] if tapo_settings(env) or not added else []
    subs = {d.sub for d in added if d.kind == "robot"}
    pretend_robots = [r for r in (PRETEND_VACUUM, PRETEND_ROS) if r.sub not in subs]
    return tuple(lamp + added + pretend_robots)


def by_id(device_id: str | None) -> Device | None:
    return next((d for d in current() if d.id == device_id), None)


def clean(text: str, n: int) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s'&-]", "", str(text or ""))).strip()[:n]


def from_found(found: dict, name: str, room: str, roles, name_ar: str = "") -> Device:
    """A device made from one scan result and what the person typed."""
    kind = found["kind"]
    if kind not in KIND_ACTIONS and kind != "robot":
        raise ValueError("No connector for this device yet")
    name, room = clean(name, 40) or found.get("label", kind), clean(room, 30) or "Office"
    first = name.split(" ")[0]
    natural = name if first.isupper() else first.lower() + name[len(first):]  # keep "HP", lower "Living"
    spoken = natural if natural.lower().startswith("the ") else "the " + natural
    roles = tuple(r for r in ROLES if r in set(roles or ()))
    if not roles:
        raise ValueError("Tick at least one role who may use it")
    places = tuple(tuple(p) for p in found.get("places", ()))
    words = tuple(dict.fromkeys(KIND_WORDS[kind] + (name.lower(),) + tuple(a.lower() for p in places for a in p)))
    return Device(found["key"], spoken, clean(name_ar, 40) or KIND_AR[kind], room, kind, words, roles,
                  address=found.get("address"), uid=found.get("uid"), mac=found.get("mac"),
                  path=found.get("path"), model=found.get("model", ""), sub=found.get("sub", ""),
                  places=places, spots=tuple(tuple(x) for x in found.get("spots", ())), port=found.get("port"))


def may_use(person_id: str, device: Device) -> bool:
    person = PEOPLE.get(person_id)
    return bool(person) and person["role"] in device.roles
