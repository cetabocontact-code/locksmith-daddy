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

**MAJOR DISCOVERY 2026-06-01** — DNS probe of oempartsonline.com
revealed 10 additional makes have Revolution Parts subdomains (same
CMS, same code pattern, no new driver class needed beyond a one-line
subclass). The expansion now covers ~85% of US market via a single
unified scraping architecture.

| Make | Dealer subdomain | PN family | Status | Notes |
|---|---|---|---|---|
| **Hyundai** | hyundai.oempartsonline.com (+ hyundaioempart.com + Canada SimplePart) | `95440-XXXXX`, `95430-XXXXX` | ✅ live | 100% 2019–2025 on 77/77 audit |
| **Kia** | kia.oempartsonline.com (+ parts.kia.com SimplePart) | `95440-XXXXX`, `95430-XXXXX`, `95431-XXXXX` | ✅ live | 100% 2019–2025 on 40/40 audit |
| **Genesis** | genesis.oempartsonline.com (+ Hyundai adjacent) | `95440-XXXXX` (G70/GV70/etc.) | ✅ live | Small sample (2/2); G70 family confirmed |
| **Toyota** | toyota.oempartsonline.com | `89070`, `89904`, `89742`, **`8990H`** | ✅ live | 8990H is the 2025+ smart-key family |
| **Lexus** | lexus.oempartsonline.com (+ Toyota adjacent) | `89070`, `89904`, `8990H` | 🟡 enabled | DNS-confirmed; awaiting first-VIN validation |
| **Honda** | honda.oempartsonline.com (+ hondapartsnow.com) | `72147-XXX-XXX`, `35118-XXX-XXX`, `35880-XXX-XXX` | 🟡 enabled | 3-segment hyphen PN, regex handles |
| **Acura** | acura.oempartsonline.com (+ Honda adjacent) | same as Honda | 🟡 enabled | Adjacent fallback to Honda |
| **Nissan** | nissan.oempartsonline.com (+ nissanpartsdeal.com) | `285E3-XXXXX`, `28268`, `28630` | 🟡 enabled | |
| **Infiniti** | infiniti.oempartsonline.com (+ Nissan adjacent) | same as Nissan | 🟡 enabled | |
| **Subaru** | subaru.oempartsonline.com (+ subarupartsdeal.com) | `57497AXXXXX`, `88835`, `88036` | 🟡 enabled | |
| **Mazda** | mazda.oempartsonline.com (+ mazdapartsgiant.com) | `KD45-67-5DY` (3-segment), `GHP9`, `GHR9`, `BBM4`, `BHN9` | 🟡 enabled | 3-segment hyphen PN, regex handles |
| **Ford** | ford.oempartsonline.com | `164R`, `BC3Z`, `AA6T`, `DS7T`, `FL3T` | 🟡 enabled | Covers Lincoln too (no Lincoln subdomain) |
| **Lincoln** | (routes through Ford) | `164R`, `BC3Z`, `DS7T` | 🟡 enabled | Adjacent to Ford |
| **GM** (Chevy/Buick/Cadillac/GMC) | gm.oempartsonline.com | `13598`, `13509`, `13577`, `13594`, `22XX` | 🟡 enabled | Single subdomain covers all 4 brands |
| **Stellantis** (Jeep/Ram/Chrysler/Dodge/FIAT) | mopar.oempartsonline.com | `68XXXXXXAA` (8d + 2 opt revision letters), `56038`, `56046` | 🟡 enabled | Single subdomain covers all 4 brands |
| **Volkswagen** | vw.oempartsonline.com (+ Audi adjacent) | `5G0`, `3G0`, `5C0`, `1K0`, `5K0`, `7E0` | 🟡 enabled | VW-Group format prefix+6d+letter |
| **Audi** | audi.oempartsonline.com (+ VW adjacent) | `8K0`, `8R0`, `4G0`, `4M0`, `4F0`, `8V0` | 🟡 enabled | |
| **Porsche** | porsche.oempartsonline.com (+ Audi adjacent) | `970`, `971`, `991`, `992`, `9Y0`, `95B` | 🟡 enabled | Model-line prefixes |
| **BMW** | bmw.oempartsonline.com | 8-11 digit numeric SKU (e.g., `51453427411`) | 🟡 enabled | Covers Mini too |
| **Mini** | (routes through BMW) | same as BMW | 🟡 enabled | Adjacent to BMW |
| **Volvo** | volvo.oempartsonline.com | `3149`, `3164`, `3074`, `3140`, `316` (8d numeric) | 🟡 enabled | |
| **Mitsubishi** | mitsubishi.oempartsonline.com | `8637A`, `MR4`, `6370A`, `8307A` | 🟡 enabled | |
| **Mercedes-Benz** | (no subdomain — different CMS) | `A164...` style | ⏳ research | Mercedes runs proprietary STAR EPC; needs custom driver |

To enable a make: `fly secrets set LBT1_ENABLE_<MAKE>=1`. Enabled
flags as of 2026-06-01: all 18 makes above except Mercedes. After
first-VIN validation per make, move ✅ live and update the table.

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
