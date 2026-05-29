# Kia / Hyundai / Genesis OEM Parts Supplier Ecosystem

Research compiled 2026-05-28 against live probes + commercial dealer registries.
This drives our fallback-chain prioritization and tells us where the gaps are.

The catalogs cluster into **three platforms** (CMS), each shared by many domains.
A coverage gap on one platform usually affects every domain on that platform —
they pull from the same upstream OEM data feed.

---

## Platform 1: Revolution Parts (third-party dealer aggregator)

The largest dealer-network CMS in North America for OEM parts.

**Tech stack**: marketplace-style React/SSR site, ASP `.aspx` pages with VIN search
on `/search?search_str={VIN}` → resolves to `/v-{year}-{make}-{model}--{trim}--{engine}`.

**Detection**: HTML contains `.marketplace-info-col` cards + `revolutionparts` in JS.

**Hyundai domains** (all share upstream feed):
- `hyundai.oempartsonline.com` ← **our primary** (wired in pipeline)
- `hyundaioempart.com` ← **our secondary** (wired in pipeline)
- `hyundaipartsdeal.com`
- `hyundaipartsnow.com`
- `hyundaiparts.com`
- `hmaparts.com`
- `jenkinshyundaiparts.com`
- `kingstonhyundaiparts.com`
- `hyundaioemnow.com`

**Kia domains**:
- `kia.oempartsonline.com` ← **our primary** (wired in pipeline)
- `kiapartsdirect.ca` (Canada, Revolution Parts CMS)
- `kiapartsnow.com`
- `kiapartshouse.com`
- `kiagenuineparts.com`
- `mckiaparts.com`

**Genesis**:
- `genesis.oempartsonline.com` ← **our primary** (wired in pipeline)
- `genesisoemparts.com`
- `genesispartshouse.com`

**Strengths**: Best coverage for 2014–2024 model years. Fast resolves. Categorizes
keys clearly under `electrical--keyless-entry-components` / `electrical--anti-theft-system`.

**Weaknesses**: All domains share one feed. When the upstream feed is missing
data for a brand-new model year or trim (e.g. 2026 Elantra SEL Sport), EVERY
Revolution Parts dealer returns 0 PNs — adding another Revolution Parts dealer
buys nothing.

**Verified gap**: 2026 Elantra electrical category 410s on all RP dealers.

---

## Platform 2: SimplePart (manufacturer-direct)

Official platform that Hyundai, Kia, and Genesis use directly for their
"Genuine Parts" sites. Different upstream feed from Revolution Parts.

**Tech stack**: ASP.NET, `spApp` JS namespace, ASMX endpoints under `/wm.aspx/`.
VIN search via `POST /wm.aspx/CreateVinLinks` with JSON `{VinNumber, AbsolutePath,
QueryString}` → returns `{"d": "[{vehicleDescription, vechicleHref}]"}`.

**Detection**: HTML contains `window.spApp` + `/wm.aspx/CreateVinLinks` reference.

**Hyundai (official)**:
- `parts.hyundaicanada.com` ← **wired as Hyundai tier-3 fallback**
- `parts.hyundaiusa.com` (returns 422 via ScrapFly — tighter anti-bot, not yet wired)

**Kia (official)**:
- `parts.kia.com` ← **wired as Kia tier-2 fallback** (US)
- `parts.kia.ca` (Canada, 422'd via ScrapFly — not wired)

**Genesis (official)**:
- `parts.genesis.com` (422'd via ScrapFly — not wired yet, but same platform)

**Catalog structure**: vehicle pages at `/{Make}_{Year}_{Model}-{Engine-Trim}.html`,
schematic groups at `/a/{vehicle}/_{group_id}/{NAME}/{schematic_id}`, parts at
`/p/{vehicle}/{Name}/{id}/{PN}.html`.

**Key parts hide under TWO schematic groups** (discovered 2026-05-28):
- `Body-and-Trim > KEY--CYLINDER-SET` — mechanical keys, blanks, transponder
  chip, immobilizer antenna coil
- `Electric > RELAY--MODULE` — FOB-SMART KEY (95440-*), antenna-smartkey, IBU
  module, transmitter battery

**Strengths**: Authoritative OEM data direct from the manufacturer. Different
catalog feed = catches some Revolution Parts gaps. Verified working on
2017 Hyundai Elantra (18 PNs) and 2022 Kia Telluride (5 PNs).

**Weaknesses**: Doesn't have 2026 trim data either — manufacturer hasn't
published it yet. Search-only PN exposure (no aftermarket-style fitment chooser).
parts.hyundaiusa.com + parts.kia.ca + parts.genesis.com all 422 via ScrapFly
ASP — likely need direct httpx with rotated user agents.

---

## Platform 3: Custom dealer sites (long tail)

Individual dealers running their own catalog software, often via licensing
arrangements with Hyundai/Kia. Examples:

- `parts.hyundaiusa.com` (Hyundai USA official — custom, not SimplePart) — anti-bot blocks ScrapFly
- Various dealer-network sites that don't fit Revolution Parts or SimplePart

These are inconsistent — different CMS per dealer, varying coverage. We
don't currently target these. Worth investigating only when the two main
platforms exhaust.

---

## Mexico / regional catalogs

**Status**: Not viable for our use case (2026-05-28).

- `hyundai.com.mx`, `kia.com.mx` — consumer brand sites only, no parts API
- `refacciones.hyundai.com.mx`, `refacciones.kia.com.mx` — 422 via ScrapFly,
  likely behind regional anti-bot or geo-locked

If we ever need Spanish-speaking market coverage, we'd negotiate direct API
access with Hyundai México / Kia México rather than scrape.

---

## Current pipeline fallback chain (live in production)

```
Kia VIN:
  1. KiaOempartsDriver       (kia.oempartsonline.com   Revolution Parts)
  2. KiaUsOfficialDriver     (parts.kia.com            SimplePart)

Hyundai VIN:
  1. HyundaiOempartsDriver   (hyundai.oempartsonline.com  Revolution Parts)
  2. HyundaiOemPartDriver    (hyundaioempart.com           Revolution Parts)
  3. HyundaiCanadaDriver     (parts.hyundaicanada.com      SimplePart)

Genesis VIN:
  1. GenesisOempartsDriver   (genesis.oempartsonline.com  Revolution Parts)
```

Strict OEM-verified-only policy throughout: NO year-fallback, NO trim-fallback,
NO close-match guessing. Each driver returns only parts the dealer's own
catalog explicitly maps to that exact VIN's year + trim + engine.

---

## Potential next additions (ranked by value)

1. **`parts.genesis.com`** as Genesis tier-2 fallback. Same SimplePart platform,
   needs unblocking on ScrapFly (try direct httpx + UA rotation instead of ASP).
   Adds Genesis coverage parity with Hyundai/Kia tier-2.

2. **`parts.hyundaiusa.com`** as Hyundai tier-4 fallback. Hyundai's OFFICIAL US
   site, separate platform from SimplePart. Currently blocks ScrapFly ASP — needs
   investigation. If unblockable, gives us best-of-class Hyundai US coverage.

3. **A few more long-tail Revolution Parts dealers** (e.g. hyundaipartsdeal.com).
   Low value because shared feed — but +1-2 dealers buys insurance against
   one specific dealer being down. ~$0.01/lookup cost each, on misses only.

4. **Hyundai/Kia recall API** as a cross-verification source for VIN range
   validity. Not for fitment (recalls don't list key fobs as affected parts),
   but useful for confidence scoring + VIN validation.

---

## What WE DON'T do (and why)

- **Aftermarket key suppliers** (RockAuto, AutoZone, Strattec, Ilco, etc.) —
  These have aftermarket equivalents, not OEM PNs. Locksmiths need the OEM
  number for dealer warranty + Smartra programming. We never return aftermarket
  PNs as "verified".

- **Manual VIN-pattern seed table** — per user directive 2026-05-28: the tool
  MUST always do the live search. Manual seeds would be untrustworthy at scale
  and conflict with VIN-verified guarantees.

- **Year-fallback (2025 PN as proxy for 2026)** — proven WRONG by user testing:
  the 2026 Elantra rejects the 2025 95440-AA500 in dealer's own fitment check.
  Wrong PN > no PN for a locksmith.
