# Audit — three existing prototypes

Three prototypes were already deployed on Render. They don't work. Here's what they tried, what was wrong, and what we're doing differently.

## App 1 — `wassup-bl8d.onrender.com`

**Title:** *VIN Key Fob Agent*  
**Tagline:** *VIN-verified OEM key fob and transmitter lookup*

What it exposes:
- Email gate (presumably to allow-list users)
- VIN input with "Enter a VIN to start a live lookup"
- Live status: *"Searching live VIN decode, OEM catalogs, and key transmitter pages. This may take a minute."*
- "Last Searches" table with columns: Email, VIN, Part shown, Correct part if known, What happened?
- "Report Error" form with Save report / Copy report
- Server-side persistence via Render `DATA_DIR`

Diagnosis:
- The status string suggests it attempts live OEM scraping, which is the right idea, but the Render free tier 503s on cold start. We hit that on first fetch.
- The "Correct part if known" + "What happened?" columns in the search history reveal that the team already knew results were unreliable enough to need manual annotation.

## App 2 — `hyundai-ofgw.onrender.com`

**Title:** *OEM Key Finder 8989*  
**Tagline:** *VIN-only OEM key lookup*

What it exposes:
- VIN input with "Enter VIN to detect make" (0/17 char counter)
- "Make override" dropdown defaulting to "Auto detect"
- **"Cache only" checkbox** — the smoking gun
- "Last 50 Searches" table with a `Confidence` column

Diagnosis:
- The "Cache only" checkbox means live scraping fails often enough that the team built a fallback to stale results.
- The "Make override" suggests VIN decode sometimes can't resolve the make reliably — but for Hyundai/Kia VINs, NHTSA VPIC is highly reliable (we confirmed this on three sample VINs). The override is likely covering up a deeper decode bug.
- Confidence is shown but the source of the score is opaque.

## App 3 — `oem-key-finder.onrender.com`

**Title:** *OEM Key Part Finder*  
**Description:** *Lookup OEM key, remote, and transponder part numbers across Toyota, Lexus, Scion, Nissan, Infiniti, Honda, Acura, GM, Ford, Mopar, Hyundai, Kia, Subaru, Mazda, Mitsubishi, Volkswagen, BMW, and MINI.*

What it exposes:
- VIN input (0/17 counter)
- Make override → "Auto detect"
- "Look Up Keys" button
- "Recent Searches" table (Time, VIN, Make, Status, Site, Parts)
- Results table (Part Number, Description, View Link, Copy action)
- "Copy All Part Numbers" / "Export CSV" buttons
- Status text: *"Searching OEM car key parts..."* with a `Cached` indicator

Diagnosis:
- **Scope blew up.** 18 makes is too many to do well in v1. Each OEM dealer site has different navigation, different category labels, different anti-bot.
- Same `Cached` indicator as app 2 — same fallback pattern, same underlying failure.

## Common root causes

1. **`oempartsonline.com` returns 403 Forbidden to non-browser HTTP fetches.** Verified directly: `WebFetch https://kia.oempartsonline.com/` → 403. The site has Cloudflare/Akamai fingerprinting. Plain `requests`/`fetch`/`axios` cannot get past it.
2. **Render free tier sleeps after inactivity.** All three apps returned 503 on the first fetch attempt. For a locksmith on a service call, that's unusable.
3. **YMM-only matching with a Make-override escape hatch.** Suggests the architecture is: NHTSA decode → YMM tuple → static table lookup. That doesn't reproduce the human workflow, which is *trim-aware + category-sweep + related-parts walk*.
4. **No replacement-chain logic.** The CSV training data shows 1–6 PNs per VIN due to button-count variants + supersession. A "one part wins" UI cannot represent that.
5. **No category sweep.** The CSV proves that *Electrical → Keyless Entry Components* alone misses parts on Telluride/Carnival (need *Electrical Components*) and on older Forte/Optima (need *Anti-Theft System*). A scraper that stops at the first category fails on those models.

## What we're doing differently

| Failure mode | Our mitigation |
|---|---|
| 403 anti-bot | Real Chromium via Playwright + `playwright-stealth` + persisted storage state |
| 503 cold sleeps | Paid Fly.io tier ($10–25/mo), no free-tier hosting for the worker |
| YMM-only | Use NHTSA `Series` field for trim disambiguation; the scraper picks the matching trim when prompted |
| One-part UI | Return all PNs as variants; `primary_result` is the most-likely match, `alternative_matches` is the rest |
| Single category | Sweep four paths (Keyless Entry / Anti-Theft / Electrical / Related Parts) per the CSV |
| No supersession | Walk the Related-parts rail on every captured part page |
| Make sprawl | MVP locked to Kia + Hyundai; expand only after Kia hits ≥90% PN recall on the 23-VIN training set |

## What we are NOT doing

- We are not using a cache-only fallback. If Layer 3 fails, the result is honestly labeled `NOT_DEALER_VERIFIED_BY_VIN` with the confidence label set to `LOW`.
- We are not displaying a single confidence number without explaining how it was derived. The confidence engine's rubric is documented and the inputs are visible in `research_steps`.
