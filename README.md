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

## Pairing

Only someone you give the 6-digit code to can join, and only from your Wi-Fi. A new code is made each run (unless
`SW_PAIR_CODE` is set, which is for testing only). 5 wrong codes lock that device out for a minute; 20 wrong in all
make a new code. On the Mac, **Joined phones** lists every joined device with **Remove**, and **Remove all + new
code** logs everyone out. Joining shares nothing from the phone: it only lets it send commands to this Mac.

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
