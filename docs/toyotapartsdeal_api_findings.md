# toyotapartsdeal.com API Reverse-Engineering — Findings

Investigation 2026-05-29. Reached 90% of the way to a working Toyota driver.
**One last blocker** to solve: multi-tenant `Site` header value.

## What we know

### Platform stack
- Vue/React SPA with code-split JS bundles
- `pages-BaseHome.js` exposes the search component (`renderSelectVehicleByVin`)
- All API calls go through a wrapper (`r.ZP`) that internally uses what
  looks like a custom Chinese-language axios-style client
- Error responses in Chinese (`Site:不存在` = "Site: does not exist") —
  suggests Chinese-developed platform, likely a shared backend across all
  the `*partsdeal.com` / `*partsnow.com` / `*partsgiant.com` family

### Discovered API endpoints
| Endpoint | Method | Purpose |
|---|---|---|
| `/api/url/vehicle-redirect` | **POST** | **VIN search** — the key one |
| `/api/vehicle/make-list` | GET | YMM: makes |
| `/api/vehicle/model-list` | GET | YMM: models for a make |
| `/api/vehicle/year-list` | GET | YMM: years |
| `/api/vehicle/submodel` | GET | YMM: trim |
| `/api/vehicle/extra1` | GET | likely engine |
| `/api/vehicle/extra2` | GET | likely drive/transmission |
| `/api/option/option-list` | POST | options/dropdowns |
| `/api/url/no-vehicle-redirect` | POST | fallback when no vehicle context |
| `/api/url/header-link` | GET | nav |
| `/api/user/*` | GET/POST | user's saved garage |

### Confirmed call signature for VIN search (from `pages-BaseHome.js`)
```javascript
u = function(e, t) {
  return r.ZP.post("/api/url/vehicle-redirect", e, t)
}
```
- `e` = body (probably `{vin: "..."}` but server rejects every shape we tried)
- `t` = config (probably headers)

## The blocker

Every POST attempt to `/api/url/vehicle-redirect` with any body shape returns:
```json
{"code": 204103, "data": null, "message": "Site:不存在"}
```

Tried bodies: `{vin}`, `{VIN}`, `{vinNumber}`, `{vin_number}`,
`{vehicleVin}`, `{vinSearch}`, `{search}`, `{data: {vin}}` — all same error.

The error message is **about the Site identifier, not the body**, meaning
backend validates `Site` BEFORE parsing body. We need to send the correct
multi-tenant site identifier (header or cookie).

Searched JS bundles for:
- `siteInfo` — referenced in `common.js` as `siteInfo:e.initApp.siteInfo`
  (loaded from server-rendered initial state — not a static value)
- `'Site'` header literal — not found
- `X-Site-Id` — not found
- Default axios headers — only saw `If-Modified-Since` shim

Likely answers (untested due to time):
1. **Cookie from homepage** — visit `/` first, capture cookies, send same
   cookies on POST. Standard SPA pattern.
2. **Header set by initApp** — the `initApp.siteInfo` blob is rendered
   server-side into the HTML. JS reads it and adds it to axios defaults.
   Would require JS rendering to capture (or parsing the homepage HTML
   for the embedded JSON state).
3. **Site identifier in URL** — `/site/123/api/...` — not seen but
   possible.

## Recommended next step (one $0.50 burn)

Send ONE request via ScrapFly with `render_js=true` and capture the
network requests it fires. ScrapFly's `network: true` flag returns all
XHR calls including their request headers. That gives us the exact
`Site` header (or cookie) the JS sends.

After that one probe, we have a working Toyota driver in ~30 min.

## What this also unlocks

Per `docs/dealer_source_map.md`, the `*partsdeal/*partsnow/*partsgiant`
family includes:
- **Toyota** (toyotapartsdeal.com)
- **Honda** (hondapartsnow.com)
- **Acura** (acurapartsnow.com, acurapartswarehouse.com)
- **Hyundai** (hyundaipartsdeal.com — duplicate source)
- **Kia** (kiapartsnow.com — duplicate)
- **Lexus** (lexuspartsnow.com)
- **Nissan** (nissanpartsdeal.com)
- **Infiniti** (infinitipartsdeal.com)
- **Subaru** (subarupartsdeal.com)
- **GM** (gmpartsgiant.com)
- **Ford** (fordpartsgiant.com)
- **Chrysler/Dodge/Jeep/RAM** (moparpartsgiant.com)
- **Scion** (toyotapartsdeal.com/scion-parts.html)

If all 13 sites share the same backend (very likely given the same JS
bundles, same Chinese error messages, same `/api/` namespace), **one
driver class with per-make base_url** covers 13 makes.

This single endpoint unlock = the multi-make expansion play.
