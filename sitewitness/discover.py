"""Scan the Wi-Fi: what is here, and which of it Diwan has a connector for.

It only listens and asks devices who they are; it never controls anything. A person then picks what to add.
- Listens for a few seconds to the announcements devices make on the network (mDNS / Bonjour, via zeroconf).
- Samsung TVs are confirmed by asking the TV itself (GET :8001/api/v2/): model, its own id, Wi-Fi MAC.
- Printers come from IPP announcements; their id is the printer's own UUID.
- Tapo / Kasa plugs come from kasa's own discovery.
- Everything else is listed as "found, no connector yet".
Devices are known by their own id, not their IP address, so one device announcing twice is one row.
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import socket
import time

import httpx

SERVICE_TYPES = {
    "_airplay._tcp.local.": "AirPlay", "_raop._tcp.local.": "AirPlay speaker", "_googlecast._tcp.local.": "Chromecast",
    "_ipp._tcp.local.": "Printer", "_hap._tcp.local.": "HomeKit", "_matter._tcp.local.": "Matter",
    "_hue._tcp.local.": "Philips Hue", "_shelly._tcp.local.": "Shelly", "_spotify-connect._tcp.local.": "Spotify",
    "_sonos._tcp.local.": "Sonos", "_androidtvremote2._tcp.local.": "Android TV", "_home-assistant._tcp.local.": "Home Assistant",
}


def key_for(kind: str, uid: str) -> str:
    return f"{kind}-{hashlib.sha1(uid.encode()).hexdigest()[:8]}"


def browse(seconds: float = 6) -> list[dict]:
    """[{type, name, address, port, props}] heard on the network."""
    from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

    heard: dict[tuple, dict] = {}

    class Listener(ServiceListener):
        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name, timeout=1500)
            if not info:
                return
            props = {k.decode(errors="ignore"): (v or b"").decode(errors="ignore") for k, v in info.properties.items()}
            for addr in info.parsed_addresses():
                if ":" not in addr:  # IPv4 only
                    heard[(type_, name, addr)] = {"type": type_, "name": name.split("." + type_)[0].split("._")[0],
                                                  "address": addr, "port": info.port, "props": props}

        update_service = add_service

        def remove_service(self, zc, type_, name):
            pass

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, list(SERVICE_TYPES), Listener())
        time.sleep(seconds)
    finally:
        zc.close()
    return list(heard.values())


def probe_samsung(address: str) -> dict | None:
    try:
        d = httpx.get(f"http://{address}:8001/api/v2/", timeout=1.5).json()
    except Exception:
        return None
    dev = d.get("device") or {}
    if "samsung" not in str(dev.get("type", "")).lower() and dev.get("OS") != "Tizen":
        return None
    return {"uid": d.get("id") or dev.get("id"), "label": html.unescape(dev.get("name") or d.get("name") or "Samsung TV"),
            "model": dev.get("modelName", ""), "mac": dev.get("wifiMac"), "power": dev.get("PowerState", "on")}


def kasa_plugs(seconds: int = 4) -> list[dict]:
    try:
        from kasa import Discover
        found = asyncio.run(asyncio.wait_for(Discover.discover(discovery_timeout=seconds), seconds + 3))
    except Exception:
        return []
    out = []
    for addr, dev in found.items():
        mac = getattr(dev, "mac", None) or addr
        out.append({"uid": str(mac), "address": addr, "label": getattr(dev, "alias", None) or "Smart plug",
                    "model": getattr(dev, "model", "")})
    return out


def own_addresses() -> set[str]:
    out = {"127.0.0.1"}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1)); out.add(s.getsockname()[0]); s.close()
    except OSError:
        pass
    return out


def classify(services: list[dict], probe=probe_samsung, plugs: list[dict] = (), own: set[str] = frozenset()) -> list[dict]:
    """Sort what was heard into TVs, printers, plugs (with connectors) and the rest (no connector yet)."""
    found: dict[str, dict] = {}
    claimed: set[str] = set(own)
    for s in services:
        if s["type"] == "_ipp._tcp.local." and s["address"] not in own:
            uid = s["props"].get("UUID") or s["name"]
            k = key_for("printer", uid)
            found.setdefault(k, {"key": k, "kind": "printer", "uid": uid, "label": s["props"].get("ty") or s["name"],
                                 "model": s["props"].get("ty", ""), "address": s["address"],
                                 "path": s["props"].get("rp") or "ipp/print", "connector": True})
            claimed.add(s["address"])
    for addr in sorted({s["address"] for s in services} - claimed):
        info = probe(addr)
        if info and info.get("uid"):
            k = key_for("tv", info["uid"])
            found.setdefault(k, {"key": k, "kind": "tv", "uid": info["uid"], "label": info["label"], "model": info["model"],
                                 "address": addr, "mac": info.get("mac"), "connector": True})
            claimed.add(addr)
    for p in plugs:
        k = key_for("plug", p["uid"])
        found.setdefault(k, {"key": k, "kind": "plug", "uid": p["uid"], "label": p["label"], "model": p["model"],
                             "address": p["address"], "connector": True})
        claimed.add(p["address"])
    others: dict[str, dict] = {}
    for s in services:
        if s["address"] in claimed:
            continue
        o = others.setdefault(s["address"], {"key": key_for("other", s["address"]), "kind": "other", "label": s["name"],
                                             "model": "", "address": s["address"], "what": [], "connector": False})
        what = SERVICE_TYPES.get(s["type"], s["type"])
        if what not in o["what"]:
            o["what"].append(what)
    return list(found.values()) + list(others.values())


def scan(seconds: float = 6) -> list[dict]:
    """Listen and look for plugs at the same time; never longer than about seconds + 7."""
    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(2)
    heard, plugs = pool.submit(browse, seconds), pool.submit(kasa_plugs, 4)
    try:
        plug_list = plugs.result(timeout=seconds + 7)
    except Exception:
        plug_list = []
    pool.shutdown(wait=False, cancel_futures=True)
    return classify(heard.result(timeout=seconds + 7), plugs=plug_list, own=own_addresses())
