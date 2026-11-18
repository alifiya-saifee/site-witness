"""SwitchBot Bot: a small Bluetooth arm that presses a physical switch or button (it works on things with no app).

Commands (no password set on the Bot): press 57 01 00, on 57 01 01, off 57 01 02, written to cba20002-…;
the Bot answers on cba20003-… with a status byte (1 = done). That answer is the read-back proof.
"""
from __future__ import annotations

WRITE = "cba20002-224d-11e6-9fb8-0002a5d5c51b"
NOTIFY = "cba20003-224d-11e6-9fb8-0002a5d5c51b"
COMMANDS = {"press": bytes([0x57, 0x01, 0x00]), "on": bytes([0x57, 0x01, 0x01]), "off": bytes([0x57, 0x01, 0x02])}
STATUS = {1: "done", 3: "busy", 5: "it has a password set (remove it in the SwitchBot app)", 11: "battery too low"}


class SwitchBotError(RuntimeError):
    pass


class SwitchBot:
    def __init__(self, adapter, address: str):
        self.adapter, self.address = adapter, address

    async def do(self, action: str) -> dict:
        """{"confirmed": bool, "detail": str}"""
        if action not in COMMANDS:
            raise SwitchBotError(f"a SwitchBot can't {action}")
        reply = await self.adapter.write(self.address, WRITE, COMMANDS[action], notify=NOTIFY)
        if not reply:
            return {"confirmed": False, "detail": f"Sent {action}, but the Bot didn't answer"}
        code = reply[0]
        if code == 1:
            return {"confirmed": True, "detail": f"The Bot did {action} and said so"}
        return {"confirmed": False, "detail": f"The Bot said: {STATUS.get(code, f'code {code}')}"}
