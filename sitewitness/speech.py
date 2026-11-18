"""Speech to text on this Mac, with Whisper (faster-whisper). English and Arabic; no API key; audio never
leaves the Mac.

The browser records a short clip (webm from Chrome, mp4 from Safari) and sends it to the hub; this turns it
into text. The model loads once (about 480 MB for "small", downloaded the first time) and stays in memory.
"""
from __future__ import annotations

import os
import tempfile
import threading

MODEL_NAME = (os.environ.get("SW_WHISPER_MODEL") or "small")
MAX_BYTES = 10 * 1024 * 1024   # about a minute of speech; commands are a few seconds

_model = None
_lock = threading.Lock()


def model():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
        return _model


def warm_up() -> None:
    """Load the model in the background at start-up, so the first command isn't slow."""
    threading.Thread(target=model, daemon=True).start()


def hint() -> str:
    """Words Whisper should expect: our phrases, app names, and every website the owner saved."""
    try:
        from .sites import hint_words
        names = hint_words()
    except Exception:
        names = []
    return ("Open the Al Noor slides on my Mac. Turn up the volume on my Mac. Open YouTube, WhatsApp, Mail, Calendar. "
            "Open the Cosmique website. " + (" ".join(f"Open {n}." for n in names[:20])) + " افتح عرض النور على الماك.")[:600]


def transcribe(audio: bytes, suffix: str = ".webm") -> dict:
    """Audio clip -> {"text", "language"}. Raises ValueError for an empty or too-large clip."""
    if not audio:
        raise ValueError("No audio was recorded")
    if len(audio) > MAX_BYTES:
        raise ValueError("That recording is too long")
    with tempfile.NamedTemporaryFile(suffix=suffix) as f:
        f.write(audio)
        f.flush()
        segments, info = model().transcribe(
            f.name, beam_size=1, vad_filter=True,
            # helps Whisper spell the words this office uses (and "on my Mac", not "on Melmah")
            initial_prompt=hint(),
        )
        text = " ".join(s.text.strip() for s in segments).strip()
    return {"text": text, "language": info.language}
