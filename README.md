# Site Witness

A phone walk of an ageing Dubai building becomes a signed, evidence-backed inspection file for Dubai Law No. 3 of
2026. The AI flags issues; a licensed engineer signs every verdict. Fixes are proven on camera before they are closed
or paid.

Entry for the Create AI Agents Championship (deadline 4 Jan 2027). All code in this repo is written fresh for the
entry.

- Project context: [CLAUDE.md](CLAUDE.md)
- What to build: [docs/checklist.md](docs/checklist.md)
- Mockups (open in a browser): [docs/mockups/](docs/mockups/)

All names, buildings and figures in the mockups are made up.

## Run the helper demo (phone → Mac)

Say or type “open the Al Noor slides” on your phone; the file opens on the Mac and a screenshot comes back as proof.

```
./run-demo
```

The terminal shows a link for your phone (same Wi-Fi) and a 6-digit pairing code. Stop with Ctrl+C.

- On the phone, use your **keyboard’s mic** to dictate: browsers block a page’s own mic on plain `http://` over
  Wi-Fi. On the Mac (`http://localhost:8040`) the page’s 🎙 button works.
- You pick who is speaking (voice match isn’t built yet). Visitors are refused; “open the report” asks which one;
  “send … to …” waits for your tap and, in this demo, only logs “would send”. Nothing is emailed.
- macOS asks once for **Screen Recording** (the proof screenshot) and once to let Terminal **control Preview**
  (the “is it really open?” check). If you say no, the page shows “couldn’t confirm” instead of pretending.
- The helper only opens files listed in `sitewitness/records.py`, each download needs a one-time token, and it never
  runs any other command.

Tests: `.venv/bin/pytest -q`
