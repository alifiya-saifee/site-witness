"""Tailscale: a private, encrypted link from your phone to this Mac from anywhere, with a real https certificate.

- Nothing here opens the Mac to the internet: only devices signed in to your own Tailscale account can reach it.
- We use `tailscale cert` for a certificate for this Mac's name (e.g. mac.tail1234.ts.net) and serve it ourselves.
  We do NOT use `tailscale serve`: it would forward every phone as if it were this Mac, and the Mac is trusted.
- If Tailscale isn't installed or running, these return None and the hub keeps its Wi-Fi address only.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

CANDIDATES = ("tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
              "/opt/homebrew/bin/tailscale", "/usr/local/bin/tailscale")
RENEW_DAYS = 30  # Tailscale's certificates last 90 days; get a fresh one well before


def cli() -> str | None:
    for c in CANDIDATES:
        found = shutil.which(c) or (c if c.startswith("/") and Path(c).exists() else None)
        if found:
            return found
    return None


def name(run=subprocess.run, tool: str | None = None) -> str | None:
    """This Mac's Tailscale name, if Tailscale is running and signed in."""
    tool = tool or cli()
    if not tool:
        return None
    try:
        r = run([tool, "status", "--json"], capture_output=True, text=True, timeout=8)
        data = json.loads(r.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if data.get("BackendState") != "Running":
        return None
    dns = str((data.get("Self") or {}).get("DNSName") or "").rstrip(".").lower()
    return dns if dns.endswith(".ts.net") else None


def cert(host: str, run_dir: Path, run=subprocess.run, tool: str | None = None) -> tuple[Path, Path] | None:
    """A real certificate for `host`, kept in run/ (never committed). Renewed after 30 days."""
    tool = tool or cli()
    if not tool:
        return None
    crt, key, stamp = run_dir / "ts-cert.pem", run_dir / "ts-key.pem", run_dir / "ts-name"
    fresh = crt.exists() and key.exists() and stamp.exists() and stamp.read_text() == host and \
        time.time() - crt.stat().st_mtime < RENEW_DAYS * 86400
    if fresh:
        return crt, key
    try:
        r = run([tool, "cert", "--cert-file", str(crt), "--key-file", str(key), host],
                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not crt.exists() or not key.exists():
        return None
    key.chmod(0o600)
    stamp.write_text(host)
    return crt, key
