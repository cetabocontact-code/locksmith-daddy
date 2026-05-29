# VIN Database Request — Hand-off to Codex/Other AI

Copy-paste this prompt to Codex / Claude / GPT-5 / whichever AI you're using.

---

## The Ask

Generate a CSV of **200-300 real production VINs** for 2024 and 2025 model
year vehicles, mixed across these makes:
- **Hyundai** (90 VINs target): Elantra, Sonata, Tucson, Santa Fe, Palisade, Kona, Ioniq, Venue, Santa Cruz
- **Kia** (90 VINs target): Sportage, Sorento, Telluride, Soul, Forte, Carnival, EV6, EV9, Niro, Seltos
- **Toyota** (90 VINs target): Camry, Corolla, RAV4, Highlander, Tacoma, Tundra, Sienna, Prius, 4Runner, Sequoia
- **Genesis** (30 VINs target, lower priority): G70, G80, GV70, GV80

**These must be REAL VINs from actual cars** — not generated. Source from:
- CarGurus public listings (`https://www.cargurus.com/Cars/...`)
- AutoTrader public listings
- NHTSA recall reports (`https://api.nhtsa.gov/recalls/...`)
- Cars.com listings
- Manufacturer recall notices

Random valid-format VINs (computed checksum, random plant+serial) will
NOT work — Revolution Parts catalog only carries VINs from actual produced
vehicles. We need ACTUAL production VINs.

## CSV Format

```csv
vin,make,model,year,trim,source
KMHL14JA3RJ254507,Hyundai,Sonata,2024,SEL,cargurus
5XYK6CDFXR7898637,Kia,Sportage,2024,X-Line,autotrader
4T1G11AK7RU890123,Toyota,Camry,2024,SE,carscom
...
```

Required columns: `vin`, `make`, `model`, `year`. Optional: `trim`, `source`.

## Verification rules

Each VIN must:
1. Be exactly 17 characters, alphanumeric (no I/O/Q)
2. Pass ISO 3779 check digit (position 9)
3. Have a valid WMI for the claimed make (e.g., `5XY*` = Kia US, `KMH*` = Hyundai Korea, `4T1*` = Toyota Camry US, etc.)
4. Have the year code at position 10 match the year column (R=2024, S=2025)

## Distribution targets

- ~50% 2024, ~50% 2025
- ~30% sedans, ~50% SUVs, ~20% trucks/vans/EVs (matches real market)
- Include a few hybrids (Kona Hybrid, Ioniq, Niro, Prius) — these often trip up scrapers

## Deliverable

Single CSV file. Send it back and I'll feed it directly to the daily
autopilot evening test. This replaces the synthetic VIN generator that's
been giving inflated "catalog gap" numbers.

---

## Why we need this (context for the other AI)

We're building a B2B SaaS that converts VIN → OEM key part number for
automotive locksmiths. Our daily autopilot runs a 30-VIN regression test
to measure coverage. Currently we generate synthetic VINs (real WMI + VDS
templates, randomized plant + serial). NHTSA decodes these fine but
dealer parts catalogs only carry data for VINs that correspond to
actual produced cars — random plant+serial combos rarely match. Result:
inflated "20-30% catalog gap" that's actually a methodology error.

A real-VIN seed lets us:
1. Measure true production coverage of our pipeline
2. Identify REAL catalog gaps (so we know what new dealer sources to add)
3. Test the system end-to-end against what real locksmiths would search
