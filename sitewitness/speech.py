"""Speech to text on this Mac, with Whisper (faster-whisper). English and Arabic; no API key; audio never
leaves the Mac.

The browser records a short clip (webm from Chrome, mp4 from Safari) and sends it to the hub; this turns it
into text. The model loads once (about 480 MB for "small", downloaded the first time) and stays in memory.
"""
from __future__ import annotations

import os
import tempfile
import threading

MODEL_NAME = os.environ.get("SW_WHISPER_MODEL", "small")
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
            # helps Whisper spell the words this office uses
            initial_prompt="Open the Al Noor slides. Send the report to Karim. افتح عرض النور.",
        )
        text = " ".join(s.text.strip() for s in segments).strip()
    return {"text": text, "language": info.language}
