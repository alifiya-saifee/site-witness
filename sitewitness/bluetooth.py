"""Bluetooth Low Energy: find what's near, and talk to the few kinds we have connectors for.

Two ways to reach a Bluetooth device:
- **this Mac** (its own Bluetooth, about 10 m), through the library `bleak`;
- **relays**: small ESP32 boards running ESPHome's "Bluetooth Proxy", one per far room. Each listens to Bluetooth
  around it and passes it to the Mac over Wi-Fi (library `aioesphomeapi`). Relays are kept in run/relays.json
  (never committed); a relay's encryption key is never logged, shown or sent anywhere but to that relay.

A scan only listens: nothing is connected to or changed. What can be controlled:
- lamps / LED strips (ELK-BLEDOM and Triones / Happy Lighting families)  -> connectors/ble_lamp.py
- SwitchBot Bot (presses a physical switch)                               -> connectors/switchbot.py
- Sphero robots (BOLT, Mini, SPRK+, RVR)                                    -> connectors/sphero.py
Anything else is listed as "found, can't control yet".

The libraries are loaded only when Bluetooth is really used, so the rest of the app works without them.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field

from .records import ROOT

RELAYS_FILE = ROOT / "run" / "relays.json"

LAMP_NAMES = re.compile(r"^(ELK-BLE|ELK-BULB|ELK-LAMPL|MELK|LEDBLE|Triones|QHM-|Dream~|BRGLED|LEDnet)", re.I)
LAMP_SERVICES = {"0000fff0-0000-1000-8000-00805f9b34fb", "0000ffd5-0000-1000-8000-00805f9b34fb",
                 "0000ffe5-0000-1000-8000-00805f9b34fb"}
SWITCHBOT_SERVICE = "cba20d00-224d-11e6-9fb8-0002a5d5c51b"
SWITCHBOT_DATA = {"00000d00-0000-1000-8000-00805f9b34fb", "0000fd3d-0000-1000-8000-00805f9b34fb"}
SPHERO_NAMES = re.compile(r"^(SB-|SM-|SK-|RV-|SP-)", re.I)


class BluetoothError(RuntimeError):
    pass


@dataclass
class Advert:
    """One device heard: its id (macOS gives its own id, not the hardware address), name, signal, what it says."""
    address: str
    name: str = ""
    rssi: int = -100
    services: tuple = ()
    service_data: dict = field(default_factory=dict)
    via: str = "mac"          # "mac" or a relay id
    via_name: str = "this Mac"


def guess(ad: Advert) -> tuple[str, str]:
    """(kind, label) for an advert. kind: ble_lamp | switchbot | sphero | other."""
    services = {s.lower() for s in ad.services}
    data = {k.lower() for k in ad.service_data}
    if SWITCHBOT_SERVICE in services or data & SWITCHBOT_DATA:
        return "switchbot", "SwitchBot Bot"
    if SPHERO_NAMES.match(ad.name or ""):
        return "sphero", "Sphero robot"
    if LAMP_NAMES.match(ad.name or "") or services & LAMP_SERVICES:
        return "ble_lamp", "Bluetooth lamp / LED strip"
    return "other", ad.name or "Unnamed Bluetooth device"


def key_for(address: str) -> str:
    return "bt-" + hashlib.sha1(address.lower().encode()).hexdigest()[:8]


def rows(adverts: list[Advert]) -> list[dict]:
    """One row per device (the strongest signal wins when the Mac and a relay both heard it), for the page."""
    best: dict[str, Advert] = {}
    for ad in adverts:
        old = best.get(ad.address.lower())
        if old is None or ad.rssi > old.rssi:
            best[ad.address.lower()] = ad
    out = []
    for ad in sorted(best.values(), key=lambda a: -a.rssi):
        kind, label = guess(ad)
        row = {"key": key_for(ad.address), "kind": "robot" if kind == "sphero" else kind, "label": label,
               "name": (ad.name or "")[:60], "address": ad.address, "rssi": ad.rssi, "via": ad.via,
               "via_name": ad.via_name, "connector": kind != "other",
               "model": {"ble_lamp": "Bluetooth lamp", "switchbot": "SwitchBot Bot", "sphero": "Sphero"}.get(kind, "")}
        if kind == "sphero":
            row |= {"sub": "sphero", "uid": ad.name}  # spherov2 finds the robot by its name
        if kind == "ble_lamp":
            from .connectors.ble_lamp import family_of
            row["path"] = family_of(ad.name, ad.services)
        out.append(row)
    return out


# ---------------- relays (ESPHome Bluetooth Proxy boards) ----------------

def load_relays() -> list[dict]:
    try:
        return [r for r in json.loads(RELAYS_FILE.read_text()) if r.get("id") and r.get("host")]
    except (OSError, ValueError):
        return []


def public_relays() -> list[dict]:
    """Relays for the page: never the key."""
    return [{"id": r["id"], "name": r["name"], "host": r["host"], "has_key": bool(r.get("key"))} for r in load_relays()]


def add_relay(name: str, host: str, key: str = "") -> dict:
    name = re.sub(r"[^\w\s'-]", "", str(name or "")).strip()[:40] or "Relay"
    host = str(host or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,100}", host):
        raise BluetoothError("Type the relay's IP address or name, e.g. kitchen-proxy.local")
    key = str(key or "").strip()
    if key and not re.fullmatch(r"[A-Za-z0-9+/]{43}=", key):
        raise BluetoothError("The encryption key is the 44-character key from the relay's ESPHome page (or leave it empty)")
    row = {"id": "relay-" + uuid.uuid4().hex[:6], "name": name, "host": host, "key": key}
    rows_ = [r for r in load_relays() if r["host"] != host] + [row]
    RELAYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RELAYS_FILE.write_text(json.dumps(rows_, indent=1))
    RELAYS_FILE.chmod(0o600)
    return {k: row[k] for k in ("id", "name", "host")}


def remove_relay(relay_id: str) -> bool:
    rows_ = load_relays()
    left = [r for r in rows_ if r["id"] != relay_id]
    RELAYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    RELAYS_FILE.write_text(json.dumps(left, indent=1))
    return len(left) != len(rows_)


# ---------------- adapters: the Mac's own Bluetooth, and relays ----------------

class MacAdapter:
    """The Mac's own Bluetooth, through bleak."""
    id, name = "mac", "this Mac"

    async def scan(self, seconds: float) -> list[Advert]:
        try:
            from bleak import BleakScanner
        except ImportError as e:
            raise BluetoothError("the Bluetooth library isn't installed yet (pip install bleak)") from e
        found = await BleakScanner.discover(timeout=seconds, return_adv=True)
        out = []
        for dev, adv in found.values():
            out.append(Advert(address=dev.address, name=adv.local_name or dev.name or "", rssi=adv.rssi,
                              services=tuple(adv.service_uuids or ()), service_data=dict(adv.service_data or {})))
        return out

    async def write(self, address: str, char: str, data: bytes, notify: str | None = None, wait: float = 3.0) -> bytes | None:
        """Write one command; with notify, wait for the device's answer on that characteristic."""
        try:
            from bleak import BleakClient
        except ImportError as e:
            raise BluetoothError("the Bluetooth library isn't installed yet (pip install bleak)") from e
        reply: asyncio.Future = asyncio.get_running_loop().create_future()
        async with BleakClient(address, timeout=10) as client:
            if notify:
                await client.start_notify(notify, lambda _c, d: reply.done() or reply.set_result(bytes(d)))
            await client.write_gatt_char(char, data, response=bool(notify))
            if notify:
                try:
                    return await asyncio.wait_for(reply, wait)
                except asyncio.TimeoutError:
                    return None
        return None


class RelayAdapter:
    """An ESPHome Bluetooth Proxy on the Wi-Fi, through aioesphomeapi.
    Note: written against aioesphomeapi's Bluetooth API; it is checked with a fake here and must be tried with a real
    relay before relying on it."""

    def __init__(self, relay: dict, client_factory=None):
        self.id, self.name, self.host, self._key = relay["id"], relay["name"], relay["host"], relay.get("key") or None
        self._factory = client_factory

    def _client(self):
        if self._factory:
            return self._factory(self.host, self._key)
        try:
            from aioesphomeapi import APIClient
        except ImportError as e:
            raise BluetoothError("the relay library isn't installed yet (pip install aioesphomeapi)") from e
        return APIClient(self.host, 6053, None, noise_psk=self._key)

    async def scan(self, seconds: float) -> list[Advert]:
        cli = self._client()
        heard: dict[str, Advert] = {}
        try:
            await cli.connect(login=True)

            def on_adv(a):
                addr = ":".join(f"{(a.address >> s) & 0xff:02X}" for s in range(40, -8, -8))
                heard[addr] = Advert(address=addr, name=a.name or "", rssi=a.rssi, services=tuple(a.service_uuids or ()),
                                     service_data=dict(a.service_data or {}), via=self.id, via_name=f"relay: {self.name}")
            unsub = cli.subscribe_bluetooth_le_advertisements(on_adv)
            await asyncio.sleep(seconds)
            if callable(unsub):
                unsub()
        except BluetoothError:
            raise
        except Exception as e:
            raise BluetoothError(f"couldn't reach the relay {self.name} ({type(e).__name__})") from e
        finally:
            try:
                await cli.disconnect()
            except Exception:
                pass
        return list(heard.values())

    async def write(self, address: str, char: str, data: bytes, notify: str | None = None, wait: float = 3.0) -> bytes | None:
        cli = self._client()
        addr = int(address.replace(":", ""), 16)
        try:
            await cli.connect(login=True)
            connected = asyncio.get_running_loop().create_future()
            await cli.bluetooth_device_connect(addr, lambda ok, mtu, err: connected.done() or connected.set_result(ok),
                                               timeout=10)
            if not await asyncio.wait_for(connected, 12):
                raise BluetoothError("the relay couldn't connect to the device")
            services = await cli.bluetooth_gatt_get_services(addr)
            handles = {c.uuid.lower(): c.handle for s in services.services for c in s.characteristics}
            if char.lower() not in handles:
                raise BluetoothError("the device doesn't have the expected Bluetooth service")
            reply: asyncio.Future = asyncio.get_running_loop().create_future()
            if notify and notify.lower() in handles:
                await cli.bluetooth_gatt_start_notify(addr, handles[notify.lower()],
                                                      lambda h, d: reply.done() or reply.set_result(bytes(d)))
            await cli.bluetooth_gatt_write(addr, handles[char.lower()], data, bool(notify))
            if notify:
                try:
                    return await asyncio.wait_for(reply, wait)
                except asyncio.TimeoutError:
                    return None
            return None
        except BluetoothError:
            raise
        except Exception as e:
            raise BluetoothError(f"couldn't use the device through the relay {self.name} ({type(e).__name__})") from e
        finally:
            try:
                await cli.bluetooth_device_disconnect(addr)
                await cli.disconnect()
            except Exception:
                pass


def adapters(mac=None, relay_factory=None) -> list:
    """The Mac first, then every relay (read fresh: relays can be added or removed while running)."""
    return [mac or MacAdapter()] + [RelayAdapter(r, relay_factory) for r in load_relays()]


def adapter_for(via: str | None, all_adapters: list):
    """The adapter a device was found through (the strongest signal then); the Mac if that relay is gone."""
    return next((a for a in all_adapters if a.id == (via or "mac")), all_adapters[0])


async def scan(seconds: float = 8, all_adapters=None) -> tuple[list[dict], list[str]]:
    """(rows, problems): listen through every adapter at once. A relay that can't be reached is a problem, not a
    failure of the whole scan."""
    all_adapters = all_adapters if all_adapters is not None else adapters()
    results = await asyncio.gather(*(a.scan(seconds) for a in all_adapters), return_exceptions=True)
    heard, problems = [], []
    for a, r in zip(all_adapters, results):
        if isinstance(r, Exception):
            problems.append(f"{a.name}: {r}")
        else:
            heard.extend(r)
    return rows(heard), problems
