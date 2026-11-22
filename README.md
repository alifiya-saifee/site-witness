<div align="center">

# Site Witness

**Every fix in an ageing Dubai building, proven on camera, signed by an engineer, and paid only when it's true.**

An AI agent for Dubai Law No. 3 of 2026. It turns a phone walk of a building into an evidence-backed inspection file.
The AI flags issues; a licensed engineer signs every verdict. Fixes are proven on camera before they are closed or paid.

<sub>Entry for the Create AI Agents Championship (submissions close 4 Jan 2027) · all code written fresh for the entry ·
all names, buildings and figures are made up</sub>

</div>

---

## The problem

Dubai Law No. 3 of 2026 requires a safety certificate for every building 20+ years past completion. A registered
engineering office must inspect six areas (structure, cladding, common-area electrical and mechanical systems, windows
and barriers, Civil Defence, CCTV). Late certificates mean fines of AED 100k to 1M and possible suspension of Ejari
lease registration.

Today the evidence lives in paper notes, WhatsApp photos and Word reports. Nobody can see what was fixed, and
contractors are often paid before anyone checks the work.

**Proof of safety is slow to collect, easy to fake, and disconnected from the money.**

## How Site Witness works

1. **Walk.** The engineer films the building on a phone, offline if needed.
2. **Flag.** The agent checks each clause of the chosen rulebook and gives one of three verdicts: *issue found*,
   *needs a human look* or *no issue seen*. It **never says "pass"**, and every verdict links to the video frames
   behind it.
3. **Sign.** The engineer accepts, edits or overturns each verdict. Nothing reaches the report unsigned.
4. **Fix.** Each issue becomes a job with an owner, a deadline and a cost.
5. **Prove.** A job closes only when the camera shows the fix, matched to the original frame.
6. **Pay.** The contractor is paid only for a verified fix. If the amount or the bank account changes, the approval is
   cancelled automatically.

## What's built today: the proof engine

The rule under everything is: **an agent may act, but it must prove what it did, and a person approves anything
risky.** That engine is built and tested first, on the hardest case: a voice agent that acts in a real office.

You say *"turn on the corridor light"*, *"print the Al Noor report"* or *"send the lift note to Omar"*, in English or
Arabic, from your phone. The agent:

| | |
|---|---|
| **Acts only within its role** | Owner, broker and visitor each have their own permissions. Visitors are refused; files only from folders that role may see |
| **Waits for a tap on anything risky** | Sending, printing, robots moving, devices that heat. **"Stop" never waits** |
| **Proves it worked** | Screenshot on the Mac, the device's state read back, or a before/after camera photo |
| **Never pretends** | If it can't confirm, it says *"couldn't confirm"* instead of *"done"* |
| **Never sends for you** | It prepares the email or WhatsApp; a person presses send |
| **Keeps a log that can't be edited** | Every command, approval and result; never file contents |

Already connected: the Mac (apps, files, volume), Wi-Fi devices (Samsung TV, IPP printers, Tapo plugs), infrared
lamps through an IR blaster, Bluetooth lamps, SwitchBot and Sphero, Roborock vacuums and ROS 2 robots. **280 tests
passing.**

> **Why devices?** In a building, "the corridor light is fixed" is a claim. Site Witness turns it into a checked
> state plus a photo. The device layer is how fixes get proven, not a smart-home toy.

## Status

| Part | Status |
|---|---|
| Proof engine: roles, approvals, checks after each action, event log | ✅ built and tested |
| Voice agent (English and Arabic), phone app, secure pairing, Face ID | ✅ built and tested |
| Device and robot connectors | ✅ built and tested against fakes and simulators; some real hardware still to be tried |
| Rulebooks (Law 3 Art. 7(d), DHA clinics) and inspection walk | 🔨 in progress |
| Engineer review and signing, verifying fixes on camera, payments tied to verified fixes | 🔨 in progress |
| Signed report and evidence-pack export | 🔨 in progress |

Full build list: [docs/checklist.md](docs/checklist.md) · progress: [docs/progress.md](docs/progress.md)

## Try it

Needs macOS and Python 3. No API keys needed.

```bash
cp .env.example .env        # set SW_DEMO=1 for sample records and pretend devices
./run-demo                  # first run sets up .venv and the sample files
```

Open `http://localhost:8040` on the Mac. The terminal shows a link and a 6-digit code for your phone (same Wi-Fi).
Try *"open the Al Noor slides"* or *"turn on the lamp"*.

Full guide (devices, robots, shared folders, Tailscale, security): **[docs/helper-guide.md](docs/helper-guide.md)**

Tests: `.venv/bin/pytest -q`

## More

- [Project summary](docs/project-summary.md): the law, who pays, the full solution
- [Problem, solution, results](docs/problem-solution-results.md)
- [Mockups](docs/mockups/) (open in a browser)
- Built on the same ideas as [Diwan](https://github.com/alifiya-saifee/diwan): facts pinned to approvals, and
  corrections that reopen only the work that depended on them.
