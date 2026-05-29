# Architecture

## Layers

```
┌────────────────────────────────────────────────────────────────┐
│  Layer 1 — NHTSA VPIC decoder            (vin/decoder.py)      │
│  Free public API → VehicleProfile (year, make, model, trim,    │
│  series, engine, drive, doors, plant, fuel).                   │
│  Sync call, <500ms. Always runs first.                         │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  Layer 2 — Local OEM cache                (future)             │
│  Read from v6 master Excel (OEM_PartNum_Master, 1,184 PNs;     │
│  YMM_FCC_Variants, 13,273 rows). YMM+trim match → candidate    │
│  PNs labeled NOT_DEALER_VERIFIED.                              │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  Layer 3 — Playwright dealer scrape       (scrapers/*.py)      │
│  Drives {make}.oempartsonline.com:                             │
│    a. VIN entry                                                │
│    b. Trim disambiguation when prompted                        │
│    c. Category sweep — Electrical→Keyless Entry Components,    │
│       Anti-Theft System, Electrical Components                 │
│    d. Related-parts rail walk                                  │
│    e. Replacement-chain extraction                             │
│  Outputs DEALER_VERIFIED_BY_VIN parts.                         │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  Layer 4 — Confidence engine              (future)             │
│  Merges L1+L2+L3 → confidence_score (0.0–1.0) +                │
│  confidence_label (HIGH | MEDIUM | LOW).                       │
└────────────────────────────────────────────────────────────────┘
```

## Module map

| Module | Responsibility |
|---|---|
| `lbt1.models` | Pydantic models — `VehicleProfile`, `OemPart`, `LookupResult`, `ResearchStep`, `KeyType` enum + the part-name → KeyType lookup |
| `lbt1.vin.validator` | ISO 3779 VIN format + checksum check |
| `lbt1.vin.decoder` | NHTSA VPIC client (httpx + tenacity retry) |
| `lbt1.scrapers.base` | `OempartsonlineDriver` — Playwright session, stealth, category sweep, related-parts walk, dedup. Make-agnostic. |
| `lbt1.scrapers.kia` | `KiaOempartsDriver` — base URL + Kia-specific overrides |
| `lbt1.cli` | Typer CLI: `validate`, `decode`, `lookup` |

## Data flow for one lookup

```
CLI: lbt1 lookup 5XYK6CDF8TG390982
  │
  ├─→ vin.validator.validate()              (rejects malformed VINs)
  │
  ├─→ vin.decoder.decode()                  (NHTSA → VehicleProfile)
  │
  ├─→ scrapers.kia.KiaOempartsDriver
  │     ├─→ session() opens Chromium + stealth + storage state
  │     ├─→ _enter_vin()
  │     ├─→ _resolve_trim()                 (matches NHTSA series)
  │     ├─→ _sweep_categories()             (4 paths, dedupe by PN)
  │     ├─→ _walk_related_parts()           (supersession chain)
  │     └─→ session closes, storage state persisted
  │
  └─→ LookupResult assembled and printed
```

## Why Playwright instead of `requests` + BeautifulSoup

`oempartsonline.com` returns **403 Forbidden** to plain HTTP requests (verified directly via WebFetch UA). They have anti-bot (likely Cloudflare or Akamai) that fingerprints non-browser clients. The only viable path for unauthenticated scraping is a real browser with stealth patches.

The driver uses `playwright-stealth` to hide the `navigator.webdriver` flag, fix User-Agent Client Hints headers, and patch other CDP-detectable signals. We also persist a `storage_state.json` so repeat visits look like a returning user (cookies + localStorage).

## Stealth and detection

Risk: if the dealer ramps up bot protection (e.g., Cloudflare Turnstile / Bot Fight Mode), even stealth Playwright can be blocked. Mitigation tiers:

1. **Stealth Playwright** — current default, free, may suffice.
2. **Residential proxies + stealth** — paid (~$10–30/mo, e.g., Bright Data, Oxylabs). Rotates IP to avoid datacenter blocks.
3. **Browserbase / ScrapingBee** — managed browser-as-a-service with built-in stealth (~$0.05–0.15 per VIN lookup).
4. **User-credentialed dealer session** — the locksmith provides their own Kia GDS / Hyundai HMA login; the tool drives that authenticated session. Highest accuracy, zero ToS risk.

The `OempartsonlineDriver` is designed so we can swap stealth tiers without rewriting the navigation logic.

## VIN privacy

VINs are stored plaintext with a 60-day auto-purge (env var `VIN_RETENTION_DAYS`). Rationale: lets us re-run research when a locksmith reports a bug. The auto-purge job runs daily and deletes rows where `created_at < now() - retention`.

## Deployment topology (planned)

| Component | Host | Tier |
|---|---|---|
| Frontend (Next.js) | Vercel | Free |
| Backend API (FastAPI) | Fly.io | $5/mo |
| Worker (Playwright) | Fly.io (separate machine) | $10–20/mo |
| Database (Postgres) | Neon | Free |
| Email (magic links) | Resend | Free tier |

## Testing

- `tests/test_vin_validator.py` — unit tests for ISO 3779 + the 23 training VINs.
- `tests/test_vin_decoder.py` — integration against the live VPIC API for 3 representative VINs.
- `tests/test_kia_scraper.py` — *to be added* — regression against the full 23-VIN training set comparing extracted PNs to the CSV's expected PNs.

## Future work

- `lbt1.cache` — read v6 Excel sheets into a Postgres cache table for L2.
- `lbt1.confidence` — the scoring engine.
- `lbt1.scrapers.hyundai` — Hyundai parity once Kia is verified.
- FastAPI app, Next.js frontend, magic-link auth, deployment.
