/* Rooms and agents: the one source for the room view in diwan-onboarding-3d-mockup.html
   and for docs/rooms-and-agents.md (built by scripts/build-rooms-doc.mjs).
   All names, buildings and figures are made up (sample data).
   status: working | waiting (for a person) | idle */
(function (root) {
const ROOM_DETAIL = {

/* ---------------- TODAY ---------------- */
desk: {
  starts: ['A new WhatsApp, email or voice message', '08:00 every day'],
  agents: [
    { name: 'Receptionist', does: 'Reads every message in English or Arabic, works out what it is about and sends it to the right room.',
      tools: ['WhatsApp', 'Email', 'Speech to text'], decides: 'A reply that mentions money, dates or legal terms waits in Approvals.',
      now: 'Sorting a WhatsApp from Flat 504', status: 'working',
      last: ['DM notice for Al Noor Residence → Buildings', 'Voice note “corridor light out” → Residents', 'Quote request from a landlord → Approvals'] },
    { name: 'Morning Brief', does: 'Writes the owner’s 20-second briefing from today’s facts, in English and Arabic.',
      tools: ['Event log', 'Text to speech'], decides: 'Nothing: it only reads and reports.',
      now: 'Brief sent at 08:00', status: 'idle',
      last: ['Brief: 3 findings to sign, 1 payment waiting', 'Brief: certificate due 15 May 2027', 'Brief: contractor fix filmed'] } ],
  never: ['Promise a price, a date or a legal outcome', 'Reply to a client about money without approval'],
  hands: ['buildings', 'residents', 'approvals', 'leads'],
  waiting: [{ t: 'Reply to Karim H.: proposed visit date 18 Nov', who: 'Owner' }],
  feed: ['08:00 Morning brief sent (EN + AR)', '09:12 DM notice read → Buildings', '09:40 Voice note from Flat 504 → Residents'] },

approvals: {
  starts: ['Any agent asks a person to decide'],
  agents: [
    { name: 'Approval Clerk', does: 'Collects everything waiting for a person, shows the exact facts each item rests on, and cancels the item by itself if one of those facts changes.',
      tools: ['Event log', 'Fact versions'], decides: 'Never decides. The named role holder taps yes or no.',
      now: 'Holding 3 items for the owner', status: 'waiting',
      last: ['Cancelled payment CON-311: bank account changed', 'Inspection quote accepted by owner', 'Export approved by Eng. R. Haddad'] } ],
  never: ['Approve anything itself', 'Keep an approval alive after a fact it rests on has changed'],
  hands: ['finance', 'reports', 'deals'],
  waiting: [{ t: 'Inspection quote, Al Noor Residence, AED 24,000', who: 'Owner' }, { t: 'Contractor payment CON-311, AED 1,942.50', who: 'Owner' }],
  feed: ['10:02 Quote sent for approval by Finance', '10:15 Owner accepted the quote', '10:16 Deposit invoice released to Finance'] },

meetings: {
  starts: ['A meeting starts (after everyone agrees to the recording)'],
  agents: [
    { name: 'Scribe', does: 'Asks for consent, transcribes, and keeps each fact with the speaker’s exact words.',
      tools: ['Speech to text (EN/AR)', 'Event log'], decides: 'The people in the meeting confirm each fact.',
      now: 'Waiting for the next meeting', status: 'idle',
      last: ['Consent given by 3 people', '7 facts kept with exact quotes', 'Meeting ended, notes filed'] },
    { name: 'Action Taker', does: 'Turns what was decided into tasks with an owner and a date.',
      tools: ['Tasks'], decides: 'The meeting owner confirms the task list.',
      now: '2 tasks waiting to be confirmed', status: 'waiting',
      last: ['Task: book contractor for stair B door', 'Task: send quote to owners’ association', 'Task: chase DCD certificate'] } ],
  never: ['Record without consent', 'Change what someone said'],
  hands: ['deals', 'fixjobs', 'approvals'],
  waiting: [{ t: 'Confirm 2 tasks from the Al Noor meeting', who: 'Meeting owner' }],
  feed: ['11:00 Consent given, recording started', '11:42 7 facts kept with quotes', '11:45 2 tasks drafted'] },

/* ---------------- CLIENTS ---------------- */
leads: {
  starts: ['A new enquiry arrives', 'A lead has been quiet for 3 days'],
  agents: [
    { name: 'Qualifier', does: 'Asks the few questions that matter (what, where, budget, when) and scores the lead.',
      tools: ['WhatsApp', 'Listings'], decides: 'The broker approves the first reply.',
      now: 'Qualifying an enquiry for a 2-bed in Deira', status: 'working',
      last: ['Lead scored hot: viewing this week', 'Lead not a fit: budget below range', 'First reply sent after broker OK'] },
    { name: 'Follow-up', does: 'Drafts a short, helpful follow-up when a lead goes quiet. Never more than two.',
      tools: ['WhatsApp', 'Calendar'], decides: 'The broker sends or skips each follow-up.',
      now: '1 follow-up drafted', status: 'waiting',
      last: ['Follow-up drafted for Omar’s lead', 'Lead opted out: stopped', 'Viewing booked for Thursday'] } ],
  never: ['Send more than two follow-ups', 'Contact someone who opted out'],
  hands: ['deals', 'meetings'],
  waiting: [{ t: 'Send follow-up to an enquiry from 12 Nov', who: 'Broker' }],
  feed: ['09:05 New enquiry from a portal', '09:06 Qualified: warm', '13:30 Follow-up drafted'] },

residents: {
  starts: ['A resident sends a voice note, photo or WhatsApp'],
  agents: [
    { name: 'Fault Desk', does: 'Turns “the corridor light on floor 4 is out” (English or Arabic) into a fault ticket with the place and a photo.',
      tools: ['Speech to text (EN/AR)', 'WhatsApp'], decides: 'The manager approves anything that costs money.',
      now: 'Ticket: corridor light, floor 4', status: 'working',
      last: ['Ticket: water leak, basement', 'Ticket: lift noise, block B', 'Duplicate report merged'] },
    { name: 'Resident Updates', does: 'Tells the resident what happens next, and again when the camera confirms it is fixed.',
      tools: ['WhatsApp'], decides: 'Nothing: it only sends status updates.',
      now: 'Update sent to Flat 504', status: 'idle',
      last: ['“Booked for tomorrow 10:00”', '“Fixed and checked on camera”', '“We need one more photo”'] } ],
  never: ['Close a fault because someone said it is fixed', 'Share one resident’s details with another'],
  hands: ['fixjobs', 'devices'],
  waiting: [{ t: 'Approve AED 350 call-out for the basement leak', who: 'Manager' }],
  feed: ['09:40 Voice note from Flat 504 (Arabic)', '09:41 Ticket created → Fix jobs', '09:42 Resident told: booked'] },

patients: {
  starts: ['A patient messages or calls'],
  agents: [
    { name: 'Booking Desk', does: 'Offers free slots that match the doctor and the patient’s need.',
      tools: ['Calendar', 'WhatsApp'], decides: 'Reception confirms anything outside normal hours.',
      now: 'Offering 3 slots for Tuesday', status: 'working',
      last: ['Booked: Tue 10:30', 'Moved: Wed 16:00', 'Reminder sent for tomorrow'] },
    { name: 'Patient Messages', does: 'Answers practical questions: hours, location, what to bring.',
      tools: ['WhatsApp'], decides: 'A clinician answers anything medical.',
      now: 'Passed a medical question to the doctor', status: 'waiting',
      last: ['Answered: parking', 'Answered: opening hours', 'Medical question → clinician'] } ],
  never: ['Give medical advice', 'Share patient details outside the clinic'],
  hands: ['rota', 'approvals'],
  waiting: [{ t: 'Patient question about medication dose', who: 'Clinician' }],
  feed: ['08:30 2 bookings made', '09:15 Medical question passed to clinician', '10:00 Reminders sent'] },

/* ---------------- DEALS ---------------- */
deals: {
  starts: ['An offer is accepted'],
  agents: [
    { name: 'Deal Desk', does: 'Moves each deal through its stages, lists the documents still missing, and stops at every gate.',
      tools: ['Documents', 'Tasks', 'Fact versions'], decides: 'The broker passes each gate.',
      now: 'Deal D-219: waiting for Ejari renewal', status: 'waiting',
      last: ['D-218: transfer booked', 'D-220: Oqood registered', 'D-219: Law 3 risk flagged'] } ],
  never: ['Pass a gate on old facts', 'Mark a deal ready for transfer by itself'],
  hands: ['signing', 'compliance', 'finance'],
  waiting: [{ t: 'D-218: confirm ready for transfer', who: 'Broker' }],
  feed: ['10:20 D-218 buyer screening clear', '10:21 Form B sent for signing', '12:05 D-219 Ejari risk from Law 3'] },

listings: {
  starts: ['A new listing is added', 'The posting schedule comes round'],
  agents: [
    { name: 'Listing Writer', does: 'Writes the listing from the facts (size, price, permit number) in English and Arabic.',
      tools: ['Listings', 'Photos'], decides: 'The broker approves every listing.',
      now: 'Drafting Unit 1208, Sample Heights', status: 'working',
      last: ['Listing drafted: Villa 12', 'Permit number checked', 'Price updated after owner change'] },
    { name: 'Post Planner', does: 'Plans social posts for listings and suggests the best time.',
      tools: ['Instagram', 'Calendar'], decides: 'A person approves every public post.',
      now: '2 posts waiting for approval', status: 'waiting',
      last: ['Post planned: Thursday 19:00', 'Post paused: unit sold', 'Reel script drafted'] } ],
  never: ['Publish anything without approval', 'Use a price the owner has not confirmed'],
  hands: ['leads'],
  waiting: [{ t: 'Approve Instagram post for Unit 1208', who: 'Broker' }],
  feed: ['09:00 Listing drafted (EN + AR)', '09:30 Post planned', '14:00 Post approved and scheduled'] },

signing: {
  starts: ['A deal reaches a signing stage'],
  agents: [
    { name: 'Form Builder', does: 'Fills Form A, B or I and the DLD paperwork from the deal’s facts.',
      tools: ['Documents', 'Fact versions'], decides: 'The broker checks the form before it goes out.',
      now: 'Form B ready for the buyer', status: 'waiting',
      last: ['Form A filled for Villa 12', 'Form I filled with co-broker', 'Form sent back: price changed'] },
    { name: 'Signature Tracker', does: 'Sends each person their own signing link and tracks who has signed.',
      tools: ['Signing links'], decides: 'Each party signs for themselves.',
      now: '1 of 2 signed', status: 'working',
      last: ['Seller signed Form A', 'Link renewed for buyer', 'Signed copy filed in Records'] } ],
  never: ['Sign for anyone', 'Let a link work on an old version of a form'],
  hands: ['records', 'deals'],
  waiting: [{ t: 'Check Form B before sending to the buyer', who: 'Broker' }],
  feed: ['10:21 Form B filled', '10:30 Link sent to buyer', '15:02 Seller signed Form A'] },

leasing: {
  starts: ['90 days before a lease renews', 'A building’s Law 3 status changes'],
  agents: [
    { name: 'Lease Tracker', does: 'Tracks every lease and starts renewals in good time.',
      tools: ['Leases', 'Calendar'], decides: 'The manager approves renewal terms.',
      now: 'Renewal for Flat 504 due 1 Feb 2027', status: 'working',
      last: ['Renewal started: Flat 504', 'Rent change flagged for owner', 'Lease filed'] },
    { name: 'Ejari Risk Watch', does: 'Flags units in buildings without a Law 3 certificate, and clears the flag when the report is submitted.',
      tools: ['Buildings', 'Reports'], decides: 'Nothing: it only raises and clears flags.',
      now: 'Watching 2 buildings', status: 'idle',
      last: ['Flag raised: Flat 504, Al Noor', 'Flag cleared: report submitted', 'Marina Court: not due yet'] } ],
  never: ['Tell a tenant a lease can be registered while the flag is open'],
  hands: ['deals', 'buildings'],
  waiting: [{ t: 'Approve renewal terms, Flat 504', who: 'Manager' }],
  feed: ['08:00 2 renewals within 90 days', '12:05 Ejari risk raised on Flat 504', '16:40 Risk cleared after export'] },

/* ---------------- BUILDINGS ---------------- */
buildings: {
  starts: ['A building is added', 'A Dubai Municipality notice arrives', 'Every morning'],
  agents: [
    { name: 'Building Register', does: 'Keeps each building’s age from its completion certificate, its Law 3 due date and its notices.',
      tools: ['Documents', 'Event log'], decides: 'Nothing: it records facts.',
      now: 'Al Noor Residence: 25 years old, due 15 May 2027', status: 'working',
      last: ['Al Noor added from DM notice', 'Marina Court: 22 years, no notice yet', 'Completion certificate read: 2001'] },
    { name: 'Deadline Watch', does: 'Counts down to each report deadline and asks for a walk to be booked in time.',
      tools: ['Calendar'], decides: 'The owner books the walk.',
      now: '181 days to the deadline', status: 'idle',
      last: ['Walk suggested for next week', 'Reminder: 6 months left', 'Certificate renewal set for 2037'] } ],
  never: ['Call a building safe or compliant'],
  hands: ['site', 'leasing'],
  waiting: [{ t: 'Book the safety walk for Al Noor Residence', who: 'Owner' }],
  feed: ['09:12 DM notice for Al Noor', '09:13 Building registered, due 15 May 2027', '09:14 Walk requested → Site Witness'] },

site: {
  starts: ['A walk video syncs from the engineer’s phone (it works offline)'],
  agents: [
    { name: 'Walk Reader', does: 'Takes the walk video and picks the clear frames for each area of the checklist.',
      tools: ['Video frames', 'Offline queue'], decides: 'Nothing: it prepares evidence.',
      now: 'Picking frames from 9 min 40 s of video', status: 'working',
      last: ['3 clips synced after offline', '212 frames picked', 'Low-light clip marked'] },
    { name: 'Clause Matcher', does: 'Checks each Law 3 clause and gives one of three verdicts: issue found, needs a human, no issue seen. Each verdict links its proof frames.',
      tools: ['Rulebook Law 3 Art. 7(d) v1.2', 'Vision model A v3'], decides: 'Nothing is final here: every verdict goes to Review & Sign.',
      now: 'Drafting verdicts: 13 so far', status: 'working',
      last: ['F2 exit sign not lit: issue found', 'S2 roof rebar: needs a human', 'F1 extinguisher: no issue seen'] },
    { name: 'Privacy Guard', does: 'Blurs faces and number plates before any frame is saved.',
      tools: ['Face and plate blur'], decides: 'Nothing: it always blurs.',
      now: '4 faces blurred', status: 'working',
      last: ['4 faces blurred', '1 plate blurred', 'Frames saved'] } ],
  never: ['Say “pass”, “safe” or “compliant”', 'Save a frame before it is blurred', 'Guess a measurement from video'],
  hands: ['review'],
  waiting: [],
  feed: ['09:10 Walk synced (3 clips were offline)', '09:11 Faces blurred', '09:12 13 findings drafted with model A v3'] },

review: {
  starts: ['Draft findings are ready'],
  agents: [
    { name: 'Review Prep', does: 'Lines up each finding with its proof frame, the narration quote and the clause.',
      tools: ['Findings', 'Frames'], decides: 'The engineer accepts, edits or overturns each finding.',
      now: '13 findings ready for Eng. R. Haddad', status: 'waiting',
      last: ['F2 lined up with frame 03:50', 'S3 sent to lab check', 'C2 needs a certificate'] },
    { name: 'Report Lock', does: 'Keeps the report locked until every finding is signed.',
      tools: ['Signatures'], decides: 'The engineer signs.',
      now: 'Locked: 13 still to sign', status: 'waiting',
      last: ['Locked', '6 of 13 signed', 'Released: all signed'] } ],
  never: ['Sign for the engineer', 'Release a report with an unsigned finding'],
  hands: ['reports', 'fixjobs'],
  waiting: [{ t: 'Sign 13 findings, Al Noor Residence', who: 'Engineer' }],
  feed: ['09:20 13 findings ready', '10:05 Engineer signed 13 of 13', '10:05 Report released'] },

verify: {
  starts: ['A contractor uploads a re-filmed fix'],
  agents: [
    { name: 'Fix Matcher', does: 'Matches the new frame to the original spot and says “fix seen” or “unsure”. Unsure stays open.',
      tools: ['Frames', 'Vision model A v3'], decides: 'The engineer closes the finding.',
      now: 'F2: fix seen, same door and wall', status: 'waiting',
      last: ['F2: fix seen', 'W1: unsure, asked for a closer shot', 'E1: fix seen'] } ],
  never: ['Close a finding by itself', 'Treat “unsure” as fixed'],
  hands: ['finance', 'records'],
  waiting: [{ t: 'Close F2: exit sign now lit', who: 'Engineer' }],
  feed: ['14:00 Re-film uploaded for F2', '14:01 Fix seen (same position)', '14:20 Engineer closed F2'] },

fixjobs: {
  starts: ['A finding is signed as an issue', 'A resident fault ticket arrives'],
  agents: [
    { name: 'Job Builder', does: 'Turns each issue into a job with an owner, a deadline and a cost estimate.',
      tools: ['Tasks', 'Contractors'], decides: 'The manager assigns the job and approves the cost.',
      now: 'Job for F2: exit sign, stair A', status: 'waiting',
      last: ['Job: F2 exit sign', 'Job: W1 door closer', 'Job: E1 board labels'] },
    { name: 'Chaser', does: 'Reminds the contractor before the deadline and tells the manager if it slips.',
      tools: ['WhatsApp', 'Calendar'], decides: 'Nothing: it reminds.',
      now: 'Reminder due tomorrow', status: 'idle',
      last: ['Reminder sent: 2 days left', 'Deadline slipped: manager told', 'Contractor confirmed visit'] } ],
  never: ['Mark a job done without Fix Verify'],
  hands: ['contractors', 'verify'],
  waiting: [{ t: 'Assign F2 to Sample Contracting LLC', who: 'Manager' }],
  feed: ['10:06 4 jobs from the signed report', '10:30 F2 assigned', '13:00 Contractor on site'] },

dha: {
  starts: ['Every week, before DHA visits'],
  agents: [
    { name: 'Clinic Walk', does: 'Runs the same walk-and-verdict engine with the DHA checklist instead of Law 3.',
      tools: ['Rulebook DHA outpatient v1.0', 'Video frames'], decides: 'The medical director signs each finding.',
      now: 'Weekly walk: 5 findings drafted', status: 'waiting',
      last: ['D1 sharps box full: issue found', 'D3 expired medicine: issue found', 'D5 crash cart seal: needs a human'] } ],
  never: ['Say a clinic passes DHA'],
  hands: ['medicines', 'fixjobs'],
  waiting: [{ t: 'Sign 5 findings, Sample Family Clinic', who: 'Medical director' }],
  feed: ['07:30 Weekly walk synced', '07:32 5 findings drafted', '08:10 2 jobs created'] },

devices: {
  starts: ['A staff member or resident says a command (voice matched)'],
  agents: [
    { name: 'Hub Operator', does: 'Sends the command to the room hub (screen, AC, lights) and waits for the room camera to confirm.',
      tools: ['Home Assistant hub', 'HDMI-CEC', 'Infrared', 'Wi-Fi plugs', 'Room camera'], decides: 'A tap for sensitive actions, and the first time anything heats or moves.',
      now: 'AC set to 22°, display confirmed', status: 'working',
      last: ['Screen on, slides opened, camera confirmed', 'Lights to 30%, camera confirmed', '“Send the report”: waiting for tap'] },
    { name: 'Device Setup', does: 'Point the phone at a device, name it, test it.',
      tools: ['Phone camera', 'Hub discovery'], decides: 'The person approves each new device.',
      now: '4 devices set up', status: 'idle',
      last: ['Screen found: infrared', 'AC found: Wi-Fi', 'Lights found: smart switch'] },
    { name: 'Guide', does: 'For devices with no connection, tells the person which button to press, then checks on camera.',
      tools: ['Room camera'], decides: 'Nothing: it guides.',
      now: 'Idle', status: 'idle',
      last: ['“Press the blue button on the left”', 'Projector on, confirmed', 'Asked for a photo of the panel'] } ],
  never: ['Act on a voice it does not recognise', 'Send, pay or sign without a tap', 'Say done before the camera confirms'],
  hands: ['records', 'residents'],
  waiting: [{ t: 'Send “Al Noor Law 3 report.pdf” to the client', who: 'Staff member' }],
  feed: ['10:00 “AC to 22” (voice matched)', '10:00 Display reads 22°, confirmed', '10:05 Slides opened, confirmed'] },

/* ---------------- BACK OFFICE ---------------- */
finance: {
  starts: ['A report is signed (fee invoice)', 'A fix is verified (contractor payment)'],
  agents: [
    { name: 'Invoice Writer', does: 'Writes invoices with TRN and 5% VAT from the agreed facts.',
      tools: ['Invoices', 'Fact versions'], decides: 'The owner approves each invoice before it goes out.',
      now: 'SW-007 ready to issue', status: 'waiting',
      last: ['Deposit invoice: AED 12,000 + VAT', 'SW-007 Law 3 report fee drafted', 'Credit note for a cancelled visit'] },
    { name: 'Payment Gate', does: 'Lets a payment through only while its pinned facts hold: fix verified, the same bank account, the agreed amount.',
      tools: ['Fact versions', 'Approvals'], decides: 'The owner approves every payment.',
      now: 'CON-311: fix ✓ bank ✓ amount ✓', status: 'waiting',
      last: ['CON-311 unlocked: F2 verified', 'Stopped a payment: bank changed', 'Paid: AED 1,942.50'] } ],
  never: ['Pay anyone by itself', 'Pay after a pinned fact has changed'],
  hands: ['records', 'compliance'],
  waiting: [{ t: 'Approve CON-311, AED 1,942.50 to ****4417', who: 'Owner' }],
  feed: ['10:16 Deposit invoice issued', '14:21 CON-311 unlocked by F2 verified', '14:30 Owner approved, paid'] },

compliance: {
  starts: ['A new client or contractor', 'Someone changes bank details', 'A cash payment over AED 55,000'],
  agents: [
    { name: 'Screener', does: 'Checks clients and contractors against sanctions and PEP lists.',
      tools: ['Screening lists'], decides: 'The compliance officer clears any match.',
      now: 'Sample Contracting LLC: clear', status: 'idle',
      last: ['Contractor screened: clear', 'Buyer screened: clear', 'Possible match sent to officer'] },
    { name: 'Bank-Change Guard', does: 'When bank details change, stops every payment that rested on the old account and alerts the officer first.',
      tools: ['Fact versions', 'Approvals'], decides: 'The officer verifies the new account by phone.',
      now: 'No changes today', status: 'idle',
      last: ['Bank change on CON-311: payment stopped', 'Verified by phone', 'Payment allowed again'] },
    { name: 'goAML Drafter', does: 'Drafts the real-estate report for cash over AED 55,000.',
      tools: ['goAML form'], decides: 'The MLRO files it.',
      now: '1 report drafted', status: 'waiting',
      last: ['Drafted: D-218 cash AED 60,000', 'Filed by MLRO', 'Reminder: 2 days to file'] } ],
  never: ['File with the regulator by itself', 'Tell a client they were reported'],
  hands: ['approvals', 'finance'],
  waiting: [{ t: 'File goAML report for D-218', who: 'MLRO' }],
  feed: ['10:40 Contractor screened: clear', '11:10 goAML report drafted', '15:00 MLRO filed'] },

records: {
  starts: ['Every event in every room', 'Every morning (expiry check)'],
  agents: [
    { name: 'Record Keeper', does: 'Keeps the one event log. Facts are replaced by new versions, never edited or deleted.',
      tools: ['Event log'], decides: 'Nothing: it records.',
      now: '1,284 events today', status: 'working',
      last: ['F2 closed: camera + engineer', 'CON-311 paid', 'Report exported with model A v3'] },
    { name: 'Expiry Watch', does: 'Reminds before certificates expire: 10 years, or 5 once a building is 40.',
      tools: ['Calendar'], decides: 'The owner books the renewal.',
      now: 'Al Noor renewal set for 2037', status: 'idle',
      last: ['Renewal reminder set: 2037', 'DCD certificate expires in 30 days', 'Trade licence renewal flagged'] } ],
  never: ['Edit or delete an event'],
  hands: ['buildings'],
  waiting: [],
  feed: ['09:10 Walk synced', '10:05 13 findings signed', '14:30 CON-311 paid'] },

reports: {
  starts: ['Every finding in a report is signed'],
  agents: [
    { name: 'Pack Builder', does: 'Builds the signed report and evidence pack: findings, proof frames, clause version and model version.',
      tools: ['Documents', 'Frames'], decides: 'The engineer approves the export.',
      now: 'Evidence pack ready: 42 pages, 31 frames', status: 'waiting',
      last: ['Pack built: Al Noor', 'Clause version Law 3 v1.2 stamped', 'Model A v3 stamped'] } ],
  never: ['Export a report that is not fully signed', 'Leave out the model or clause version'],
  hands: ['buildings', 'leasing', 'finance'],
  waiting: [{ t: 'Approve export to the Dubai Building Platform', who: 'Engineer' }],
  feed: ['10:06 Pack built', '10:20 Engineer approved export', '10:21 Upload-ready pack saved'] },

contractors: {
  starts: ['A fix job is created'],
  agents: [
    { name: 'Quote Collector', does: 'Asks approved contractors for quotes and lines them up side by side.',
      tools: ['WhatsApp', 'Email'], decides: 'The manager picks a quote.',
      now: '3 quotes for F2', status: 'waiting',
      last: ['Quote: AED 1,850 (Sample Contracting)', 'Quote: AED 2,300', 'Quote declined'] },
    { name: 'Contractor Score', does: 'Scores each contractor on time, cost and rework.',
      tools: ['Fix jobs', 'Fix Verify'], decides: 'Nothing: it reports.',
      now: 'Sample Contracting: 4.6 / 5', status: 'idle',
      last: ['On time: 9 of 10 jobs', 'Rework: 1 of 10', 'Score updated'] } ],
  never: ['Hire a contractor who has not been screened'],
  hands: ['fixjobs', 'compliance', 'finance'],
  waiting: [{ t: 'Pick a quote for F2', who: 'Manager' }],
  feed: ['10:31 Quotes requested', '12:00 3 quotes in', '12:10 Manager picked AED 1,850'] },

medicines: {
  starts: ['Every morning', 'A DHA check finds a medicine problem'],
  agents: [
    { name: 'Stock & Expiry Watch', does: 'Tracks stock and expiry dates and asks for reorders.',
      tools: ['Stock list'], decides: 'The pharmacist approves removals and orders.',
      now: '1 expired box to remove', status: 'waiting',
      last: ['Expired box found (DHA walk)', 'Reorder suggested: gloves', 'Fridge log uploaded'] } ],
  never: ['Order or remove medicines by itself'],
  hands: ['dha'],
  waiting: [{ t: 'Remove expired box, shelf 3', who: 'Pharmacist' }],
  feed: ['07:35 Expired box flagged', '09:00 Reorder suggested', '11:00 Pharmacist removed box'] },

rota: {
  starts: ['Every week', 'A staff licence expires within 60 days'],
  agents: [
    { name: 'Rota Planner', does: 'Drafts next week’s shifts from bookings and leave.',
      tools: ['Calendar', 'Bookings'], decides: 'The manager approves the rota.',
      now: 'Next week drafted', status: 'waiting',
      last: ['Rota drafted', 'Gap on Thursday flagged', 'Swap approved'] },
    { name: 'Licence Watch', does: 'Warns before a DHA staff licence expires.',
      tools: ['Staff records'], decides: 'The manager arranges renewal.',
      now: '1 licence expires in 45 days', status: 'idle',
      last: ['Licence alert: 45 days', 'Renewal uploaded', 'All licences valid'] } ],
  never: ['Publish a rota without approval'],
  hands: ['patients'],
  waiting: [{ t: 'Approve rota for next week', who: 'Manager' }],
  feed: ['08:00 Rota drafted', '08:01 Thursday gap flagged', '12:00 Manager approved'] },
};

/* The best case, end to end: engineering office, Al Noor Residence (sample).
   Each step is one room; agent = index into that room's agents. */
const STORY = [
  { room: 'desk', agent: 0, title: 'A notice arrives', text: 'The Receptionist reads a Dubai Municipality notice for Al Noor Residence and sends it to Buildings.', now: 'DM notice → Buildings' },
  { room: 'buildings', agent: 0, title: 'The building is registered', text: 'Building Register: completion 2001, 25 years old, report due 15 May 2027.', now: 'Al Noor: due 15 May 2027' },
  { room: 'approvals', agent: 0, title: 'The owner says yes', text: 'The owner accepts the inspection quote, AED 24,000. Finance writes the deposit invoice.', now: 'Quote accepted by owner' },
  { room: 'site', agent: 1, title: 'The walk is checked', text: 'The engineer films offline; the walk syncs. Faces are blurred, frames picked, and 13 findings drafted. Never “pass”.', now: 'F2 exit sign: issue found' },
  { room: 'review', agent: 1, title: 'The engineer signs', text: 'Eng. R. Haddad checks each proof frame and signs all 13 findings. The report unlocks.', now: '13 of 13 signed' },
  { room: 'reports', agent: 0, title: 'The report is exported', text: 'The evidence pack carries the clause version and model version. The engineer approves the export.', now: 'Export approved' },
  { room: 'leasing', agent: 1, title: 'Ejari risk clears', text: 'The report is submitted, so the Ejari risk on Flat 504 clears.', now: 'Flag cleared: Flat 504' },
  { room: 'fixjobs', agent: 0, title: 'A fix job is made', text: 'Finding F2 (exit sign not lit, stair A) becomes a job with an owner, a deadline and a cost.', now: 'Job: F2 exit sign' },
  { room: 'contractors', agent: 0, title: 'A contractor is chosen', text: 'Three quotes come in. The manager picks Sample Contracting LLC at AED 1,850.', now: 'Picked: AED 1,850' },
  { room: 'compliance', agent: 0, title: 'The contractor is screened', text: 'Sanctions and PEP checks are clear.', now: 'Sample Contracting: clear' },
  { room: 'verify', agent: 0, title: 'The fix is proven on camera', text: 'The contractor re-films. The Fix Matcher sees the lit sign in the same spot; the engineer closes F2.', now: 'F2: fix seen → closed' },
  { room: 'finance', agent: 1, title: 'The contractor is paid', text: 'Payment Gate: fix ✓ bank ✓ amount ✓. The owner approves AED 1,942.50.', now: 'CON-311: paid', twist: true },
  { room: 'records', agent: 0, title: 'Everything is on record', text: 'Every step is in the event log. A renewal reminder is set for 2037.', now: 'Trail complete' },
];

root.ROOM_DETAIL = ROOM_DETAIL; root.STORY = STORY;
if (typeof module !== 'undefined') module.exports = { ROOM_DETAIL, STORY };
})(typeof window !== 'undefined' ? window : globalThis);
