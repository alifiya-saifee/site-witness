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
The first time, open `http://localhost:8040` on the Mac and type the owner's name; add other people on the **People** card.

- **Mic:** tap 🎙, speak (English or Arabic), tap again. The page records a short clip and the Mac writes it down with
  Whisper (`small` model, runs on the Mac, no API key; about 480 MB downloaded the first time).
- **Phone:** use the `https://…:8443` link. The first time, Chrome says “not private”: tap Advanced → Proceed (it is
  this Mac’s own certificate). Browsers only allow a mic on secure pages, so plain `http` is for this Mac only.
- A phone is always the person you chose when you allowed it. The Mac's own page is the owner, and can try a command
  as someone else to see what they may do. Visitors are refused; “open the report” asks which one;
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

## Smart plug demo (“turn on the lamp”)

Say “turn on the lamp” or «شغّل المصباح». The Mac switches the plug, reads it back, and takes a before/after photo
with its camera to check the lamp really got brighter. If the camera is blocked or sees no change, the page says
“couldn’t see it” rather than claiming it worked. Visitors are refused. A device that heats or moves (an oven) would
always wait for an Approve tap.

With no plug set up, a **pretend lamp** on the page switches instead (labelled “pretend”, no camera check).

For the real plug (TP-Link Tapo P100 or P110):
1. Set it up in the Tapo app on your 2.4 GHz Wi-Fi, with a lamp plugged in.
2. If the app has **Me → Third-Party Services → Third-Party Compatibility**, switch it on.
3. Find the plug’s IP address in the app (device settings → Device info).
4. Add to `.env` (never committed): `SW_PLUG=tapo`, `SW_PLUG_HOST=<IP>`, `TAPO_USERNAME=<Tapo login email>`,
   `TAPO_PASSWORD=<Tapo password>`. The login only unlocks the plug; commands go straight to it on your Wi-Fi.
5. Point the Mac camera at the lamp. macOS asks once for **Camera** access (System Settings → Privacy & Security →
   Camera → allow the app that runs `./run-demo`, e.g. Terminal or VS Code).

## Your own devices on the Wi-Fi (TV, printer, plug)

On the Mac page (http://localhost:8040), **Scan my Wi-Fi** listens for about 6 seconds and lists what it finds. It
only listens: nothing is controlled until you **add** it, with a name, a room and who may use it (Owner / Broker /
Visitor). Adding and removing work only on the Mac itself. Added devices are kept in `run/devices.json` (not
committed). Once a real device is added, the pretend lamp goes away.

| Device | What you can say | How it is checked |
|---|---|---|
| Samsung TV (2016+) | “turn off the TV”, “turn on the TV”, “volume up / down”, “mute”, “open YouTube / Netflix”, «اطفئ التلفزيون» | the TV is asked afterwards: power state, volume number, mute, app visible |
| Printer (IPP: HP, Canon, Epson, Brother) | “print the Al Noor report”, «اطبع تقرير النور» | always waits for your **Approve** tap; then the print job is followed to “completed” |
| Tapo plug | “turn on the lamp” | plug state + camera photo |

- **TV, first time:** when you add it, the TV shows an **“Allow”** pop-up. Accept it with the TV remote. Its token
  is kept in `run/` (only you can read it, never logged).
- **TV, turning on:** needs **Power On with Mobile** on the TV (Settings → General → Network → Expert Settings).
  Without it, “turn on” says plainly that the TV didn't wake.
- **Printer:** only files from Records can be printed, by people allowed to open them. No printer setup on the Mac
  is needed. Problems like “out of paper” are said out loud.
- Other things on the Wi-Fi are listed as “no connector yet”.

The helper only runs the actions each kind allows (for example a plug has no volume) on devices in the list.

## Search inside files (one shared folder)

On the Mac page, **Shared folder** → keep `~/Documents/Diwan Shared` (or pick another folder inside your home
folder) → tick who may open its files → **Share this folder**. **Add sample files** copies in 3 made-up reports.
Then say “open the report about the cracked balcony”, “find lift” or «ابحث عن تسرب المياه».

- Only that folder is ever read: PDF, Word (.docx), text and Markdown; hidden files, links leading out of the folder
  and files over 20 MB are skipped. Your home folder itself, Library, Desktop, Downloads, iCloud and hidden folders
  can't be shared. **Stop sharing** forgets the folder and deletes the search index.
- The index (`run/search.db`) is updated every minute, or with **Re-index**. File contents never go in the event log.
- The 4 Records files still come first; the shared folder is searched when you say “about …” / “find …”, or when
  nothing in Records matches. A scanned PDF with no text inside is found only by its name (no OCR yet).

## The phone app, from anywhere (Tailscale)

1. Install **Tailscale** (free) on the Mac and on the phone, and sign in to the same account on both.
2. In the Tailscale admin page (DNS), turn on **MagicDNS** and **HTTPS Certificates**.
3. Run `./run-demo`. The hub finds its Tailscale name, gets a real certificate with `tailscale cert` (kept in
   `run/`, never committed) and shows `https://<your-mac>.<tailnet>.ts.net:8443`. The plain Wi-Fi address moves to
   port 8444.
4. On the phone, open that address (it works on 4G too), then **Share → Add to Home Screen**. It opens full screen
   like an app, and Face ID works.

- Only your own Tailscale devices can reach the Mac. Nothing is opened to the internet.
- We serve the certificate ourselves and never use `tailscale serve`. That command would make every phone look like
  this Mac, which the hub trusts.
- The app keeps only its own page and icons for offline use. Files, replies and results are never stored by it.

## Files come to your phone

From a phone, "open the Al Noor slides" or "find my CV" → tap a result → the file comes **to the phone**, with
**Open**, **Save** and **Share…** buttons (WhatsApp, Mail and so on, with the phone's own share sheet). Say "… on my
Mac", or tap **Open on the Mac instead**, to open it on the Mac.

- The link works **once**, only for the phone that asked, and only for **5 minutes**. Files can be up to **100 MB**.
- Whole-Mac files are for the owner only, after a fresh check (Face ID, or a tap on the Mac). Hidden, system, code
  and secret files are never offered.
- The helper sends the file up by its one-time id; the path never leaves the helper. The hub keeps the copy (mode
  600, in `run/outbox/`) only until the phone has it, or for 5 minutes.
- Each file offered or taken is logged by name and person, never by path.

## Pairing

1. The phone types the 6-digit code from the terminal (a new code each run; `SW_PAIR_CODE` is no longer used).
2. On the Mac, **Joined phones** shows "A iPhone wants to join". Pick whose phone it is and tap **Allow**. Until then
   the phone can do nothing.
3. From then on the phone is that person. Anything else it claims is ignored.

- Joined phones stay joined for 30 days, even after a restart. They are kept in `run/sessions.json` only as a hash.
- 5 wrong codes lock a device out for a minute; 20 wrong in all make a new code.
- **Remove** logs one phone out; **Remove all + new code** logs everyone out. Removing a person logs out their phones.
- Each phone may send 30 commands a minute.

**Is it really you?** From a phone, a file from the whole Mac or an **Approve** needs a fresh check, which lasts 5
minutes. It is either Face ID (a passkey, when the hub has a real https name such as Tailscale's: put that name in
`SW_HOSTS`), or, on a plain IP address, a tap on **Allow** on the Mac. Only the phone that asked, or the Mac, can
approve.

**Other websites can't use the hub.** Every request must come to one of the hub's own names (this stops DNS
rebinding). A request from another website (by its `Origin` / `Sec-Fetch-Site`) is refused, and so is a non-JSON
body. The page also sends security headers: CSP (only its own script), no framing, and no referrer.

## Apps (on the Mac or on your phone)

Where it opens: “… on my Mac” / «على الماك» → **the Mac**; “… on my phone” → **the phone**; nothing said → the
device you spoke on (the Mac’s own page → the Mac). “open YouTube” goes to the TV once one is added, unless you name
the Mac or the phone.

| App | On the Mac | On the phone |
|---|---|---|
| YouTube | youtube.com in your browser | one-tap button |
| WhatsApp | WhatsApp Web in your browser (the WhatsApp app if installed) | one-tap button |
| Google Maps | in your browser | one-tap button |
| Mail | the Mail app | your phone’s mail app |
| Calendar | the Calendar app | not possible from a web page: it says so |
| Phone dialler | not on the Mac: it says so | one-tap button |

- On the Mac the helper checks the app really came to the front (`lsappinfo`, no permission needed) and takes a
  screenshot. Only an app key and plain text are sent to it; the command is built from the list in
  `sitewitness/apps.py`. Owner and Broker may open apps on the Mac; Visitors only on their own phone.
- **Drafts, never sending:** “WhatsApp message: I’ve sent the report” and “write an email saying the report is
  ready” open with your text typed. **You add who it’s to and press send yourself.** No addresses or contacts are
  stored, and the text isn’t logged. (“email the Al Noor report to Karim” is still the file send that needs a tap.)

## Understanding what you mean (Groq), Mac volume, your websites

- **Groq (optional):** put `GROQ_API_KEY=…` in `.env`. Each sentence then goes to Groq with a short menu of what is
  possible right now (file titles, app names, device names, website names), and Groq picks one item. Its answer is
  checked against the menu; anything else is thrown away, and every rule (roles, Approve taps, checks) still applies.
  Without a key, or if Groq is slow or busy, the built-in word match is used. **Sent to Groq:** the sentence and
  those names. **Never:** file contents, website addresses, tokens or keys. The log only says which way a command
  was understood.
- **Mac volume:** “turn up the volume on my Mac”, “volume to 30”, “mute the Mac”, «ارفع الصوت على الماك». The
  helper reads the volume back as proof. Owner and Broker only. (A TV's volume needs “TV” in the sentence.)
- **Websites:** the Mac page's **Websites** card holds the only sites the agent will open (https only), with the
  words people might say (“cosmique, cosmic, our website”). Ask for one that isn't saved and it asks
  **“What's the address?”**: say “https cosmique dot com”, check the address on screen, tap **Approve**, and it is
  saved and opened. Only the Owner can add sites. It never opens an address someone just says.
- **Hearing:** Whisper is told to expect “on my Mac” and your website names, so “on Melmah” no longer happens; if
  it still mishears, a small fix turns common mishearings back into “on my Mac”.
- When it doesn't understand, it says so (and what you can say), instead of “I couldn't find that file”.

## A dynamic assistant: several things at once, memory, answers, any app, any file

- **Several things in one sentence:** “open Notes and set the Mac volume to 30”, «افتح يوتيوب على الماك وارفع الصوت».
  Groq turns the sentence into up to 5 steps, each checked like a single command. They run **in order**: the next
  starts when the Mac has finished (and checked) the one before. The page shows a checklist (✓ done, ⏸ waiting
  for your tap, ✕ failed, – not done) with proof pictures, and **Stop the rest**.
  - A step that needs a tap (send, print, a robot moving) waits with its own **Approve** button; the steps after it
    run once you approve.
  - A failed or refused step stops the rest, and it says which and why. A step Groq made up is skipped, never run.
- **Memory:** the last 6 turns per phone (and the Mac), for 10 minutes, kept in memory only (never saved). So “now
  send **it** to Omar”, “turn it up more” and “open it on my Mac” work. “Forget that” / «انسَ» clears it.
- **Questions and answers:** “what's the Mac's volume?” (read, nothing changes), “which devices are on?”, “what
  websites do I have?”, “what did I just do?”. A general question (“what's 15% of 2000?”) gets a short answer and
  nothing is done. Something it can't do (“order a pizza”) gets an honest “I can't”. An answer may never claim
  something was done.
- **Fresh spoken replies:** after a list of steps, Groq writes one short reply from the real results. It is kept
  only if every number and name in it is in those results, and it may never say “sent” for something that wasn't
  (in this demo a send is only logged). Otherwise a fixed sentence is used.
- **Any app on the Mac:** the helper keeps a **live map** of installed apps (`sitewitness/mac_map.py`). Install an
  app and it is on the map at once; delete it and it's gone at once (macOS file-change notices, no timers). “Open
  Notes”, “open Spotify”: the helper opens only a name on its own map, with `open -a`, then checks it's in front.
  Owner and Broker only.
- **Any file on the Mac (Owner only):** the Mac's own Spotlight index is the live file map. “Find my CV on the Mac”
  lists matching documents (name + folder) to pick from. Never shown: `~/Library`, hidden folders, code projects,
  `.env`, keys, keychains and password files; only documents, pictures and media. A file is opened by a one-time id
  the helper handed out, never by a path. Brokers and Visitors search only Records and the shared folder.
- **The shared folder** updates its search index the moment a file is added, changed or deleted.
- **Groq's free plan** allows about 8,000 tokens a minute per model (about 3 sentences a minute on the main model).
  When one model is busy, the next one is used; replies are written with the small model. If all are busy, the
  word match is used.
- **Sent to Groq:** the sentence, the recent conversation (what was said and done, names only), and the menu (file
  titles, app names, website and device names). **Never:** file contents, paths, addresses, tokens or keys.

## A lamp with an infrared remote (IR blaster)

The Mac has no infrared light, so a lamp that only has a remote needs a **Wi-Fi IR blaster** (Broadlink RM4 mini;
an RM4 Pro if the remote is radio, not infrared). Check first: point your phone's camera at the remote's tip and
press a button. A flicker of light means infrared.

1. Set the blaster up in the Broadlink app, then `pip install broadlink` in `.venv` (needed only for a real blaster).
2. Mac page → **A lamp with a remote**: name, room, the blaster's IP, who may use it → **Add**.
3. Under **Devices**, tap **Teach on**, point the remote at the blaster and press **On** once. Do the same for Off
   (or **power** if the remote has one button), brighter, dimmer, colour.
4. “Turn on the lamp” presses the taught button. Infrared can't report back, so the Mac camera takes a before and
   after photo as proof, and says plainly when it couldn't see a change.

## Bluetooth devices and relays

Wi-Fi devices only need the **router** in range (about 30–50 m indoors). Bluetooth needs the **Mac itself** within
about 10 m, so **relays** extend it: an ESP32 board (about AED 30–40) flashed from esphome.io as a
“Bluetooth Proxy”, one per far room, passes Bluetooth to the Mac over Wi-Fi.

- **One-time setup:** `.venv/bin/pip install bleak bleak-esphome spherov2` (and allow Bluetooth for Terminal
  when macOS asks).
- **Scan Bluetooth** (Mac page, next to Scan my Wi-Fi) listens for 8 s through the Mac and every relay, and lists
  each device with its signal and who heard it. It never connects to anything. Add one with a name, room and roles.
- **What can be controlled:**

| Device | Actions | Proof |
|---|---|---|
| Bluetooth lamps / LED strips (ELK-BLEDOM, Triones / Happy Lighting) | on, off, brighter, dimmer, colour (“make the strip blue”, «اجعل الشريط أزرق») | camera before/after |
| SwitchBot Bot (presses a physical switch) | press, on, off | the Bot's own answer |
| Sphero robots (BOLT, Mini, SPRK+, RVR) | forward, back, left, right, spin (each **needs Approve**, at most 2 s at half speed), stop (never waits), light colour | the robot |

  Tick “heats or moves” when adding a SwitchBot that presses, say, a kettle: then it always asks first.
- **Relays card:** add a relay by IP or `name.local` (Scan my Wi-Fi also finds them), plus its encryption key if it
  has one. The key stays in `run/relays.json` on this Mac and is never shown or logged.
- Cheap lamp clones vary; if one doesn't react, its Bluetooth services need checking. Relay control is written
  against ESPHome's Bluetooth API and tested with fakes. Try it with a real relay before relying on it.

## Robots

| Robot | Say | Checked by |
|---|---|---|
| Roborock vacuum | “clean the kitchen”, “start the vacuum”, “pause”, “send the vacuum home”, «نظف المطبخ» | the vacuum’s own status (cleaning / returning home / charging, battery, errors) |
| ROS 2 robot (rosbridge) | “robot go to the meeting room”, “go home”, «روح غرفة الاجتماعات» | Nav2 says it arrived, or its own position is within 0.5 m of the spot |

- **Every movement waits for your Approve tap. “Stop” / «وقف» never does**, goes first, and cancels any waiting
  robot approval. “Stop” with no robot named stops every robot. Each robot row has a red **Stop** button.
- Until you add real ones, a **pretend vacuum** and a **pretend office robot** stand in (labelled “pretend”).
- **Add a Roborock** (Mac page → Add a robot): type your Roborock app email, type the code Roborock emails you, pick
  the vacuum. This logs in to Roborock’s cloud; only the login token is kept, in `run/roborock.json` (never your
  password, never committed). Its rooms come from the Roborock app.
- **Add a ROS 2 robot**: its IP, the rosbridge port (9090), and its spots, one per line: `Meeting room: 4, 2, 0`
  (x, y in metres on its map, heading in radians). It needs `rosbridge_server` and Nav2 running on the robot.
- **No robot to hand?** `tools/ros-sim/README.md` runs a real Nav2 robot simulation in Docker, and the Roborock
  connector is tested against Roborock's own simulator in the normal tests.

Tests: `.venv/bin/pytest -q`
