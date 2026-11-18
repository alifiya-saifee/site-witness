# Site Witness: the problem, our solution, and the results so far

Create AI Agents Championship (Dubai), portal opens 4 Dec 2026, due 4 Jan 2027 (we submit 2 Jan) · Built fresh for the
entry, as a new agent inside **Diwan**.
Repo: github.com/alifiya-saifee/site-witness (private).
Status on 18 Nov 2026: 16 commits; **240 tests passing**. The last two commits (`2e0ad35` dynamic assistant,
`5645de3` Bluetooth) are local and not pushed yet.

---

## 1. The problem

### Two sides of one building
**Commercial side.** Dubai Law No. 3 of 2026 requires a safety certificate for buildings 20+ years past completion
(renewed every 10 years, or every 5 once the building is 40+). The report must come from a licensed engineering
office and cover:
- structure;
- cladding;
- common-area electrical and mechanical systems;
- windows, doors and barriers;
- Civil Defence;
- CCTV.

Fines run from AED 100k to 1M, and Ejari lease registration can be suspended. Today the evidence lives in paper,
WhatsApp photos and Word files. Nobody can see what was found, what was fixed, or whether a contractor was paid
before the fix was checked.

**End-user side.** Residents and office staff report faults by phone call, and nobody confirms the fix. In meeting
rooms, people fight with remotes, screens and laptops.

### What this part of the build solves
**One trusted assistant** that people talk to from their phone, in English or Arabic. It:
1. understands what they mean, even when they say several things at once;
2. acts on the office's own computer and devices (files, apps, screens, printers, lamps, robots);
3. **proves** each action (a screenshot, a camera photo, the device's own read-back);
4. never does anything sensitive without a person's tap, and never claims to have done what it didn't.

This is the end-user half of Site Witness: the same engine later closes fix tasks only when the camera sees the fix,
and pays a contractor only after a verified fix.

### Rules we hold ourselves to
| # | Rule |
|---|---|
| 1 | The AI never marks anything "pass", "safe" or "done" unless it is checked. A reply may only say what really happened. |
| 2 | Every change is an event in an append-only log. Never updated, never deleted. |
| 3 | Sending, printing, moving robots and anything that heats or moves need a person's tap. **Stop never waits.** |
| 4 | Secrets never leave the Mac: no keys, tokens, paths or file contents in logs, replies or AI requests. |
| 5 | Bilingual: English and Arabic for every spoken reply. |
| 6 | All demo names and records are made up. |

---

## 2. Our solution

**One line:** you speak to your phone; the Mac understands, does it, checks it and shows the proof, under rules a
person controls.

### How it works
```
 Phone (paired)                 The Mac (hub + helper)                                    Things
 ─────────────                  ──────────────────────                                    ──────
 🎙 voice / text ──https──►  Hub (FastAPI)                                              
                             1. Whisper writes down what was said (on the Mac, no cloud)
                             2. Groq turns it into up to 5 checked steps (menu-checked);
                                word matching is the backup
                             3. Rules: who you are, roles, taps, limits
                             4. Steps run in order ───────► Mac helper ──► apps, files, volume, websites
                                                                  │       ──► Wi-Fi: TV, printer, plug, Roborock, ROS
                                                                  │       ──► IR blaster (lamp with a remote)
                                                                  │       ──► Bluetooth: lamps, SwitchBot, Sphero
                                                                  │            (the Mac, or relays in far rooms)
                             5. Proof comes back ◄────────────────┘ screenshot / camera / device read-back
 🔊 spoken reply ◄─────────  6. One reply, written from the real results (fact-checked), EN or AR
                             7. Every step is an event in the append-only log
```

- **Hub** (`sitewitness/server.py`): the page, pairing, understanding, rules, steps, approvals, replies, the log.
- **Helper** (`helper/diwan_helper.py`): the only part that touches the Mac and devices. It accepts only a
  short list of message types, and never runs a command or opens a path it was sent.

### Understanding what people mean (`sitewitness/understand.py`)
- **Groq gets a menu**, not free rein: file titles, app names (built-in apps plus every app on the Mac), saved
  websites, devices with their allowed actions, and the recent conversation. It answers with JSON steps.
- **Every step is checked here.** An unknown id, a made-up app, an out-of-range number or a website that isn't saved
  is thrown away and shown as "skipped". A message's text must appear word for word in what was said.
- **Several steps per sentence:** "Open Notes and set the Mac volume to 30" runs both steps, in order.
- **Memory:** the last 6 turns per phone, for 10 minutes, kept in memory only. "Now send **it** to Omar" knows "it"
  is the report you just opened. "Forget that" clears it.
- **Questions and answers:**
  - "What's the Mac's volume?" reads it, and nothing changes.
  - "What's 15% of 2000?" is answered.
  - "Order a pizza" gets an honest "I can't".
  - An answer that claims something was done is thrown out.
- **Fresh replies, fact-checked:** after the steps, Groq writes one short reply from the real results. It is kept
  only if every number and name in it appears in those results, and it may never say "sent" for a step still
  waiting for a tap. Otherwise a fixed sentence is used.
- **Free-plan limits:** Groq's free plan allows about 8,000 tokens a minute per model. When the main model is busy,
  the next one is used; replies use the small model. If every model is busy, the word matcher takes over.

### What it can do

| Area | What you can say | Proof | Status |
|---|---|---|---|
| **Files: Records** | "open the Al Noor slides", "send the report to Omar" (tap) | Preview confirms it's open, plus a screenshot | ✅ live |
| **Files: shared folder** | "open the report about the cracked balcony", "find lift" (searches inside PDF, Word, text; Arabic too) | screenshot | ✅ live |
| **Files: whole Mac** (Owner only) | "find my CV on the Mac" → pick one | screenshot | ✅ live (opens on the Mac) |
| **Any Mac app** | "open Notes", "open Calendar" | the app is checked in front, plus a screenshot | ✅ live |
| **Live app map** | install or delete an app: it's on or off the map within ~0.6 s | event in the log | ✅ live |
| **Websites** | "open Cosmique website on my Mac"; an unknown one: it asks for the address, then you tap to save | browser in front, plus a screenshot | ✅ live |
| **Mac volume** | "turn it up", "volume to 30", "mute the Mac", «ارفع الصوت على الماك» | the volume is read back | ✅ live |
| **Drafts** | "write an email saying…", "WhatsApp message: …" | the draft opens; **you press send** | ✅ live |
| **Phone apps** | "open WhatsApp on my phone" | a one-tap button | ✅ live |
| **Samsung TV** | on, off, volume, mute, YouTube, Netflix, input | the TV reports back | 🟡 found on your Wi-Fi; pairing not tried |
| **Printer (IPP)** | "print the Al Noor report" (tap) | the job is followed to "completed" | 🟡 found, status read; a real print not tried |
| **Smart plug (Tapo)** | "turn on the lamp" | plug state plus camera before/after | 🟡 pretend plug only |
| **Robots** | Roborock: "clean the kitchen" (tap); ROS 2: "go to reception" (tap); "stop" (never waits) | robot state and position | 🟡 passes the official Roborock simulator and a real Nav2 simulation |
| **Lamp with an IR remote** | teach its buttons once, then "turn on the lamp" | camera before/after | 🟡 tested with a fake blaster; needs a Broadlink RM4 mini |
| **Bluetooth lamps / LED strips** | "make the strip blue", "dimmer" | camera before/after | 🟡 tested with fakes; libraries not installed |
| **SwitchBot Bot** | "press the coffee switch" | the Bot's own answer | 🟡 tested with fakes |
| **Sphero robots** | "Sphero go forward" (tap; 2 s at half speed at most), "stop" | the robot | 🟡 tested with fakes |
| **Bluetooth relays** | an ESP32 per far room extends Bluetooth over Wi-Fi | the scan shows which relay heard each device | 🟡 tested with fakes |

### Range: Wi-Fi and Bluetooth
| | Range indoors | What must be close |
|---|---|---|
| Wi-Fi | ~30–50 m from the router, through walls and floors | only the router |
| Bluetooth | ~10 m | the Mac, or a relay in that room |

### Voice
- **Listening:** Whisper ("small") runs on the Mac and is told to expect "on my Mac", your website names and app
  names. Common mishearings are fixed ("on Melmah" → "on my Mac").
- **Speaking:** the Mac's own voices (Samantha for English, Majed for Arabic), played on the phone and optionally on
  the Mac's speakers.
- **Your own voice:** optional, through NVIDIA magpie-tts-zeroshot (access applied for; waiting for approval).

---

## 3. Security

### What is protected today
| Protection | How |
|---|---|
| Joining | A 6-digit code (new each start), then the owner taps **Allow** on the Mac and picks whose phone it is. 5 wrong codes lock a device for a minute; 20 wrong in all make a new code |
| Who a phone is | Always the person it was allowed as; a `person` it sends is ignored |
| Joined phones | 30 days, saved hashed in `run/sessions.json`; listed on the Mac with last use and Remove; removing a person logs out their phones |
| Fresh check | From a phone, whole-Mac files and Approve need Face ID (passkey) or a tap on the Mac, valid 5 minutes. Only the phone that asked, or the Mac, can approve |
| Other websites | Host must be the hub's own (no DNS rebinding); other-site Origin / Sec-Fetch-Site refused; JSON bodies only; CSP, no framing, no referrer |
| Limits | 30 commands a minute per phone |
| The helper | Accepts only the Mac's own token, from this Mac. It never opens a path it was sent: files come by id with a one-time token |
| Files from the whole Mac | Owner only. Never shown: `~/Library`, hidden folders, code projects, `.env`, keys, keychains, password files; documents and media only. Opened by a one-time id |
| Apps | Only names on the helper's own live map, opened with `open -a` (no shell) |
| Websites | Only saved https addresses; no passwords or tokens in them; saving one needs a tap |
| Devices | Only devices a person added on the Mac, only their kind's actions, only for the roles ticked |
| Taps | Send, print, robot moves, anything that heats or moves. **Stop never waits** and cancels waiting moves |
| AI | Groq sees the sentence, recent turns and names, never file contents, paths, addresses or keys. Its steps are checked; its replies are fact-checked |
| Secrets | `.env` is never read by the assistant or committed. Relay keys are kept on the Mac (file mode 600), never shown or logged |
| Log | Append-only; every command, step, approval, refusal and device result |

### Problems found in the review
| | Problem | Fix |
|---|---|---|
| ✅ | A phone **chooses who it is** from a list: any joined phone could pick the owner | Fixed 18 Nov. Each phone is tied to a person when the owner allows it on the Mac; the hub ignores any `person` a phone sends |
| ✅ | A website open in the Mac's browser could post to the hub, which trusts this Mac (cross-site request; DNS rebinding) | Fixed 18 Nov. The hub checks Host and Origin on every request, and requires JSON |
| ✅ | Fixed pairing code in `.env`; joined phones never expire; restarts forget phones | Fixed 18 Nov. A new code each start; sessions last 30 days, saved hashed |
| ✅ | Self-signed certificate: a browser warning, and no installable app or passkeys | Built 18 Nov: a real certificate through Tailscale, turned on by itself once Tailscale is installed (not tried live yet) |
| ✅ | No limit on commands per phone; no security headers | Fixed 18 Nov. 30 commands a minute per phone; CSP, frame and referrer headers |

### Who can do what (after the fix)
| Person | Records / shared folders | Whole Mac files | Mac apps, volume, websites | Devices | Send, print, robot moves |
|---|---|---|---|---|---|
| Owner | ✅ | ✅ plus Face ID on the phone | ✅ | ✅ | tap, plus Face ID on the phone |
| Broker | their roles' files | ❌ | ✅ | as ticked | tap |
| Visitor | their roles' files | ❌ | ❌ | as ticked | tap |

---

## 4. From demo to real: what's left

### Still demo-static
1. ~~People are written into the code, and phones pick who they are.~~ Done in Phase 1.
2. ~~Records is 4 made-up sample PDFs.~~ Done in Phase 3: Records are your shared folders.
3. ~~"Send" is only logged.~~ Done in Phase 3: a Mail draft or the phone's share sheet; you press send.
4. ~~A pretend lamp and pretend robots appear when no real one is added.~~ Done in Phase 3: only with `SW_DEMO=1`.
5. ~~Files found from the phone open on the Mac, not on the phone.~~ Done in Phase 2.

### The plan (approved 18 Nov)
**Phase 1: who you are, and closing the holes** ✅ done 18 Nov (257 tests)
- People are data, set up on the Mac (the owner first, then others, with roles and email).
- A phone joins with the code; the owner taps **Allow** on the Mac and picks whose phone it is.
- **Face ID (passkey)** for owner-level actions from a phone: whole-Mac files, approving a send or print, adding
  things. It lasts 5 minutes.
- Host and Origin checks, JSON only, rate limits, security headers, and saved sessions that expire.

**Phase 2: the phone app, from anywhere** ✅ built 18 Nov (271 tests); Tailscale waits for your install
- **Tailscale** (free): a private, encrypted link from your phone to the Mac from anywhere, with a real
  certificate. The Mac is never open to the public internet.
- **Installable web app:** a home-screen icon, full screen, the mic, phone-first layout.
- **"Find this file" gets it on the phone:**
  1. pick a result; Face ID if it's a whole-Mac file;
  2. a one-time link that expires in 5 minutes;
  3. view, save or Share (WhatsApp, Mail).
  - Limits: 100 MB at most; secret files never offered.

**Phase 3: no more static parts** ✅ built 18 Nov (280 tests)
- Records = the folders the owner shares, each with the roles that may use them.
- **Send for real, with you pressing send:** the phone's share sheet, or a Mail draft with the attachment to that
  person's email.
- Pretend devices only with `SW_DEMO=1`.

### Needs from Alifiya
| Item | Why |
|---|---|
| `pip install bleak bleak-esphome spherov2` (~10 MB) | Bluetooth (code ready) |
| Tailscale on the Mac and phone, HTTPS certificates on | The phone app from anywhere, with no warning |
| Delete `SW_PAIR_CODE` from `.env` (it is ignored now) | Tidy |
| Hardware when wanted: Broadlink RM4 mini (~AED 60–100), ESP32 relays (~AED 30–40 each), a Tapo plug | Real lamp, more Bluetooth range, plug proof |
| NVIDIA approval | Replies in your own voice |

### Later (not in this plan)
- Voice match (who is speaking).
- App Store apps.
- Home Assistant hub.
- The Site Witness inspection flow (walk → verdicts → sign → fix verified → payment).

---

## 5. Results so far

| Check | Result |
|---|---|
| Tests | **280 passing** (Groq, Bluetooth, IR and robots faked; the ROS sim and Roborock simulator tested separately) |
| "Open Notes and set the Mac volume to 30" | 2 steps, both checked (Notes in front; volume 46 → 30), one fresh reply, 2.7 s |
| «افتح يوتيوب على الماك وارفع الصوت» | 2 steps (YouTube open; volume 30 → 40), Arabic reply |
| "Open the Al Noor report" → "now send it to Omar" | "it" understood from memory; the send waited for a tap |
| "Send the Marina quote to Omar, then open Calendar" | Paused for Approve, then Calendar opened and was checked; the reply didn't claim it was sent |
| "What's 15 percent of 2000?" / "order a pizza" | Answered "300", nothing done / an honest "I can't" |
| "Find my CV on the Mac" | 8 CVs listed from Documents › CVs, no code or secret files |
| Live app map | Install noticed in 0.64 s, delete in 0.65 s |
| Wi-Fi scan | Found the Samsung TV (UA55DU8000) and the HP printer (IPP ready) |
| Robots | ROS 2 Nav2 simulation: go-to and stop pass; Roborock official simulator passes |
| Phase 3, live on a scratch copy (no demo mode) | No pretend devices, no sample files ("open the Al Noor slides" → not found); a shared folder read (1 file); "send the lift note to Omar" → "Send 'Lift note' to Omar?" → Approve → a Mail draft is asked of the helper (Mail itself not tried live yet) |
| Phase 2, live on a scratch copy (phone over https) | "Open the Al Noor slides" → file ready → 81 KB PDF downloaded, a second try refused (410). "Find my CV" → 8 Spotlight results → tap → "check it's you first" → Allow on the Mac → the CV (136 KB) came to the phone; the temporary copy was deleted; no folder path anywhere in the log. Manifest and service worker served |
| Phase 1, live on a scratch copy | First-run owner set-up; a phone waits for Allow (403 before); allowed as Omar, it claimed to be the owner and was still refused the owner's report; other-site Origin 403, text/plain POST 415, wrong Host 403; CSP header on the page; `sessions.json` mode 600 with no token in it |
| Bluetooth scan without the library | Says "the Bluetooth library isn't installed yet" instead of failing |

## 6. How to run
```
cd site-witness
./run-demo                 # starts the hub and the Mac helper; prints the Mac and phone addresses and the code
```
- **On the Mac:** http://localhost:8040
- **On the phone:** the https address it prints → Advanced → Proceed (until Tailscale) → enter the code.
- **Optional, in `.env` (never committed):** `GROQ_API_KEY` (understanding); `SW_TTS=magpie`, `NVIDIA_API_KEY`,
  `SW_MAGPIE_FUNCTION_ID` (your voice); `TAPO_*` (plug).
- **Tests:** `.venv/bin/python -m pytest -q`
