"""Cheap Bluetooth lamps and LED strips (the ones run by apps like BLEDOM / duoCo / Lotus Lantern, or Happy Lighting).

Two families cover most of them:
- **ELK-BLEDOM** (names ELK-BLE…, MELK…): write characteristic FFF3.
- **Triones / Happy Lighting** (names Triones…, LEDBLE…, QHM-…): write characteristic FFD9.
Clones vary: if a lamp doesn't react, read its services and adjust here.

These lamps can't report back reliably, so the helper uses the Mac camera (before and after) as proof.
"""
from __future__ import annotations

ELK_CHAR = "0000fff3-0000-1000-8000-00805f9b34fb"
TRIONES_CHAR = "0000ffd9-0000-1000-8000-00805f9b34fb"

COLOURS = {"red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255), "white": (255, 255, 255),
           "warm": (255, 147, 41), "yellow": (255, 200, 0), "purple": (160, 0, 255), "pink": (255, 60, 150),
           "orange": (255, 100, 0)}
COLOURS_AR = {"أحمر": "red", "احمر": "red", "أخضر": "green", "اخضر": "green", "أزرق": "blue", "ازرق": "blue",
              "أبيض": "white", "ابيض": "white", "دافئ": "warm", "أصفر": "yellow", "اصفر": "yellow",
              "بنفسجي": "purple", "وردي": "pink", "برتقالي": "orange"}
LEVELS = (10, 25, 50, 75, 100)  # brightness steps for brighter / dimmer


class LampError(ValueError):
    pass


def colour_name(text: str | None) -> str | None:
    t = (text or "").strip().lower()
    return t if t in COLOURS else COLOURS_AR.get(t)


def family_of(name: str, services=()) -> str:
    services = {s.lower() for s in services}
    if (name or "").lower().startswith(("triones", "ledble", "qhm-", "dream~", "lednet")) or \
            "0000ffd5-0000-1000-8000-00805f9b34fb" in services:
        return "triones"
    return "elk"


def command(family: str, action: str, colour: str | None = None, level: int = 100) -> tuple[str, bytes]:
    """(characteristic, bytes) for one action."""
    if family == "triones":
        char = TRIONES_CHAR
        if action == "on":
            return char, bytes([0xCC, 0x23, 0x33])
        if action == "off":
            return char, bytes([0xCC, 0x24, 0x33])
        if action == "colour":
            r, g, b = COLOURS[_colour(colour)]
            return char, bytes([0x56, r, g, b, 0x00, 0xF0, 0xAA])
        if action in ("brighter", "dimmer"):  # no brightness command: white scaled to the level
            v = round(255 * level / 100)
            return char, bytes([0x56, v, v, v, 0x00, 0xF0, 0xAA])
    else:
        char = ELK_CHAR
        if action == "on":
            return char, bytes([0x7E, 0x04, 0x04, 0xF0, 0x00, 0x01, 0xFF, 0x00, 0xEF])
        if action == "off":
            return char, bytes([0x7E, 0x04, 0x04, 0x00, 0x00, 0x00, 0xFF, 0x00, 0xEF])
        if action == "colour":
            r, g, b = COLOURS[_colour(colour)]
            return char, bytes([0x7E, 0x07, 0x05, 0x03, r, g, b, 0x10, 0xEF])
        if action in ("brighter", "dimmer"):
            return char, bytes([0x7E, 0x04, 0x01, max(1, min(100, level)), 0x01, 0xFF, 0xFF, 0x00, 0xEF])
    raise LampError(f"a lamp can't {action}")


def _colour(colour: str | None) -> str:
    c = colour_name(colour)
    if not c:
        raise LampError(f"pick a colour: {', '.join(COLOURS)}")
    return c


def next_level(current: int, action: str) -> int:
    if action == "brighter":
        return next((x for x in LEVELS if x > current), 100)
    return next((x for x in reversed(LEVELS) if x < current), 10)


class BleLamp:
    def __init__(self, adapter, address: str, family: str):
        self.adapter, self.address, self.family = adapter, address, family

    async def do(self, action: str, colour: str | None = None, level: int = 100) -> None:
        char, data = command(self.family, action, colour, level)
        await self.adapter.write(self.address, char, data)
