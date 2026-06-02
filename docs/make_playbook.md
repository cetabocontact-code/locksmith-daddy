# Per-Make Expansion Playbook

Strategic framework for adding any automotive make to Locksmith Daddy
without breaking what works on Hyundai / Kia / Genesis / Toyota.

Last revised: 2026-06-01 — after the verified-100%-on-2019-2025 launch.

---

## The 5-question framework

Before writing a line of code for a new make, answer these in writing:

1. **Dealer surface** — which dealer CMS carries this make's smart-key
   catalog? (Revolution Parts subdomain? SimplePart? Manufacturer-direct
   like fordparts.com? PartsDeal/PartsNow/PartsGiant family? A unique
   proprietary CMS like BMW PuMA?)
2. **PN family** — what is the OEM part-number prefix pattern for smart
   keys / transmitters on this make? (e.g., Hyundai 95440-XXXXX, Toyota
   89070/89904/8990H, Honda 35118/72147, Ford 164-R...) The DDG fallback
   needs this list to search effectively.
3. **PN extraction shape** — does the PN format fit our existing regex
   (5 digits + 4-8 alphanumerics) or does it need a new shape? (Honda's
   3-segment hyphen format, Ford's "164-R" prefix, etc.)
4. **Title attestation phrase** — what exact words does this dealer's
   product page title use? Revolution Parts uses "{year} {make} {model}
   {part} {PN}". A different CMS may say "{PN} - {make}/{model} {year}".
   Our strict canonical fitment check needs the right pattern.
5. **Catalog gaps** — what model years lag? What trims aren't published?
   (e.g., 2026 Toyota luxury still on 2021-2025 titles.) Set expectations
   honestly on the sign-in page.

If you can't answer 1-4 with confidence before coding, **do not enable
the make for live users**. Wire it as opt-in experimental, run 1 VIN
through it to confirm, then flip it on.

---

## What we know that transfers across all makes

These were proven on Hyundai/Kia/Genesis/Toyota and apply universally:

- **Strict canonical fitment check is the trust anchor.** Title or
  "perfectly fit your YYYY[-YYYY] Make Model vehicle" body sentence —
  nothing else. (Implemented in `search_fallback.py` + `known_pn_probe.py`.)
- **Empty-result cache poisoning is the #1 silent failure mode.** Do
  NOT cache empty DDG result sets. Already fixed globally; same fix
  applies to any new make.
- **Concurrency=1 during the first VIN probe** to avoid ScrapFly 429
  cascades. Scale up only after the make is verified.
- **Pipeline always runs live — never short-circuit with memorized
  PNs.** YMM lookups are commodity; VIN-verified live is our moat.
  The `manual_pn_overrides` table is audit-only; pipeline doesn't read it.
- **Dealer-catalog lag is the lower bound on 2026 coverage.** Honest
  "not yet attested" instead of guessing keeps locksmith trust.

---

## The 4 dealer-CMS families (with their working drivers in our code)

### 1. Revolution Parts CMS — `oempartsonline.com` family
- Selectors: `.marketplace-info-col`, `.product-title`, `.product-partnum`
- Title format: `"{year(s)} {Make} {Model} {Part name} {PN} | OEM Parts Online"`
- Canonical fitment: `"...will perfectly fit your {year(s)} {Make} {Model} vehicle..."`
- Base driver: `lbt1/scrapers/base.py: OempartsonlineDriver`
- Subdomains we've confirmed working:
  - `hyundai.oempartsonline.com`, `kia.oempartsonline.com`
  - `genesis.oempartsonline.com`, `toyota.oempartsonline.com`
- To add a new Revolution-Parts make: just subclass `OempartsonlineDriver`
  with a new `base_url`. Zero new code beyond the URL.

### 2. SimplePart CMS — manufacturer-direct
- Selectors: ASMX endpoint `/wm.aspx/CreateVinLinks`, namespaced `spApp.*`
- Used by: `parts.hyundaicanada.com`, `parts.kia.com`
- Base driver: `lbt1/scrapers/simplepart.py: SimplepartDriver`
- Useful as fallback when Revolution Parts doesn't carry a trim.

### 3. PartsDeal / PartsNow / PartsGiant family — JS-rendered, multi-tenant
- One operator runs many domains. Site identity is in a `Site` header
  / cookie that we never fully cracked for Toyota (see
  `docs/toyotapartsdeal_api_findings.md`).
- High future value: cracking this once unlocks Honda + Nissan + Ford
  + GM + Chrysler + Subaru in one shot.
- **Deferred:** needs a JS-rendered ScrapFly probe (~$0.50 first try).

### 4. Per-make proprietary CMSs
- BMW, Mercedes, Volvo, Porsche, Audi run their own dealer catalogs.
- Often require dealer login or paid EPC subscriptions.
- One-off driver per make. Avoid until the four big families above are exhausted.

---

## Per-make readiness table

Status = `live` (serving real lookups), `staged` (driver wired, opt-in),
`research` (5-question framework partially done), or `none` (no work yet).

| Make | Dealer CMS | PN family | Status | Notes |
|---|---|---|---|---|
| **Hyundai** | Revolution Parts | `95440-XXXXX`, `95430-XXXXX` | ✅ live | 100% 2019–2025 on 77/77 audit |
| **Kia** | Revolution Parts | `95440-XXXXX`, `95430-XXXXX`, `95431-XXXXX` | ✅ live | 100% 2019–2025 on 40/40 audit |
| **Genesis** | Revolution Parts | `95440-XXXXX` (G70, GV70 etc.) | ✅ live | Small sample (2/2); G70 family confirmed |
| **Toyota** | Revolution Parts | `89070`, `89904`, `89742`, **`8990H`** | ✅ live | 8990H is the 2025+ smart-key family — critical to include |
| **Lexus** | Revolution Parts → Toyota dealer fallback | `89070`, `89904`, `8990H` | 🔬 staged | Same backend as Toyota; expect similar coverage profile |
| **Honda** | Revolution Parts (TBD) → hondapartsnow.com (PartsDeal) | `35118-XXX-XXX`, `72147-XXX-XXX` | 🔬 staged | Honda uses 3-segment hyphen PN format — regex update required |
| **Acura** | Revolution Parts (TBD) → acurapartsnow.com (PartsDeal) | `35118-XXX-XXX`, `72147-XXX-XXX` | 🔬 staged | Same family as Honda |
| **Nissan** | Revolution Parts (TBD) → parts.nissanusa.com | `285E3-XXXXX` | 🔬 staged | Strong consistent prefix |
| **Infiniti** | parts.infinitiusa.com → nissanpartsdeal.com | `285E3-XXXXX` | 🔬 staged | Same family as Nissan |
| **Ford** | fordparts.com → fordpartsgiant.com | `164-RXXXX` (Rotunda), `5929XXX` (Strattec) | 🔬 staged | "164-R" is the dealer-facing PN, dual numbering required |
| **Lincoln** | Ford-group | `164-RXXXX` | 🔬 staged | Same family as Ford |
| **GM** (Chevy/Buick/Cadillac/GMC) | gmpartsgiant.com → parts-catalog.acdelco.com | `13598XXX`, `25...`, `134...` (varies by brand) | 🔬 staged | Cross-brand PNs vary; brand-specific drivers may be needed |
| **Stellantis** (Chrysler/Dodge/Jeep/Ram) | moparpartsgiant.com → Mopar OEM | `68XXXAAA` (Mopar PN format) | 🔬 staged | Same backend; 4 brands one driver |
| **Subaru** | parts.subaru.com → subarupartsdeal.com | `57497AXXXXX` | 🔬 staged | Subaru-specific format |
| **Mazda** | mazda-parts-dealer.com | `KD45-67-5DY` (3-segment hyphen) | 🔬 staged | Honda-like multi-segment PN — needs regex update |
| **Mitsubishi** | mitsubishiparts.com | `8637AXXX`, `MR4...` | 🔬 staged | Smaller volume |
| **Volkswagen** | eeuroparts.com → VW dealer-specific | `5G0959752M`-style (no consistent prefix) | 🔬 staged | VW format is awkward — no clean prefix |
| **Audi** | eeuroparts.com (shares with VW) | similar to VW | 🔬 staged | Cross-brand with VW |
| **BMW** | Proprietary BMW PuMA (paid) | Hex SKU | ⏳ research | BMW often requires PuMA dealer login |
| **Mercedes-Benz** | Proprietary EPC (WIS/STAR) | `A164...`-style | ⏳ research | Mercedes requires STAR dealer access |
| **Volvo** | volvopartsdirect.com | `316...`-style | ⏳ research | |
| **Porsche** | porschepartsexpress.com | `9P1...`-style | ⏳ research | Same family as Audi sometimes |

---

## Add-a-make checklist (use this each time)

1. Fill in the 5-question framework above for the make.
2. Add the driver class in `lbt1/scrapers/` (subclass `OempartsonlineDriver`
   if it's a Revolution Parts subdomain — just one line, `base_url = "..."`).
3. Add the PN-prefix list to `_MAKE_CONFIG` in `lbt1/scrapers/search_fallback.py`.
4. If the PN shape is unusual (Honda 3-segment, Ford "164-R", etc.), update
   the regex in `_extract_pn()` in `search_fallback.py`.
5. Add `__init__.py` import if needed (we don't need it currently).
6. Wire into `_drivers_for_make()` in `lbt1/pipeline.py` — but keep the
   make BEHIND an env-var gate (`LBT1_ENABLE_<MAKE>=1`) until validated.
7. Run **one** VIN through the new make at concurrency=1 (cost: ~84 ScrapFly
   credits, plus DDG fallback if primary misses, plus KnownPnProbe if both
   miss → total worst case ~300 credits, $0.05).
8. Inspect the result, the diagnostic log, and verify the strict fitment
   check accepted/rejected as expected.
9. Run a 5–10 VIN audit. If 80%+ verify cleanly, flip the env-var gate ON
   and ship.
10. Update this doc's per-make table.

---

## What we currently spend per lookup (so you can budget)

Per VIN lookup at the strict-pipeline averages we measured:
- NHTSA decode: free
- Primary Revolution Parts driver hit (happy path): ~84 ScrapFly credits ≈ $0.01–0.02
- Secondary driver: ~84 credits if primary misses
- DDG fallback: ~84 credits + 1–3 candidate fetches if it fires
- KnownPnProbe: ~84 credits if DDG misses
- Worst case (everything fires + retries): ~500 credits ≈ $0.07

At $7.99 per paid unlock, **even the worst-case ScrapFly bill is ~1% of
revenue**. Adding makes costs almost nothing in cents; the cost is in
quality-assurance time on the first 10 VINs.

---

## What to NOT do (lessons learned the hard way)

1. **Don't cache empty DDG results.** Single line of code, but if you
   skip it, every new make eventually self-poisons via ScrapFly 429 cascades.
2. **Don't short-circuit with `manual_pn_overrides`.** YMM lookups are
   commodity; VIN-verified live is the moat.
3. **Don't enable Klarna/Afterpay/ACH at Stripe Checkout** without
   adding the matching `checkout.session.async_payment_succeeded` handler.
   We're card-only on V1.
4. **Don't run the entire test corpus at concurrency=12** — ScrapFly
   throttles, results get unreliable. concurrency=2 is the sweet spot.
5. **Don't title the sign-in page with marketing copy.** Founder kept that
   page minimal-form-only for a reason; resist the urge to add coverage
   stats back.
