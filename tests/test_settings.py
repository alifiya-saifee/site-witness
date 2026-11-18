"""A .env copied from .env.example has empty lines (SW_PORT=). Empty must mean "use the default", not crash."""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def empty_template_env():
    env = dict(os.environ)
    for line in (ROOT / ".env.example").read_text().splitlines():
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=", line)
        if m:
            env[m.group(1)] = ""
    return env


def test_every_setting_empty_uses_defaults():
    code = ("from sitewitness import server, speech; import helper.diwan_helper as h; "
            "print(server.PORT, server.SECURE_PORT, speech.MODEL_NAME, h.PORT, h.CAMERA)")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=empty_template_env(),
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-800:]
    assert out.stdout.split()[-5:] == ["8040", "8443", "small", "8040", "0"]
