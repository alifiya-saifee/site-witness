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

- **Mic:** tap 🎙, speak (English or Arabic), tap again. The page records a short clip and the Mac writes it down with
  Whisper (`small` model, runs on the Mac, no API key; about 480 MB downloaded the first time).
- **Phone:** use the `https://…:8443` link. The first time, Chrome says “not private”: tap Advanced → Proceed (it is
  this Mac’s own certificate). Browsers only allow a mic on secure pages, so plain `http` is for this Mac only.
- You pick who is speaking (voice match isn’t built yet). Visitors are refused; “open the report” asks which one;
  “send … to …” waits for your tap and, in this demo, only logs “would send”. Nothing is emailed.
- macOS asks once for **Screen Recording** (the proof screenshot) and once to let Terminal **control Preview**
  (the “is it really open?” check). If you say no, the page shows “couldn’t confirm” instead of pretending.
- The helper only opens files listed in `sitewitness/records.py`, each download needs a one-time token, and it never
  runs any other command.

- **Spoken replies:** after each command the agent answers out loud on the device you used (“Done. I’ve opened the
  Al Noor slides on your Mac.”), in English or Arabic. Switch on **“Also say it on the Mac’s speakers”** to hear it
  from the Mac too. Default voice: the Mac’s own (Samantha / Majed), nothing sent out.
- **Your own voice (optional, English only):** on the Mac page, tick consent and record 5 seconds. Then put these in
  `.env` (never committed): `SW_TTS=magpie`, `NVIDIA_API_KEY=…`, `SW_MAGPIE_FUNCTION_ID=…` (copy the function id
  from the code sample on the magpie-tts-zeroshot page on build.nvidia.com; NVIDIA may need to approve access).
  If anything goes wrong, replies fall back to the Mac voice and the page says why.

Tests: `.venv/bin/pytest -q`
