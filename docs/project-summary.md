# Diwan + Site Witness: project summary

Nov 15, 2026 · @Someone

## Summary

We are building **Site Witness**, a new AI agent inside **Diwan**. A phone walk of an ageing building becomes a signed, evidence-backed inspection file for Dubai's new building-safety law. A licensed engineer stays in charge of every verdict. The same engine later lets residents and office staff ask for fixes by voice, and Diwan proves each fix on camera before it is closed or paid.

- **What it is:** an inspection agent plus a back office, built on Diwan's shared record of facts, tasks, documents and approvals.
- **Who pays:** DM-registered engineering offices first, then property managers and owners' associations.
- **Why now:** Dubai Law No. 3 of 2026 requires a safety certificate for buildings 20+ years past completion, with fines of AED 100k to 1M and possible Ejari suspension.
- **Where it goes:** the Create AI Agents Championship (submit by 4 Jan 2027) and a global AI hackathon, using the same build.
- **The one rule:** the AI never says "pass". It flags issues, and a named human signs off.

## Problem statement

Tens of thousands of Dubai buildings must now prove they are safe, and the people who have to prove it have no fast, trustworthy way to collect the evidence.

**The law.** Dubai Law No. 3 of 2026, signed 27 Feb 2026, requires a building safety certificate for buildings 20+ years past their completion certificate. It lasts 10 years, or 5 years once a building passes 40. A DM-registered engineering office must write the report, covering six areas: structure, cladding, electrical and mechanical systems in common areas, windows and barriers, Civil Defence, and SIRA CCTV. Dubai Municipality's circular of 9 Oct 2026 sets seven steps on the Dubai Building Platform, starting with 40+ year multi-storey buildings.

**The pain, by person:**

| Who | What hurts today |
| --- | --- |
| Engineering office | Inspections run on paper, photos in WhatsApp and Word reports. One building can take days to write up, and a sudden wave of demand is coming. |
| Property manager / owners' association | Cannot see what was found, what was fixed or what is still open. Contractors get paid before anyone checks the fix. |
| Owner / landlord | Faces fines of AED 100k to 1M (2M for repeats) and can lose Ejari lease registration if the certificate is late. |
| Residents and office staff | Report faults by phone or WhatsApp. Nobody confirms the fix, and the same issue comes back. |

**Why existing tools fall short.** Inspection apps such as PlanRadar record defects but do not map them to the Law 3 checklist. Generic AI chat tools can describe a photo, but they cannot hold a signed, versioned record a regulator will accept. Nothing links "defect found" to "fix proven" to "contractor paid".

**The core problem in one line:** proof of safety is slow to collect, easy to fake and disconnected from the money, while the deadline is fixed.

## Detailed solution

One building, two sides, one shared record. The commercial side (engineering offices, property managers, accounts) works in Diwan. The end-user side (residents, office staff, meeting rooms) speaks to it by voice. Every request, defect, fix and payment is stored as a fact that a named person approves.

### 1. The engine underneath: Diwan's shared record

Diwan stores everything as seven linked things: Person, Case, Fact, Task, Document, Approval and Event. Its key feature is the **fact-pinned approval**:

- An approval is tied to the exact facts it was based on, such as the defect photo, the contractor's bank account and the amount.
- If any of those facts changes later, the approval is cancelled automatically.
- Only the tasks that depend on that fact reopen, and Compliance is told first.
- Every step is written to an event log that cannot be edited, so the full history can be replayed.

This is what lets an AI agent work fast without anyone losing control.

### 2. Site Witness: how an inspection runs

1. **Pick the rulebook.** The engineer chooses the checklist, for example Law 3 Art. 7(d). Each clause is versioned, so a report always shows which version it used.
2. **Walk the building.** The engineer films common areas on a phone. It works offline and syncs later, so basements and plant rooms are fine.
3. **The agent sorts what it sees.** For each clause it gives one of three verdicts: **issue found**, **needs a human look** or **no issue seen**. It never says "pass". Each verdict links to the exact video frames that prove it.
4. **The engineer reviews and signs.** They accept, change or reject each verdict. Nothing reaches the report without their signature.
5. **Fixes become jobs.** Each issue becomes a task with an owner, a deadline and a cost.
6. **The fix is verified on camera.** A job closes only when a new photo or video shows the fix, matched against the original frame.
7. **Payment unlocks.** The contractor's payment is approved only after the fix is verified, pinned to the bank account and amount. If the bank account changes, payment stops and Compliance is alerted.
8. **Export.** The signed report and evidence pack are exported for the Dubai Building Platform, and the Ejari risk on the building clears.

### 3. The end-user side: voice requests and device control

This is where the ControlAnything idea lives on, as a front door into the same record.

- **Residents** say "the corridor light on floor 4 is out" in English or Arabic. Diwan creates a job, assigns it, and closes it only when the camera sees the light working.
- **Office staff in meetings** say "open the Al Noor project slides", "AC to 22" or "lights to 30%". A small hub in each room carries out the command and the room camera confirms it.
- **Voice match:** only registered staff voices can give commands. Sensitive actions, such as sending a report or paying, always need a tap to approve.

**How devices are reached.** Bluetooth alone is not enough. Each room gets a small hub (a mini PC or Raspberry Pi running Home Assistant) with Wi-Fi, Bluetooth, an infrared blaster and Matter. Screens are controlled over HDMI-CEC, split ACs over infrared, and lights through Wi-Fi plugs. Office AV systems such as Crestron connect where available. The phone is used only for setup: point at a device, name it and test it. Devices with no connection get a guiding mode that tells the person which button to press and confirms the result on camera.

### 4. Back office, already in Diwan

| Room | What it does for Site Witness |
| --- | --- |
| Finance | Contractor invoices, VAT, payments unlocked only by verified fixes |
| Compliance | Bank-change alerts, AML checks on contractors, audit trail |
| Operations | Job board for fixes, deadlines, contractor performance |
| Front Desk | Voice and WhatsApp requests from residents and staff |
| Records | Signed reports, evidence packs, certificate expiry reminders |
| Deals | Ejari risk shown on any unit being leased or sold |

### 5. Human control and trust

- The AI suggests and a named human decides. Every verdict, closure and payment carries a person's signature.
- **Model gate:** a new AI model must be approved by a person before use, and each report records which model version produced it.
- **Works during outages:** walks run offline, and if the cloud or email goes down (as with the recent Outlook outage), jobs queue locally and sync when service returns. Nothing is lost or sent twice.
- **Rulebook swap:** the same engine runs the DHA clinic checklist, which shows it is not tied to one law.

## Who it is for and market

The first buyers are engineering offices racing to meet Law 3. The wider base is every building and clinic that needs proof a fix was done. All figures below are our own estimates, not official counts.

| Segment | Role | Size (estimate) |
| --- | --- | --- |
| DM-registered engineering offices | First paying customer: write and sign the Law 3 report | Hundreds of offices |
| Property managers and owners' associations | Pay for fix tracking, verified contractor payments and the dashboard | Buildings aged 20+: about 35k to 49k |
| Landlords and owners | View the owner portal and the Ejari risk | Tens of thousands |
| DHA clinics (second rulebook) | Facility checklist inspections | 5,931 facilities (H1 2026) |
| Residents and office staff | Free users: voice requests and device control | Users, not payers |

**Money estimate:** total market of AED 22M to 186M for the first certificate wave, then AED 5M to 46M a year for renewals and fixes. A realistic target by end-2027 is AED 0.3M to 3M a year in revenue. Pricing to test: a fee per building report, plus a monthly fee per building for fix tracking.

## What makes it different

Other tools stop at "defect logged". Ours carries the chain through to "fix proven, then paid", and keeps a human signature on every link.

| Usual approach | Site Witness + Diwan |
| --- | --- |
| AI says "pass" or "fail" | AI never says "pass"; three verdicts, each with proof frames, and an engineer signs |
| Defect apps log photos | Every verdict is mapped to a versioned Law 3 clause |
| A job is closed when someone ticks it | A job is closed only when the camera sees the fix |
| Contractor paid from an invoice | Payment is pinned to the verified fix, bank account and amount; any change stops it |
| Approvals stay valid after the facts change | Approvals are cancelled automatically when a pinned fact changes |
| New AI model swapped in silently | A human approves each model, and each report records the version |
| Cloud down means work stops | Offline walks and a local queue that syncs later |
| Voice assistants act on anyone's voice | Only matched staff voices, and a tap for anything sensitive |

What we are **not** building: a robot, a replacement for the engineer, or a general chatbot. The value is the system around the model, so it keeps working whichever AI model is best next year.

## Plan and timeline

We build in four phases, finish the agents by 28 Dec and submit on 2 Jan, two days before the deadline. The same build is reused for the global AI hackathon.

[embedded content: build phases and Championship milestones]

Phases are shown at equal width, not to scale.

**Championship deliverables** (judged on Real Value 20, Technical 20, Business 20, Trust and Human Oversight 15, Innovation 15, Pitch 10):

- [ ] Working prototype that judges can test in a browser, with no install
- [ ] 2-minute demo video: walk, verdicts, sign, fix verified, payment unlocked
- [ ] 6-minute pitch video
- [ ] Business Model Canvas
- [ ] Agent Card: what the agent does, its limits and where a human decides
- [ ] Room hub demo: one meeting room, four devices (screen, AC, lights, slides)
- [ ] 5 to 10 interviews with engineering offices and property managers
- [ ] All code written fresh for the entry; no copied repo code

## Risks and open questions

| Risk | What could happen | Fallback |
| --- | --- | --- |
| Rollout timing | DM's staged notices move slower than expected, so demand arrives later | Lead with the DHA clinic checklist, which needs no new law |
| Engineers' trust | Offices worry the AI will be blamed, or will replace them | The AI never says "pass"; the engineer signs everything and keeps the liability and the fee |
| Platform access | No public API for the Dubai Building Platform | Export a ready-to-upload evidence pack; staff upload it by hand |
| Device control | Some brands block outside control or break connections | Hub covers infrared, HDMI-CEC and Wi-Fi; guiding mode for the rest |
| Competition | PlanRadar, HITEK or New Nordic add a Law 3 checklist | Our edge is the fix-to-payment chain and fact-pinned approvals, not the checklist |
| Time | Too much to build before 2 Jan | Cut the end-user side to one meeting-room demo; Site Witness is the core |
| Championship rules | Diwan could count as a "fully commercialised product" | Enter Site Witness as a new agent, with fresh code |

**Open questions**

- Which 2 to 3 engineering offices will pilot it, and at what price per report?
- Does DM accept video-frame evidence inside the report, or only stills?
- What are the global hackathon's rules and deadline? (link still needed)
- Will we get push access to the Diwan repo so the redesign can ship as a pull request?
