# Locksmith Brain — Tool 1: VIN-Verified OEM Key Finder

For certified locksmiths only. Given a VIN, returns the OEM smart key / transmitter / remote-head-key part number — with dealer verification when possible, or a clearly labeled NOT_DEALER_VERIFIED replacement when it isn't.

## MVP scope

**Kia and Hyundai only.** Other makes deferred until the workflow is proven against these two.

## Architecture (three layers + a scorer)

```
1. NHTSA VPIC decode    → VehicleProfile (Year, Make, Model, Trim, Engine, …)
2. Local OEM cache       → Candidate PNs from your v6 master Excel
3. Playwright dealer     → Live navigation of {make}.oempartsonline.com:
   live scrape              - VIN entry
                            - Trim disambiguation when prompted
                            - 4-path category sweep
                            - Replacement-chain detection
4. Confidence engine     → Merge L1/L2/L3, score 0.0–1.0, label HIGH/MED/LOW
```

A lookup returns either `DEALER_VERIFIED_BY_VIN` (Layer 3 confirmed the VIN) or `NOT_DEALER_VERIFIED_BY_VIN` (Layer 3 unavailable, returning Layer 1/2 candidates labeled clearly).

## Repo layout

```
locksmith_brain_tool1/
├── src/lbt1/
│   ├── models.py           # Pydantic models for the whole pipeline
│   ├── vin/
│   │   ├── validator.py    # 17-char + no IOQ + ISO 3779 checksum
│   │   └── decoder.py      # NHTSA VPIC DecodeVinValuesExtended client
│   ├── scrapers/
│   │   ├── base.py         # Abstract OempartsonlineDriver
│   │   └── kia.py          # Kia Revolution-Parts dealer navigation
│   └── cli.py              # Standalone runner: python -m lbt1.cli vin <VIN>
├── tests/                  # pytest — regression tests against the 23 training VINs
├── data/
│   └── kia_vin_training.csv  # 23 Kia VINs with expected PNs + workflow notes
└── docs/
    ├── architecture.md
    ├── csv_workflow_notes.md
    └── audit_existing_apps.md
```

## Setup

```powershell
cd C:\Users\rawes\Downloads\locksmith_brain_tool1
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
playwright install chromium
```

## Run a single VIN lookup

```powershell
# NHTSA decode only (no scraping, fast)
python -m lbt1.cli decode 5XYK6CDF8TG390982

# Full pipeline (NHTSA + Playwright Kia scrape)
python -m lbt1.cli lookup 5XYK6CDF8TG390982
```

## Run the test suite

```powershell
pytest tests/ -v
```

## Status

This is a first-session scaffold. What works end-to-end today:

- [x] VIN format + ISO 3779 checksum validation
- [x] NHTSA VPIC live decode → VehicleProfile
- [x] Pydantic models for the full LookupResult schema
- [x] Kia Playwright scraper (driver + parsers) — installation required to run
- [ ] Hyundai scraper (next session)
- [ ] FastAPI backend (next session)
- [ ] Next.js frontend (next session)
- [ ] Magic-link auth (next session)
- [ ] Fly.io deployment (next session)

## The 23 training VINs

`data/kia_vin_training.csv` contains 23 Kia VINs with the manual workflow and expected PNs. These are the regression tests for the scraper.

The workflow that the scraper reproduces:
1. Go to kia.oempartsonline.com → enter VIN.
2. If the site asks to disambiguate trim/engine, pick the trim matching NHTSA's `Series` field.
3. Sweep these category paths and capture every PN appearing under the recognized key-related part names:
   - Electrical → Keyless Entry Components *(primary)*
   - Electrical → Anti-Theft System *(older models)*
   - Electrical → Electrical Components *(newer Telluride/Carnival)*
   - "Related parts" rail on each part page *(supersession chain)*
4. Recognized part name labels: `fob smart key`, `smart key`, `transmitter`, `transmitter/tranciever`, `keyless entry transmitter`, `remote control`, `keyless lock pad`.
5. Return ALL captured PNs as variants — do not pick a single winner.
