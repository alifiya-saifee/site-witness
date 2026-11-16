"""A network printer, spoken to with IPP (the standard printing protocol; HP, Canon, Epson and Brother all speak it).

Only three requests are ever made: ask the printer how it is, send one PDF from Records, and ask how that job went.
No driver and no printer setup on the Mac is needed. Printing always waits for a person's Approve tap (the hub
decides that); this file only prints what it is given.
"""
from __future__ import annotations

import struct
import time

import httpx

# IPP value tags
INTEGER, BOOLEAN, ENUM = 0x21, 0x22, 0x23
TEXT, NAME, KEYWORD, URI, CHARSET, LANGUAGE, MIME = 0x41, 0x42, 0x44, 0x45, 0x47, 0x48, 0x49
OP_PRINT_JOB, OP_GET_JOB, OP_GET_PRINTER = 0x0002, 0x0009, 0x000B

JOB_STATES = {3: "waiting", 4: "held", 5: "printing", 6: "stopped", 7: "cancelled", 8: "aborted", 9: "completed"}
PRINTER_STATES = {3: "ready", 4: "printing", 5: "stopped"}
PROBLEMS = {  # printer-state-reasons a person should hear about, in plain words
    "media-empty": "out of paper", "media-needed": "out of paper", "media-jam": "paper jam",
    "toner-empty": "out of toner", "marker-supply-empty": "out of toner", "door-open": "a door is open",
    "cover-open": "a cover is open", "offline": "offline", "paused": "paused",
}


class PrinterError(Exception):
    pass


def _attr(tag: int, name: str, value) -> bytes:
    data = struct.pack(">i", value) if tag in (INTEGER, ENUM) else str(value).encode()
    n = name.encode()
    return bytes([tag]) + struct.pack(">H", len(n)) + n + struct.pack(">H", len(data)) + data


def request(op: int, uri: str, extra: list[tuple[int, str, object]] = (), rid: int = 1) -> bytes:
    body = struct.pack(">BBHI", 2, 0, op, rid) + b"\x01"
    for tag, name, value in [(CHARSET, "attributes-charset", "utf-8"), (LANGUAGE, "attributes-natural-language", "en"),
                             (URI, "printer-uri", uri), (NAME, "requesting-user-name", "diwan"), *extra]:
        body += _attr(tag, name, value)
    return body + b"\x03"


def parse(resp: bytes) -> tuple[int, dict[str, list]]:
    """(status code, {attribute: [values]}) from an IPP response."""
    if len(resp) < 9:
        raise PrinterError("short answer from the printer")
    status = struct.unpack(">H", resp[2:4])[0]
    attrs: dict[str, list] = {}
    i, last = 8, None
    while i < len(resp):
        tag = resp[i]; i += 1
        if tag == 0x03:
            break
        if tag < 0x10:  # a new attribute group
            continue
        nlen = struct.unpack(">H", resp[i:i + 2])[0]; i += 2
        name = resp[i:i + nlen].decode(errors="replace"); i += nlen
        vlen = struct.unpack(">H", resp[i:i + 2])[0]; i += 2
        raw = resp[i:i + vlen]; i += vlen
        value = struct.unpack(">i", raw)[0] if tag in (INTEGER, ENUM) and vlen == 4 else \
            (raw == b"\x01") if tag == BOOLEAN else raw.decode(errors="replace")
        if nlen:
            last = name
            attrs.setdefault(name, []).append(value)
        elif last:  # an extra value of the attribute before
            attrs[last].append(value)
    return status, attrs


class Printer:
    def __init__(self, address: str, path: str = "ipp/print", port: int = 631, post=None, sleep=time.sleep):
        self.url = f"http://{address}:{port}/{path.lstrip('/')}"
        self.uri = f"ipp://{address}:{port}/{path.lstrip('/')}"
        self._post = post or self._http_post
        self.sleep = sleep

    def _http_post(self, body: bytes, timeout: float) -> bytes:
        r = httpx.post(self.url, content=body, headers={"Content-Type": "application/ipp"}, timeout=timeout)
        r.raise_for_status()
        return r.content

    def _ask(self, body: bytes, timeout: float = 8) -> dict[str, list]:
        try:
            status, attrs = parse(self._post(body, timeout))
        except PrinterError:
            raise
        except Exception as e:
            raise PrinterError(f"couldn't reach the printer ({type(e).__name__})") from None
        if status >= 0x0400:
            raise PrinterError(f"the printer refused (IPP status 0x{status:04x})")
        return attrs

    def status(self) -> dict:
        wanted = ["printer-state", "printer-state-reasons", "printer-make-and-model", "document-format-supported"]
        # one attribute with several values: the extra values have an empty name
        a = self._ask(request(OP_GET_PRINTER, self.uri, [(KEYWORD, "requested-attributes" if i == 0 else "", w)
                                                         for i, w in enumerate(wanted)]))
        reasons = [r for r in a.get("printer-state-reasons", []) if r != "none"]
        problems = sorted({PROBLEMS[k] for r in reasons for k in PROBLEMS if r.startswith(k)})
        return {"state": PRINTER_STATES.get((a.get("printer-state") or [0])[0], "unknown"), "problems": problems,
                "model": (a.get("printer-make-and-model") or [""])[0],
                "pdf": "application/pdf" in a.get("document-format-supported", [])}

    def print_pdf(self, pdf: bytes, job_name: str, wait: float = 60) -> dict:
        """Send one PDF, then follow the job until it is done. Returns job id, final state, and any problem."""
        before = self.status()
        if before["problems"]:
            return {"ok": False, "detail": f"The printer says: {', '.join(before['problems'])}", "problems": before["problems"]}
        a = self._ask(request(OP_PRINT_JOB, self.uri, [(NAME, "job-name", job_name), (MIME, "document-format", "application/pdf")])
                      + pdf, timeout=30)
        job = (a.get("job-id") or [None])[0]
        if job is None:
            raise PrinterError("the printer took the file but gave no job number")
        deadline, state, reasons = time.monotonic() + wait, "waiting", []
        while True:
            j = self._ask(request(OP_GET_JOB, self.uri, [(INTEGER, "job-id", job)]))
            state = JOB_STATES.get((j.get("job-state") or [0])[0], "unknown")
            reasons = j.get("job-state-reasons", [])
            if state in ("completed", "cancelled", "aborted", "stopped") or time.monotonic() > deadline:
                break
            self.sleep(1.5)
        if state == "completed":
            return {"ok": True, "confirmed": True, "job": job, "detail": f"Job {job} completed on the printer"}
        problems = sorted({PROBLEMS[k] for r in reasons for k in PROBLEMS if r.startswith(k)} |
                          set(self.status()["problems"]))
        why = f" ({', '.join(problems)})" if problems else ""
        if state in ("waiting", "printing", "held"):
            return {"ok": True, "confirmed": False, "job": job, "problems": problems,
                    "detail": f"Job {job} is still {state} after {wait:.0f} s{why}"}
        return {"ok": False, "job": job, "problems": problems, "detail": f"Job {job} {state}{why}"}
