# Deploy log — Locksmith Daddy

Each row is one production deploy with its small benefit line. The line
that appears on the sign-in page comes from the most recent entry's
`benefit` field.

## 2026-05-30 (today)

**Benefit (shown on sign-in page):** Toyota support shipped + search-fallback driver added. Sonata/Palisade 2025 + Hyundai/Kia mainstream lineups now verified at 100%.

What changed under the hood:

- **ToyotaOempartsDriver** wired into the pipeline — Toyota VINs route to `toyota.oempartsonline.com` with year-aware trim disambiguation.
- **DuckDuckGoSearchFallbackDriver** added as the last fallback for every make. When normal category sweeps miss a fob, a structured search of the dealer's own indexed product pages finds it. Persistent cache, ScrapFly-proxy backup for rate-limit resilience, adjacent-dealer search for Genesis/Lexus.
- **Bug #1 fix (year-segment required)**: dealer search navigation stubs like `/v-hyundai-sonata` are rejected — only `/v-{YYYY}-` URLs are accepted as real vehicle pages. Cuts ~750 ScrapFly credits per failed edge case.
- **Bug #2 fix (placeholder retry)**: when the dealer returns `/v?vin=...` placeholder with no real candidates, refetch after 3s. ~30% recovery rate.
- **Parallel category sweeps within each driver** — 3 category fetches now run concurrently. Latency drop: p50 from 356s → ~80s.
- **Defensive fix on empty `fuel_type`** — IndexError on certain motorcycles/EVs that NHTSA returns without fuel info.
- **Sign-in page**: now shows what the tool does, measured coverage per make, and the latest deploy benefit.

Measured coverage on 2024–2026 real production VINs (CarGurus-sourced):

| Make | Verified | Sample |
|---|---|---|
| Hyundai | 100% | 30 / 30 |
| Kia | 100% | 44 / 44 |
| Toyota | 73% | 22 / 30 |
| Lexus | — | in queue |

---

## Earlier deploys (Fly v1 → v3)

- **v3 (2026-05-28)** — Reverted false year-fallback for Kia/Hyundai/Genesis. Strict OEM-verified-only policy: dealer must confirm the PN for this exact VIN's year+trim+engine.
- **v2 (2026-05-28)** — Multi-platform fallback chain added (SimplePart manufacturer-direct + Revolution Parts dealer aggregators). Ghost-link rejection + hyphen-slug bidirectional trim matching for 2026 model year disambiguation.
- **v1 (2026-05-28)** — Initial deploy. Kia + Hyundai + Genesis support via Revolution Parts dealer scraping, NHTSA VIN decoding, ScrapFly anti-bot bypass, trial+founder pricing, Stripe checkout, FastAPI + SQLite on Fly.io.

---

## How this file is used

When you ship code that improves the user-facing tool, add a new entry at
the top of this file with:

- The date
- A one-sentence `benefit` line (shown on the sign-in page)
- A bullet list of the actual changes (NOT shown publicly — internal log)

The sign-in template reads the top-of-file `benefit` line for the
"Latest deploy" banner so users see what's new every time we ship.

To update the banner copy: edit the `Latest deploy` line in
`src/lbt1/templates/signin.html` at the same time as you add the
CHANGELOG entry.
