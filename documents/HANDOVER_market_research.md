# Handover: Sapcon Instruments — Market Research

This is a separate workstream from the personal CRM software being built in this same
folder (`D:\Sapcon Personal Software`). You do not need the CRM's technical details —
different task, different deliverable. This doc gives you what's actually relevant.

## Who the client is

Sapcon Instruments — Indian manufacturer of level and speed-monitoring instruments,
40+ years in process control instrumentation, based in Indore (131 Palshikar Colony;
new manufacturing facility, 60,000 sq ft, Sanwer Road, Indore). Sold through channel
partners/OEMs/consultants into process industries: cement, steel, pharma, dairy,
fertilizer, edible oil, and others.

Leadership: Rajendra R. Palshikar (Director, Finance & Accounts), Ashwin R. Palshikar
(Director, Business Development — MBA, S.P. Jain Institute of Management & Research).
The user's uncle runs marketing/business development and travels ~250 days/year meeting
channel partners, OEMs, consultants, and end users.

Headline claims (from their own decks — treat as marketing copy, not verified figures):
90,000+ successful installations, 8,000+ clients, exports to 90+ countries. A "Last 5
Year Growth" chart runs FY2018-19 through FY2022-23 (i.e. stale — doesn't cover the last
~2-3 years).

## What this task actually is

**Not yet scoped.** The user said market research for the company is a task to do, but
hasn't specified what kind: competitive landscape, industry/segment sizing, expansion
opportunities into new industries, pricing benchmarking, something else. Ask before
doing significant work.

## Source materials available (in this `documents/` folder)

- `Dairy Industry Presentation.pdf`, `Pharma Presentation.pdf`, `Sapcon Presentation
  Edible Oil.pdf` — three sales decks, industry-specific variants of the same ~29-slide
  template (cover → "Virtuous Cycle" → leadership → plant → manufacturing process →
  experience stats → certifications → industry client list → order-copy proof →
  industry applications → product spec slides → coatings → growth chart → about
  us/highlights/presence → manufacturing process (PMI/XRF, welding) → team → "Why
  Sapcon" → contact. Read them directly if you need product/industry detail — don't
  rely on secondhand summary.

- `Visit Scoop+Exhibition call List Updated (5).xlsx` — a spreadsheet the uncle's office
  boy maintains, an **unorganized historical log of past meetings/visits/exhibition
  calls**. The user was explicit: this is NOT for CRM import, it's just background
  colour on where the uncle has been and what kind of business he does. Useful context
  for market research (shows real geography/industries/contact patterns), but don't
  treat its structure as authoritative or worth cleaning up.

## Product lines mentioned across the decks (by industry variant)

- **Dairy**: Elixir, Elixir T-Uni, SLC, Coat Endure, CAPVEL_ICT (capacitance level
  transmitter), SAP-Sonic (ultrasonic level transmitter), SAP-Flow (electromagnetic flow
  meter), hydrostatic pressure level transmitter, Orbit (rotary paddle level switch),
  SLA_M/B (RF admittance level switch), magnetic level switch.
- **Pharma**: adds Vital, SLW (conductive level switch), Orbit paddle type detail slide.
- **Edible Oil**: adds Vital, Elefant (deoiled-toaster application), Smart SSI (speed
  monitoring system, over/under-speed alarm).

Common instrument categories across all three: level switches (high/low detection,
overfill/dry-run, hazardous-area rated), level sensors/transmitters (continuous
monitoring), speed monitoring, flow metering. Special-application coatings: Halar
(ECTFE) and PFA coated, for corrosion/weathering resistance.

Certifications claimed: CIMFR flame-proof housing IIC (note: misspelled "CMIFR" in two
of the three decks), EIL certified, IP-68, IEC 60529/60079/61000, CISPR 11, intrinsic
safety, CE/ISI/CCOE/PESO, ISO 9001.

Named clients (from the Pharma deck's client list + order-copy proof slides): Cipla,
Lupin, Mylan, Ipca, Symbiotec, Sun Pharma, Dr. Reddy's, Dabur, Jubilant Generics, Indo
German Pharma Engineers, and others visible in the order-copy scans.

## Issues found while reviewing the decks (context, not necessarily in scope)

Flagged to the user already, in case it's relevant to whatever the research task turns
into (e.g. if positioning/competitive-differentiation is part of the ask):
- All three decks' final "Get in Touch" slide links to `sapconinstruments.com/cement` —
  a leftover from a cement-industry version, on decks for dairy/pharma/edible oil.
- The Pharma deck is structurally the roughest: missing the "New Plant Expansion" slide
  the other two have, and its slide titled "Capacitance Based Level Switch: SLC Series"
  near the end actually contains plant-expansion content (a stale/mismatched title), so
  SLC ends up covered twice while the actual expansion slide has no proper heading.
- Growth chart is ~2-3 years stale (ends FY2022-23).
- Minor copy errors: "CMIFR" vs the correct "CIMFR" (two of three decks), "Sanver Road"
  vs "Sanwer Road", "Charted Accountant" vs "Chartered", "BUSSINESS DEVELOPMENT".

## What not to do

- Don't touch the CRM codebase (`app/`, `scripts/`, `migrations/`, `PLAN.md`, git
  history) — unrelated project, different session owns that.
- Don't import the visit-list spreadsheet anywhere or treat it as structured data.
- Don't assume the research scope — the user hasn't defined deliverable/depth/focus
  yet. Ask first.
