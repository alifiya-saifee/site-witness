"""Text to speech for the agent's replies.

- Mac voice (default, always there): macOS `say` (Samantha for English, Majed for Arabic) and `afconvert` to
  .m4a, which phones and browsers play. Built into macOS: no key, nothing leaves the Mac.
- NVIDIA magpie-tts-zeroshot (English only, opt-in): speaks in the owner's own voice, copied from a short sample
  they recorded with consent. Used only when ALL of these hold: SW_TTS=magpie, NVIDIA_API_KEY and
  SW_MAGPIE_FUNCTION_ID are set, the reply is English, and run/voice-sample.wav exists. Any error, slowness or
  rate limit falls back to the Mac voice, and the result says so. Sends the reply text and the voice sample
  to NVIDIA.
"""
from __future__ import annotations

import concurrent.futures
import io
import os
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

from .records import ROOT

SAMPLE = ROOT / "run" / "voice-sample.wav"
MAC_VOICES = {"en": "Samantha", "ar": "Majed"}
MAGPIE_URI = "grpc.nvcf.nvidia.com:443"
MAGPIE_TIMEOUT = 15.0
MAGPIE_PER_MINUTE = 35  # the key allows 40 requests a minute; stay under it

_cache: dict[tuple, tuple[bytes, str, str]] = {}
_calls: list[float] = []
_lock = threading.Lock()


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=30)


def to_m4a(src: Path) -> bytes:
    out = src.with_suffix(".m4a")
    r = run(["afconvert", "-f", "m4af", "-d", "aac", str(src), str(out)])
    if r.returncode != 0 or not out.exists():
        raise RuntimeError("afconvert failed")
    return out.read_bytes()


def mac_say(text: str, lang: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        aiff = Path(tmp) / "reply.aiff"
        r = run(["say", "-v", MAC_VOICES.get(lang, "Samantha"), "-o", str(aiff), text])
        if r.returncode != 0 or not aiff.exists():
            raise RuntimeError("say failed")
        return to_m4a(aiff)


def magpie_ready(lang: str) -> str | None:
    """None if magpie may be used for this reply, else the reason it isn't."""
    if os.environ.get("SW_TTS", "").lower() != "magpie":
        return "off"
    if lang != "en":
        return "magpie speaks English only"
    if not os.environ.get("NVIDIA_API_KEY") or not os.environ.get("SW_MAGPIE_FUNCTION_ID"):
        return "no NVIDIA key or function id"
    if not SAMPLE.exists():
        return "no voice sample recorded"
    return None


def _rate_ok() -> bool:
    now = time.monotonic()
    with _lock:
        _calls[:] = [t for t in _calls if now - t < 60]
        if len(_calls) >= MAGPIE_PER_MINUTE:
            return False
        _calls.append(now)
        return True


def magpie_call(text: str) -> bytes:
    """One call to NVIDIA's hosted magpie-tts-zeroshot. Returns 16-bit mono PCM at 22.05 kHz."""
    import riva.client
    auth = riva.client.Auth(uri=MAGPIE_URI, use_ssl=True, metadata_args=[
        ["function-id", os.environ["SW_MAGPIE_FUNCTION_ID"]],
        ["authorization", f"Bearer {os.environ['NVIDIA_API_KEY']}"]])
    tts = riva.client.SpeechSynthesisService(auth)
    resp = tts.synthesize(text, language_code="en-US", sample_rate_hz=22050,
                          zero_shot_audio_prompt_file=SAMPLE, zero_shot_quality=20)
    return resp.audio


def magpie(text: str) -> bytes:
    if not _rate_ok():
        raise RuntimeError("rate limit: too many replies this minute")
    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        pcm = ex.submit(magpie_call, text).result(timeout=MAGPIE_TIMEOUT)
    if not pcm:
        raise RuntimeError("empty audio")
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "reply.wav"
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050); w.writeframes(pcm)
        wav.write_bytes(buf.getvalue())
        return to_m4a(wav)


def speak(text: str, lang: str) -> tuple[bytes, str, str]:
    """-> (m4a audio, engine "magpie" | "mac", note). Never raises for magpie trouble; the Mac voice takes over."""
    why_not = magpie_ready(lang)
    key = (text, lang, why_not is None, SAMPLE.stat().st_mtime if SAMPLE.exists() else 0)
    if key in _cache:
        return _cache[key]
    result = None
    if why_not is None:
        try:
            result = (magpie(text), "magpie", "your voice (NVIDIA magpie)")
        except Exception as e:  # noqa: BLE001 - any trouble: fall back, and say why
            why_not = f"magpie failed: {type(e).__name__}: {str(e)[:120]}"
    if result is None:
        result = (mac_say(text, lang), "mac", "Mac voice" + ("" if why_not in (None, "off") else f" ({why_not})"))
    if not (why_not or "").startswith("magpie failed"):  # a one-off magpie failure must not stick in the cache
        _cache[key] = result
    return result
