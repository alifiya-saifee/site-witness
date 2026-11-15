# Project context: Diwan + Site Witness

> Last updated: 15 Nov 2026. Owner: Alifiya Saifee (GitHub `alifiya-saifee`), Dubai.

## 0. This repo (read first)

- **This is the fresh Site Witness repo** (`alifiya-saifee/site-witness`, private), started 15 Nov 2026 for the
  Create AI Agents Championship. Its rule is "all code written fresh for the entry", so **never copy code from the
  Diwan repo** (`../diwan-restore`, `../diwan-hackathon`). Read Diwan for ideas and patterns only, and write new code
  here.
- There is **no code yet**. Sections 3.1 and 6 describe Diwan, the product Site Witness plugs into. Rebuild what the
  agent needs (event log, facts, approvals) fresh in this repo.
- Build list: `docs/checklist.md`. Mockups: `docs/mockups/`. Summary: `docs/project-summary.md`.
- Don't `git push` or deploy unless Alifiya says so in that session. Never read, print or commit `.env`; commit only
  an `.env.example` with empty values.

---

## 1. One-paragraph summary

We are building **Site Witness**, a new AI agent inside **Diwan**. A phone walk of an ageing building becomes a
signed, evidence-backed inspection file for Dubai Law No. 3 of 2026 (building safety certificates). A licensed engineer
stays in charge of every verdict. The same engine lets residents and office staff ask for fixes or control room devices
by voice, and Diwan proves each fix on camera before it is closed or paid.

**One building, two sides, one shared record.** The commercial side (engineering offices, property managers, accounts)
works in Diwan. The end-user side (residents, staff, meeting rooms) talks to it by voice.

**The one rule:** the AI never says "pass". It flags issues; a named human signs off.

Targets:
- **Create AI Agents Championship (Dubai):** portal opens 4 Dec 2026, deadline **4 Jan 2027** (we submit 2 Jan).
  Semi-finalists end of Jan, semi-final March, final 6 May 2027.
- **A global AI hackathon:** same build. Rules and link still to be confirmed.

---

## 2. Problem statement

Tens of thousands of Dubai buildings must now prove they are safe, and the people who have to prove it have no fast,
trustworthy way to collect the evidence.

**The law (Dubai Law No. 3 of 2026, signed 27 Feb 2026):**
- A safety certificate is required for buildings 20+ years past their completion certificate.
- It is valid for 10 years, or 5 years once the building is 40+.
- The report must come from a DM-registered licensed engineering office.
- The Art. 7(d) checklist covers: structure; external cladding; electrical and mechanical systems in common areas;
  windows, doors and barriers; Civil Defence; and SIRA CCTV.
- Fines run from AED 100k to 1M (2M for repeats), and the authorities can suspend Ejari lease registration.
- The DM circular of 9 Oct 2026 sets 7 steps on the Dubai Building Platform. Notices are staged, starting with
  multi-storey buildings aged 40+.

**Pain by person:**

| Who | Pain |
|---|---|
| Engineering office | Paper, WhatsApp photos and Word reports; days per building; a demand wave is coming |
| Property manager / owners' association | No view of found, fixed or still open; contractors paid before fixes are checked |
| Owner / landlord | Fines and loss of Ejari if the certificate is late |
| Residents / office staff | Report faults by phone; nobody confirms the fix; issues return |

**Gap:** defect apps such as PlanRadar log photos but don't map them to Law 3 clauses. Generic AI describes photos but
can't keep a signed, versioned record. Nothing links "defect found" to "fix proven" to "contractor paid".

---

## 3. Solution (what to build)

### 3.1 The engine: Diwan's shared record (exists in Diwan; rebuild fresh here)
Diwan stores everything as **Person, Case, Fact, Task, Document, Approval and Event**, in an append-only event log
(`diwan/events.py`, SQLite) feeding a knowledge graph (`diwan/graph.py`).

**Fact-pinned approval** (the core idea; never break it):
- An approval is bound to the exact fact versions it relied on (e.g. defect frame, bank account, amount).
- If a pinned fact is superseded (`fact.superseded`), the approval is cancelled automatically.
- Only the tasks that depend on that fact reopen (`task.reopened`), and Compliance is alerted first.
- Events are never updated or deleted. A repeated key returns the stored event.

### 3.2 Site Witness flow (new agent)
1. **Pick the rulebook:** Law 3 Art. 7(d), or the DHA clinic checklist. Clauses are versioned, and each report records
   the clause version it used.
2. **Walk:** the engineer films on a phone. This must work **offline-first** and sync later.
3. **Agent verdict per clause:** exactly one of `issue_found`, `needs_human` or `no_issue_seen`. **Never `pass`.** Each
   verdict links proof frames (video timestamps or stills).
4. **Engineer review and sign:** accept, edit or reject each verdict. Nothing reaches the report unsigned.
5. **Fixes become tasks** with an owner, deadline and cost.
6. **Verify the fix:** a task closes only when a new photo or video of the fix is matched to the original frame.
7. **Payment unlock:** the contractor payment approval is pinned to {fix verified, bank account, amount}. A bank
   change stops payment and raises a Compliance alert.
8. **Export:** the signed report and evidence pack for the Dubai Building Platform. The Ejari risk flag clears on
   linked units.

**Model gate:** a new AI model must be approved by a human before use. Each report stores the model version it used.

**Outage resilience:** offline walks; if the cloud or email goes down, jobs queue locally and sync with idempotent
keys, so nothing is lost or sent twice.

### 3.3 End-user side: voice requests and device control
- **Residents:** "corridor light on floor 4 is out" (English or Arabic) becomes a task, which closes only when the
  camera sees it working.
- **Meeting rooms:** "open the Al Noor project slides", "AC to 22", "lights to 30%" or "شغّل الشاشة". The room hub
  executes the command and the room camera confirms it.
- **Voice match:** only enrolled staff voices can give commands. Sensitive actions (send a report, pay) need a tap.

**Device connectivity (Bluetooth alone is NOT the plan):**
- One **room hub** per room: a mini PC or Raspberry Pi running **Home Assistant** (2,000+ integrations; agent access
  since 2026.10), with Wi-Fi, BLE, an IR blaster and Matter/Thread.
- Channels: HDMI-CEC for screens, infrared for split ACs and TVs, Wi-Fi plugs for lights, Matter for new devices,
  Crestron or Extron for office AV where present, and BACnet or Modbus gateways for building systems (engineer approval
  only).
- Flow: Diwan sends the command, the hub picks the channel, the device acts, and the camera confirms. Then an event is
  logged.
- The phone is only for setup: point at a device, name it, test it.
- Devices with no interface get **guiding mode**: tell the person which button to press, then confirm on camera.
- Anything that moves or heats needs human approval the first time, within set limits.
- **Championship demo:** one room, one hub, four devices: a screen (CEC), an AC (IR), lights (Wi-Fi plug) and the deck
  on a laptop.

### 3.4 Diwan rooms involved (existing)

| Room | Role for Site Witness |
|---|---|
| Finance | Contractor invoices, VAT, payment only after a verified fix |
| Compliance | Bank-change alerts, contractor AML, audit trail |
| Operations | Fix job board, deadlines, contractor performance |
| Front Desk | Voice and WhatsApp requests |
| Records | Signed reports, evidence packs, certificate expiry reminders |
| Deals | Ejari risk shown on units being leased or sold |
| **Buildings (new)** | Site Witness home: buildings, walks, clauses, verdicts, fixes |

---

## 4. Market (our estimates, not official)

| Segment | Role | Size |
|---|---|---|
| DM-registered engineering offices | First payer: write and sign the report | Hundreds |
| Property managers / owners' associations | Fix tracking, verified payments, dashboard | Buildings aged 20+: ~35k–49k |
| Landlords / owners | Owner portal, Ejari risk | Tens of thousands |
| DHA clinics (second rulebook) | Facility checklist | 5,931 facilities (H1 2026) |
| Residents / staff | Free users | — |

TAM is roughly AED 22–186M for the first wave, then AED 5–46M a year. A realistic target by end-2027 is AED 0.3–3M a
year. Pricing to test: a fee per building report, plus a monthly fee per building for fix tracking.

---

## 5. What makes it different

| Usual | Ours |
|---|---|
| AI says pass or fail | Never "pass"; 3 verdicts with proof frames; the engineer signs |
| Photos logged | Mapped to versioned Law 3 clauses |
| Job closed by a tick | Closed only when the camera sees the fix |
| Paid from an invoice | Payment pinned to verified fix, bank account and amount |
| Approvals survive fact changes | Auto-cancelled when a pinned fact changes |
| Model swapped silently | Human-approved model gate; version recorded per report |
| Cloud down, work stops | Offline walks plus a local queue |
| Voice assistant obeys anyone | Voice match plus a tap for sensitive actions |

We are NOT building a robot, a replacement for the engineer, or a general chatbot.

---

## 6. Codebase facts (the Diwan repo, for reference; not this repo)

> Note: Diwan's `video.py` only makes Zoom / Google Meet links; it does not process video.

- **Backend:** Python, FastAPI 0.115.6, uvicorn, websockets, pillow, python-multipart, faster-whisper (local speech to
  text), pytest. Entry point: `diwan/app.py` (~2,600 lines) with routers (`access`, `brand`, `knowledge`,
  `lobby_room`, `desk`, `floor`). Static UI is mounted with `app.mount("/web", StaticFiles(directory=WEB))`.
- **Run:**
  ```
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
  cp .env.example .env   # META_API_KEY, BASETEN_API_KEY, Supabase keys
  .venv/bin/uvicorn diwan.app:app --port 8030
  ```
- **Core modules:** `events.py` (append-only log; event types in `TYPES`; add new ones there), `graph.py`
  (Node/Graph), `office.py`, `roles.py`, `desk_rules.py`, `deal_gates.py`, `signing.py`, `invoices.py`,
  `documents.py`, `voicenotes.py`, `video.py`.
- **Agents:** `diwan/agents/*.py`. Each agent has a written charter (`charters.py`) and a module docstring stating its
  duties and limits (see `compliance.py`). Existing agents include compliance, finance, operations, records,
  frontdesk, reception, scribe, nova (chief of staff), review, watch, visual and others.
- **Providers:** `diwan/providers/` (email, storage, supabase_auth, local_asr, chat, meta, aisensy and others).
- **Frontend:** vanilla HTML, CSS and JS in `web/`. Shared tokens are in `app.css` and helpers in `app.js`. Pages:
  index, deal, studio, inbox, calendar, docs, graph, knowledge, lobby, login, meeting, office3d (three.js r128),
  personal, qualify, sales, settings, sign, team, catalog, deck. Many pages carry heavy inline JS (deal.html ~115KB,
  studio.html ~120KB).
- **Tests:** `tests/` (pytest), `e2e/` (flow scripts), `evals/`.
- **Design tokens:** `--bg #0a0d13`, `--gold #e8c77a`, `--teal #5ccfb5`; headings in Instrument Serif. Dark by
  default.

---

## 7. Build plan

| Phase | Dates | Scope |
|---|---|---|
| 1. Shell | 17–23 Nov | New navigation and design system |
| 2. Core | 24 Nov–7 Dec | Today, Approvals, sign-up flow |
| 3. Agents | 8–28 Dec | Site Witness walk to sign to verify to pay; room hub demo |
| Submit | 2 Jan 2027 | Deadline 4 Jan |
| 4. Pilot | Jan–Feb 2027 | Remaining rooms, first pilots |

**Navigation redesign:** five areas (Today / Clients / Deals / Back office / **Buildings (new)**) across 19 rooms.
Includes about 12 shared components, Arabic RTL, a light mode and accessibility.

**Suggested new code (Site Witness):**
- `diwan/agents/site_witness.py`: clause matching, verdicts and proof frames. Never emits pass.
- `diwan/rulebooks/law3_art7d.json` and `diwan/rulebooks/dha_clinic.json`: versioned clause libraries.
- `diwan/buildings.py`: Building, Walk, Verdict and FixTask, built on the existing graph and events.
- New event types: `walk.started`, `walk.synced`, `verdict.proposed`, `verdict.signed`, `fix.requested`,
  `fix.verified`, `report.exported`, `model.approved`, `device.command`, `device.confirmed`.
- `diwan/devices/hub.py`: a Home Assistant client (REST or WebSocket), with commands logged and confirmed.
- `web/buildings.html`: walk, review and sign, verify the fix, owner view, trust tab.

**Championship deliverables:**
- [ ] Prototype judges can test in a browser, with no install
- [ ] 2-minute demo: walk, verdicts, sign, fix verified, payment unlocked
- [ ] 6-minute pitch video
- [ ] Business Model Canvas
- [ ] Agent Card: what the agent does, its limits, and where a human decides
- [ ] Room hub demo (4 devices)
- [ ] 5–10 interviews with engineering offices and property managers
- [ ] **All code written fresh for the entry; no copied repo code** (Championship rule; fully commercialised products
  are excluded, so enter Site Witness as a new agent)

**Judging weights:** Real Value 20, Technical 20, Business 20, Trust and Human Oversight 15, Innovation 15, Pitch 10.

---

## 8. Rules for the AI assistant working in this repo

1. Never let the agent mark anything as "pass", "safe" or "compliant". Only a signed human verdict can.
2. Every state change is an event in `events.py`. Never update or delete rows.
3. Every approval pins the fact versions it relied on. A superseded fact must invalidate it.
4. Money, legal filings, public posts and device actions that move or heat need human approval.
5. Offline-first for walks; idempotent keys for every sync and send.
6. Bilingual: English and Arabic (RTL) for every user-facing string.
7. Keep the vanilla JS frontend. Reuse `app.css` tokens and `app.js` helpers; don't add a framework without asking.
8. Add tests for each new rule: pytest in `tests/`, plus an e2e flow in `e2e/`.
9. All demo names and records are fictional.

---

## 9. Risks and open questions

| Risk | Fallback |
|---|---|
| DM rollout slower than expected | Lead with the DHA clinic checklist |
| Engineers fear blame or replacement | AI never passes; the engineer signs and keeps the fee |
| No Dubai Building Platform API | Export an upload-ready evidence pack |
| Brands block device control | Hub covers IR, CEC and Wi-Fi; guiding mode for the rest |
| PlanRadar, HITEK or New Nordic add Law 3 | Our edge is the fix-to-payment chain and fact-pinned approvals |
| Not enough time | Cut the end-user side to one meeting-room demo |

Open questions: which 2–3 engineering offices will pilot, and at what price? Does DM accept video-frame evidence? What
are the global hackathon's rules? Push access to the repo is needed for PRs.

## 10. Reference files
- Mockups (HTML, open in a browser): `docs/mockups/diwan-site-witness-mockup.html` (full Diwan shell with linked
  Finance, Compliance and Site Witness), `docs/mockups/diwan-onboarding-3d-mockup.html` (office and user sign-up;
  the office is laid out as the 5 areas, and each office type lights up its own rooms), `site-witness-mockup.html`
  (not yet in the repo).
- Docs: "Diwan + Site Witness: project summary" (`docs/project-summary.md`), "Site Witness: solution and feature
  plan" (not yet in the repo), "Diwan visual redesign plan" (not yet in the repo).

## 11. Rooms per office type (sign-up)

Full design of every room (agents, what starts them, where a person decides, hands-to, never) and the best-case
story: `docs/rooms-and-agents.md`. It is **generated**: edit `docs/mockups/rooms-data.js` (or the room list in the
sign-up mockup), then run `node scripts/build-rooms-doc.mjs`. Never edit the .md by hand.

Every office: Front Desk, Approvals, Finance, Compliance, Records.

| Office type | Adds |
|---|---|
| Real-estate brokerage | Leads, Deals, Listings, Signing & DLD, Meetings |
| Property manager / owners' association | Buildings, Fix jobs, Residents, Leasing & Ejari, Contractors, Devices |
| Licensed engineering office | Site Witness, Review & Sign, Fix Verify, Reports & Export, Contractors |
| Clinic | Patients, DHA checks, Medicines, Devices, Staff rota |

Areas: Today (Front Desk, Approvals, Meetings) · Clients (Leads, Residents, Patients) · Deals (Deals, Listings,
Signing & DLD, Leasing & Ejari) · Buildings (Buildings, Site Witness, Review & Sign, Fix Verify, Fix jobs, DHA checks,
Devices) · Back office (Finance, Compliance, Records, Reports & Export, Contractors, Medicines, Staff rota).
