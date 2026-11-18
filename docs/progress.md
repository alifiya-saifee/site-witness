# Progress

Last updated: 18 Nov 2026. Tests: **280 passing**. Full details: `docs/problem-solution-results.md`; build list:
`docs/checklist.md`.

## Done
- **Dynamic assistant:** several steps per sentence, memory of the last few turns, answers to questions,
  live-state questions, and fact-checked replies (Groq, with a word-match fallback).
- **The Mac:**
  - any installed app, through a live map that changes the moment an app is installed or deleted;
  - websites and the volume;
  - file search across the whole Mac with Spotlight (owner only).
- **Devices:**
  - Wi-Fi: TV, printer and plug; Roborock and ROS robots;
  - IR blaster lamps;
  - Bluetooth: lamps, SwitchBot, Sphero, and ESPHome relays for more range.
- **Phase 1, security:**
  - people are data, with the owner set up on the first run;
  - a phone joins with the code, then the owner taps Allow on the Mac and picks whose phone it is;
  - joined phones stay for 30 days, saved only as a hash;
  - Face ID passkey, or a tap on the Mac, for owner-level actions;
  - only the phone that asked, or the Mac, can approve;
  - other websites and wrong addresses are refused; JSON bodies only; security headers (CSP);
  - 30 commands a minute per phone.
- **Phase 2, the phone app:**
  - installable from the home screen (manifest and a service worker that never stores answers);
  - a real certificate through Tailscale, switched on by itself once Tailscale is installed;
  - files come to the phone by a one-time link that lasts 5 minutes, up to 100 MB, with Open / Save / Share.
- **Phase 3, nothing static:**
  - Records are the owner's shared folders: several, each with its own roles;
  - send = Approve, then a Mail draft on the Mac or the share sheet on the phone; a person always presses send;
  - the sample files and pretend devices appear only with `SW_DEMO=1`.

## Next (needs Alifiya)
1. **Install Tailscale** on the Mac and phone, and turn on MagicDNS and HTTPS Certificates. Then try:
   - Add to Home Screen;
   - Face ID;
   - "find my CV" on 4G;
   - Share to WhatsApp.
2. **Try one real Mail draft:** share a folder, add Omar with an email, say "send *a file* to Omar", tap Approve.
3. **Install the Bluetooth libraries:** `.venv/bin/pip install bleak bleak-esphome spherov2`.
4. Delete `SW_PAIR_CODE` from `.env`; it is ignored now.
5. **Hardware when wanted:** a Broadlink RM4 mini (IR lamp), ESP32 relays, a Tapo plug.

## Not built yet
- Printing from shared folders (printing uses the sample Records only, in demo mode).
- A Mail draft for whole-Mac files. On the Mac they open; on a phone they come to the share sheet.
- Voice match (who is speaking); for now, a phone is its person.

## Open questions
- Is a passkey on one phone enough, or should each owner phone register its own? Today it is one per phone.
- Should Brokers ever get files from the whole Mac (with the owner's tap each time)? Today they can't.
