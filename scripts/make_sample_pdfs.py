"""Make the 4 made-up PDFs for the helper demo, using headless Google Chrome.

Run: python scripts/make_sample_pdfs.py
Everything in these files is sample data: the buildings, people and figures are invented.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sitewitness.records import BY_ID, FILES_DIR  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
STYLE = """<style>
@page{size:A4 landscape;margin:0} body{margin:0;font-family:Helvetica,Arial,sans-serif;color:#ece8df;background:#0a0d13}
.p{width:297mm;height:210mm;padding:22mm 26mm;box-sizing:border-box;page-break-after:always;position:relative}
.k{color:#e8c77a;letter-spacing:3px;font-size:13px;text-transform:uppercase} h1{font-family:Georgia,serif;font-weight:400;font-size:46px;margin:10px 0}
p,li{font-size:19px;line-height:1.55;color:#cfd2da} table{border-collapse:collapse;width:100%;font-size:16px} td,th{border-bottom:1px solid #2a3040;padding:9px 6px;text-align:left}
.f{position:absolute;bottom:14mm;left:26mm;right:26mm;font-size:12px;color:#8b92a3;display:flex;justify-content:space-between}
.tag{display:inline-block;background:#3a2a14;color:#fdb022;padding:3px 10px;border-radius:99px;font-size:13px}
</style>"""


def page(kicker: str, title: str, body: str, foot: str) -> str:
    return f'<div class="p"><div class="k">{kicker}</div><h1>{title}</h1>{body}<div class="f"><span>{foot}</span><span>SAMPLE DATA · made up for a demo</span></div></div>'


DOCS = {
    "alnoor-slides": [
        page("Al Noor Residence, Deira · Law 3", "Building safety walk: what we found", "<p>Completion 2001 · 25 years old · 9 floors<br>Report due 15 May 2027 (Dubai Municipality notice)</p><p class='tag'>Engineer: Eng. R. Haddad, Sample Engineering Consultants</p>", "Slide 1 of 3"),
        page("Findings", "13 findings, all signed", "<table><tr><th>Area</th><th>Issue found</th><th>Needs a human</th><th>No issue seen</th></tr><tr><td>Structure</td><td>1</td><td>1</td><td>0</td></tr><tr><td>Cladding</td><td>0</td><td>0</td><td>1</td></tr><tr><td>Electrical &amp; mechanical</td><td>1</td><td>0</td><td>1</td></tr><tr><td>Doors &amp; barriers</td><td>1</td><td>1</td><td>0</td></tr><tr><td>Civil Defence</td><td>1</td><td>0</td><td>1</td></tr><tr><td>CCTV</td><td>0</td><td>1</td><td>1</td></tr></table>", "Slide 2 of 3"),
        page("Next", "Fix, prove on camera, then pay", "<ul><li>4 fix jobs created, with owners and deadlines</li><li>Each fix is closed only when the camera sees it and the engineer confirms</li><li>Contractor payment unlocks only after the fix is verified</li></ul>", "Slide 3 of 3"),
    ],
    "alnoor-report": [
        page("Signed technical report · Law 3 Art. 7(d)", "Al Noor Residence, Deira", "<p>Rulebook: Law 3 Art. 7(d) v1.2 · Model: A v3 · 13 findings signed by Eng. R. Haddad on 14 Nov 2026.</p><p>F2 · Exit sign not lit, stair A level 3 · <b>issue found</b> · proof frame 03:50</p><p>The AI never marks anything as passed. Every finding above is the engineer's signed verdict.</p>", "Report SW-007 · page 1"),
    ],
    "marina-quote": [
        page("Quote · inspection under Law 3", "Marina Court (sample)", "<table><tr><th>Item</th><th>AED</th></tr><tr><td>Safety walk and Site Witness review</td><td>18,000</td></tr><tr><td>Signed report and evidence pack</td><td>6,000</td></tr><tr><td>VAT 5%</td><td>1,200</td></tr><tr><th>Total</th><th>25,200</th></tr></table>", "Quote Q-114 · valid 30 days"),
    ],
    "clinic-dha": [
        page("DHA self-inspection report · weekly", "Sample Family Clinic, Al Barsha", "<ul><li>D1 Sharps box over three-quarters full, room 2: issue found</li><li>D3 Expired medicine on shelf: issue found</li><li>D5 Crash cart seal: needs a human</li></ul><p>Signed by the medical director, Dr. S. Nair (sample).</p>", "Week 46 · 2026"),
    ],
}


def main() -> None:
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for rid, pages in DOCS.items():
            src = Path(tmp) / f"{rid}.html"
            src.write_text(f"<!doctype html><meta charset='utf-8'><title>{BY_ID[rid].title}</title>{STYLE}" + "".join(pages))
            out = BY_ID[rid].path
            subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                            f"--user-data-dir={tmp}/chrome", f"--print-to-pdf={out}", src.as_uri()],
                           check=True, capture_output=True, timeout=60)
            print(f"  made {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
