"""Sphero robots over Bluetooth (BOLT, Mini, SPRK+, RVR), through the library `spherov2`.

Every move is short and capped: at most 2 seconds at half speed, then it stops by itself. (The hub also makes every
move wait for an Approve tap; Stop never waits.) The robot is found by its Bluetooth name (e.g. SB-1A2B).
"""
from __future__ import annotations

MAX_SECONDS = 2
SPEED = 128  # half of full speed (255)
HEADINGS = {"forward": 0, "right": 90, "back": 180, "left": 270}


class SpheroError(RuntimeError):
    pass


def _default_api(name: str):
    try:
        from spherov2 import scanner
        from spherov2.sphero_edu import SpheroEduAPI
    except ImportError as e:
        raise SpheroError("the Sphero library isn't installed yet (pip install spherov2)") from e
    try:
        toy = scanner.find_toy(toy_name=name)
    except Exception as e:
        raise SpheroError(f"couldn't find {name} nearby (is it awake and charged?)") from e
    return SpheroEduAPI(toy)


class Sphero:
    def __init__(self, name: str, api_factory=None):
        self.name = name
        self.api_factory = api_factory or _default_api

    def do(self, action: str, colour_rgb: tuple | None = None) -> dict:
        """Runs one action and returns {"ok", "confirmed", "state", "detail"}. Blocking (spherov2 is synchronous)."""
        api = self.api_factory(self.name)
        try:
            with api as a:
                if action == "stop":
                    a.stop_roll()
                    return {"ok": True, "confirmed": True, "state": "idle", "detail": "Stopped"}
                if action in HEADINGS:
                    a.roll(HEADINGS[action], SPEED, MAX_SECONDS)  # rolls, then stops by itself
                    a.stop_roll()
                    return {"ok": True, "confirmed": True, "state": "idle",
                            "detail": f"Rolled {action} for {MAX_SECONDS} s at half speed, then stopped"}
                if action == "spin":
                    a.spin(360, 1)
                    return {"ok": True, "confirmed": True, "state": "idle", "detail": "Spun once"}
                if action == "colour":
                    if not colour_rgb:
                        raise SpheroError("pick a colour")
                    from spherov2.types import Color
                    a.set_main_led(Color(*colour_rgb))
                    return {"ok": True, "confirmed": True, "state": "idle", "detail": "Changed its light"}
        except SpheroError:
            raise
        except Exception as e:
            raise SpheroError(f"lost the robot ({type(e).__name__})") from e
        raise SpheroError(f"a Sphero can't {action}")
