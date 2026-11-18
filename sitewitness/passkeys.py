"""Passkeys (Face ID / fingerprint) for owner-level actions from a phone. A small WebAuthn check, ES256 only.

- Registering: the phone makes a key pair inside its secure chip; only the public key comes here
  (run/passkeys.json, never committed). Attestation is "none": we trust the phone the owner allowed on the Mac.
- Checking: the hub sends a one-time challenge; the phone signs it after Face ID; we verify the signature with the
  stored public key, and that the challenge, the site (origin and rp id) and "user verified" are all right.
- Passkeys need a real name for the hub (Tailscale gives one). On a bare IP address they can't work, and the page
  falls back to "confirm on the Mac".
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import struct
import time
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "run" / "passkeys.json"
CHALLENGE_TTL = 120   # seconds a challenge stays valid


class PasskeyError(ValueError):
    pass


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(str(text) + "=" * (-len(str(text)) % 4))
    except (ValueError, TypeError):
        raise PasskeyError("bad encoding")


# ---- a tiny CBOR reader: just what WebAuthn uses (ints, bytes, text, arrays, maps) ----

def _cbor(data: bytes, i: int = 0):
    if i >= len(data):
        raise PasskeyError("short CBOR")
    major, info = data[i] >> 5, data[i] & 31
    i += 1
    if info < 24:
        n = info
    elif info in (24, 25, 26, 27):
        size = {24: 1, 25: 2, 26: 4, 27: 8}[info]
        if i + size > len(data):
            raise PasskeyError("short CBOR")
        n = int.from_bytes(data[i:i + size], "big")
        i += size
    else:
        raise PasskeyError("unsupported CBOR")
    if major == 0:
        return n, i
    if major == 1:
        return -1 - n, i
    if major in (2, 3):
        if i + n > len(data):
            raise PasskeyError("short CBOR")
        raw = data[i:i + n]
        return (raw if major == 2 else raw.decode()), i + n
    if major == 4:
        out = []
        for _ in range(n):
            v, i = _cbor(data, i)
            out.append(v)
        return out, i
    if major == 5:
        out = {}
        for _ in range(n):
            k, i = _cbor(data, i)
            v, i = _cbor(data, i)
            out[k] = v
        return out, i
    if major == 7 and info in (20, 21, 22):
        return {20: False, 21: True, 22: None}[info], i
    raise PasskeyError("unsupported CBOR")


def _auth_data(raw: bytes, rp_id: str) -> dict:
    if len(raw) < 37:
        raise PasskeyError("short authenticator data")
    if raw[:32] != hashlib.sha256(rp_id.encode()).digest():
        raise PasskeyError("made for another site")
    flags = raw[32]
    if not flags & 0x01 or not flags & 0x04:
        raise PasskeyError("Face ID or fingerprint wasn't used")
    out = {"count": struct.unpack(">I", raw[33:37])[0]}
    if flags & 0x40:  # a new credential is attached
        if len(raw) < 55:
            raise PasskeyError("short credential")
        n = int.from_bytes(raw[53:55], "big")
        out["cred_id"] = raw[55:55 + n]
        key, _ = _cbor(raw, 55 + n)
        if not (isinstance(key, dict) and key.get(1) == 2 and key.get(3) == -7 and key.get(-1) == 1):
            raise PasskeyError("only ES256 passkeys are supported")
        x, y = key.get(-2), key.get(-3)
        if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == len(y) == 32):
            raise PasskeyError("bad public key")
        out["public"] = x + y
    return out


def _client_data(raw: bytes, kind: str, challenge: str, origin: str) -> None:
    try:
        cd = json.loads(raw)
    except ValueError:
        raise PasskeyError("bad client data")
    if cd.get("type") != kind:
        raise PasskeyError("wrong kind of answer")
    if not secrets.compare_digest(str(cd.get("challenge", "")), challenge):
        raise PasskeyError("wrong or old challenge")
    if cd.get("origin") != origin:
        raise PasskeyError("made for another site")


class Store:
    """Challenges in memory (one use, 2 minutes); public keys on disk, per person."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self.challenges: dict[str, tuple[str, str, float]] = {}  # challenge -> (session id, kind, time)
        self.keys: dict[str, dict] = {}            # credential id (b64u) -> {person, session, public, count}
        if path is not None:
            try:
                self.keys = json.loads(path.read_text())
            except (OSError, ValueError):
                self.keys = {}

    def _save(self) -> None:
        if self.path is not None:
            self.path.parent.mkdir(exist_ok=True)
            self.path.write_text(json.dumps(self.keys))
            self.path.chmod(0o600)

    def challenge(self, sid: str, kind: str) -> str:
        now = time.monotonic()
        self.challenges = {c: v for c, v in self.challenges.items() if now - v[2] < CHALLENGE_TTL}
        c = b64u(secrets.token_bytes(32))
        self.challenges[c] = (sid, kind, now)
        return c

    def _take(self, challenge: str, sid: str, kind: str) -> None:
        v = self.challenges.pop(challenge, None)
        if not v or v[0] != sid or v[1] != kind or time.monotonic() - v[2] > CHALLENGE_TTL:
            raise PasskeyError("wrong or old challenge")

    def ids_for_session(self, sid: str) -> list[str]:
        return [c for c, k in self.keys.items() if k.get("session") == sid]

    def register(self, sid: str, person: str, body: dict, rp_id: str, origin: str) -> str:
        challenge = str(body.get("challenge", ""))
        cd_raw = unb64u(body.get("clientDataJSON", ""))
        _client_data(cd_raw, "webauthn.create", challenge, origin)
        self._take(challenge, sid, "create")
        att, _ = _cbor(unb64u(body.get("attestationObject", "")))
        if not isinstance(att, dict) or not isinstance(att.get("authData"), bytes):
            raise PasskeyError("bad attestation")
        ad = _auth_data(att["authData"], rp_id)
        if "public" not in ad:
            raise PasskeyError("no key in the answer")
        cid = b64u(ad["cred_id"])
        self.keys[cid] = {"person": person, "session": sid, "public": b64u(ad["public"]), "count": ad["count"],
                          "at": time.strftime("%Y-%m-%d")}
        self._save()
        return cid

    def verify(self, sid: str, person: str, body: dict, rp_id: str, origin: str) -> None:
        challenge = str(body.get("challenge", ""))
        cd_raw = unb64u(body.get("clientDataJSON", ""))
        _client_data(cd_raw, "webauthn.get", challenge, origin)
        self._take(challenge, sid, "get")
        cid = str(body.get("id", ""))
        k = self.keys.get(cid)
        if not k or k["person"] != person or k.get("session") != sid:
            raise PasskeyError("not this phone's passkey")
        ad_raw = unb64u(body.get("authenticatorData", ""))
        ad = _auth_data(ad_raw, rp_id)
        pub = unb64u(k["public"])
        key = ec.EllipticCurvePublicNumbers(int.from_bytes(pub[:32], "big"), int.from_bytes(pub[32:], "big"),
                                            ec.SECP256R1()).public_key()
        try:
            key.verify(unb64u(body.get("signature", "")), ad_raw + hashlib.sha256(cd_raw).digest(),
                       ec.ECDSA(hashes.SHA256()))
        except InvalidSignature:
            raise PasskeyError("the signature is wrong")
        if ad["count"] and ad["count"] <= k["count"]:
            raise PasskeyError("this passkey may have been copied")
        k["count"] = ad["count"]
        self._save()

    def remove_session(self, sid: str) -> None:
        if any(k.get("session") == sid for k in self.keys.values()):
            self.keys = {c: k for c, k in self.keys.items() if k.get("session") != sid}
            self._save()
