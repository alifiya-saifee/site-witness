# Site Witness: build checklist

Fresh repo, started 15 Nov 2026. **Nothing is built yet.** Diwan already has some of these ideas; the "Diwan has"
column says where to *read* them. Don't copy code (Championship rule: fresh code only).

Key: ⬜ to build · 🟢 done · ❓ open

## 1. Engine (rebuild fresh)

| Item | Status | Diwan has (read only) |
|---|---|---|
| Append-only event log; unknown types rejected | 🟢 `sitewitness/events.py` (the database also refuses update/delete) | `diwan/events.py` (`TYPES`) |
| Repeated key returns the stored event (no duplicates) | 🟢 same file; a double tap never opens twice | `events.key` unique |
| Facts that are superseded, never edited | ⬜ | `fact.superseded` in `graph.py` |
| Approval pinned to facts; cancelled when a pinned fact changes; Compliance alerted first | ⬜ | `rests_on` + `g.stale()`, but Diwan only *shows* stale; it doesn't cancel |
| Only dependent tasks reopen | ⬜ | `g.impact()` |
| Engineer e-signature | ⬜ | `diwan/signing.py` pattern |

## 2. Site Witness agent

| Item | Status |
|---|---|
| Rulebooks: `law3_art7d.json`, `dha_clinic.json`, versioned clauses | ⬜ |
| Building, Walk, Verdict, FixTask | ⬜ |
| Agent: 3 verdicts only (`issue_found`, `needs_human`, `no_issue_seen`), never "pass", each with proof frames | ⬜ |
| Frames taken from the walk video in the browser (small JPEGs) | ⬜ |
| Engineer review: accept / edit / overturn; report locked until every finding signed | ⬜ |
| Fix verified on camera, matched to the original frame | ⬜ |
| Contractor payment pinned to {fix verified, bank account, amount}; bank change stops it | ⬜ |
| Model gate: a person approves a new model; each report records its model version | ⬜ |
| Export: signed report + evidence pack (upload-ready) | ⬜ |
| Offline walk: record, queue, sync with keys | ⬜ |
| Blur faces and number plates before saving | ⬜ |

## 3. End-user side

| Item | Status |
|---|---|
| Resident voice request → task; closes only when camera sees it working | ⬜ |
| Voice match for staff; a tap for sensitive actions | ⬜ |
| Helper demo: command from phone (paired) → file opens on the Mac → checked → screenshot proof; permissions, “which one?”, send needs a tap | 🟢 `./run-demo` (`sitewitness/`, `helper/`, `web/control.html`) |
| Voice match (today you pick the person) | ⬜ |
| Smart plug demo: “turn on the lamp” → Tapo plug (or pretend lamp) → state read back + before/after camera photo; risky devices need a tap | 🟡 built and tested with the pretend lamp; real plug + camera not tried yet (`sitewitness/devices.py`) |
| Real devices on the Wi-Fi: scan → add (name, room, roles; Mac only) → Samsung TV (power, volume, mute, apps; read back from the TV) and IPP printer (print after a tap; job followed to completed) | 🟡 built and tested with fakes; scan + printer status work on the real network; TV and a real print not tried yet (`sitewitness/discover.py`, `sitewitness/connectors/`) |
| Apps on the Mac or phone: “open YouTube on my Mac”, Mail, Calendar, WhatsApp, Maps; email/WhatsApp drafts (you press send) | 🟢 built and tested (`sitewitness/apps.py`) |
| Robots: Roborock vacuum + ROS 2 robot (rosbridge); every move needs a tap, Stop never does; pretend robots meanwhile | 🟡 ROS: passes against a real Nav2 + rosbridge simulation in Docker (`tools/ros-sim`); Roborock: passes against the library's official simulator; no real robot or Roborock account tried yet |
| Search inside files: one shared folder chosen on the Mac (PDF, Word, text); “open the report about …”, “find …”, Arabic too | 🟢 built, tested, tried for real on this Mac (`sitewitness/library.py`) |
| Pairing: wrong-code lock-out, new code after 20 wrong, joined-phones list with Remove | 🟢 built and tested; try Remove from your phone |
| Phase 1 security: people as data (first-run owner), Allow on the Mac ties a phone to a person, 30-day hashed sessions, Face ID passkey or Mac tap for owner-level actions, Host/Origin/JSON checks, CSP, 30 commands/min | 🟢 built and tested (257); try it from your phone |
| Understanding with Groq (menu-checked) + word match backup; Mac volume; saved websites (ask for the address by voice, tap to save); hearing fixes | 🟢 built and tested with Groq faked; real Groq needs `GROQ_API_KEY` in .env |
| Dynamic assistant: several steps per sentence (in order; a tap pauses, then the rest runs; a failure stops the rest), memory of the last turns (“send it to Omar”), answers and live-state questions, fresh replies fact-checked | 🟢 built, tested, tried live with real Groq on this Mac |
| Live map of the Mac: any installed app (install/delete noticed at once), any file via Spotlight (Owner only; secrets, system and code files never shown); shared folder index follows file changes at once | 🟢 built, tested, tried live (Notes, Calendar, CV search) |
| Lamp with an infrared remote via a Broadlink IR blaster: add, teach buttons, press with camera proof | 🟡 built and tested with a fake blaster; needs the blaster (and `pip install broadlink`) |
| Bluetooth: scan (Mac + ESPHome relays), BLE lamps/LED strips, SwitchBot Bot, Sphero robots (moves need a tap, capped); relays card | 🟡 built and tested with fake Bluetooth; needs `pip install bleak bleak-esphome spherov2` and real devices |
| Home Assistant room hub client; commands logged and confirmed | ⬜ |
| Hub hardware: Pi/mini PC, IR blaster, CEC, Wi-Fi plug | ⬜ |
| Guiding mode for devices with no interface | ⬜ |

## 4. Front end

| Item | Status |
|---|---|
| Sign-up mockup: 5 areas, rooms per office type | 🟢 mockup (`docs/mockups/diwan-onboarding-3d-mockup.html`) |
| Inside each room: agents at desks, agent cards, waiting-for-you, work feed, hands-to; “Follow a fix” best case | 🟢 mockup (same file; data in `docs/mockups/rooms-data.js`) |
| Features of all 24 rooms and 45 agents | 🟢 spec: `docs/rooms-and-agents.md` (generated; not built) |
| Site Witness screens mockup (walk, review, verify, owner, trust) | 🟢 mockup (`docs/mockups/diwan-site-witness-mockup.html`) |
| Real pages built from the mockups | ⬜ |
| Arabic RTL, light mode, accessibility | ⬜ |

## 5. Tests

| Item | Status |
|---|---|
| pytest per rule: never "pass", fix-gated payment, bank change stops payment, model gate, no duplicate sync | ⬜ |
| End-to-end: walk → verdicts → sign → fix verified → payment unlocked | ⬜ |

## 6. Championship (portal 4 Dec; due 4 Jan 2027; we submit 2 Jan)

| Item | Status |
|---|---|
| Browser prototype judges can test, no install, live until May 2027 | ⬜ |
| 2-min demo video (webcam face in a corner) | ⬜ |
| 6-min pitch video (face visible, unlisted link) | ⬜ |
| Pitch deck: 12 slides + cover + close | ⬜ |
| Business Canvas (12 sections) + Agent Card (13 prompts) | ⬜ |
| Room hub demo (4 devices) | ⬜ |
| 5–10 interviews (engineering offices, property managers) | ⬜ |
| Real test numbers: test count, success rate, one failure + fix, cost per task | ⬜ |

## Open questions
- ❓ Stack: same as Diwan (Python + FastAPI, vanilla JS) or something else?
- ❓ Pilot offices and price per report; does DM accept video-frame evidence?
- ❓ `site-witness-mockup.html`, the "solution and feature plan" and the "visual redesign plan" aren't here yet.
