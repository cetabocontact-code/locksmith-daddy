"""Hypothesis test (do NOT build a driver yet):

The dealer's static product-page title lags behind their VIN-aware fitment
check. Test whether the `?vin={VIN}` URL pattern surfaces the dealer's
authoritative attestation for 2026 VINs that strict-title check rejected.

For each test VIN, probe two surfaces:

  1. SEARCH ROUTING: {dealer}/search?search_str={VIN}
     If the dealer's catalog recognizes the VIN as a 2026 model, the
     search redirects to /v-2026-{make}-{model} — strong signal that
     the dealer's catalog DB has 2026 data even when their product
     pages don't yet say "2026" in the title.

  2. PRODUCT-PAGE FITMENT WIDGET: {dealer}/oem-parts/...{pn}?vin={VIN}
     If the dealer's CMS has a "Fits this vehicle" / "Confirmed fit"
     widget that activates when ?vin= is provided, we'll see indicator
     text/classes in the rendered HTML.

Per-VIN result includes:
  - search_final_url     where dealer routed the VIN
  - search_route_year    parsed year segment in the routed URL
  - vin_product_routing  what the {pn}?vin= page redirects to
  - fitment_indicator    presence of "fits"/"confirmed"/"compatible" markers
  - vehicle_panel_text   the dealer's own selected-vehicle context text

We're NOT calling this dealer-verification yet — we're collecting evidence
to decide whether building VinAwareFitmentDriver is worth it.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bs4 import BeautifulSoup

from lbt1.scrapers.backends import get_backend

# Test cases pulled from the unverified VIN tracker — mix of makes,
# root causes, and predicted PNs from KnownPnProbe catalog/research.
TESTS = [
    # (vin, year, make, model, predicted_pn, dealer_host)
    ("KMHLM4DG3TU122912", 2026, "Hyundai", "Elantra",       "95440-AA501", "hyundai.oempartsonline.com"),
    ("KMHL24JA8TA526926", 2026, "Hyundai", "Sonata",        "95440-3Q000", "hyundai.oempartsonline.com"),
    ("KM8RJES21TU031654", 2026, "Hyundai", "Palisade",      "95440-S8520", "hyundai.oempartsonline.com"),
    ("KNDEPCAA3T7857273", 2026, "Kia",     "Seltos",        "95440-Q5400", "kia.oempartsonline.com"),
    ("KNDRKDJGXT5451156", 2026, "Kia",     "Sorento",       "95440-P2000", "kia.oempartsonline.com"),
    ("JTNABAAE4TA024584", 2026, "Toyota",  "GR Corolla",    "8990H-12460", "toyota.oempartsonline.com"),
    ("5TDZRKEC8TS306831", 2026, "Toyota",  "Sienna",        "8990H-08021", "toyota.oempartsonline.com"),
    ("5TDAAAB51TS110525", 2026, "Toyota",  "Grand Highlander", "8990H-48052", "toyota.oempartsonline.com"),
    # Brand-new nameplates (RC-3) — toughest case
    ("JTMBDAFB4TJ013439", 2026, "Toyota",  "bZ",            "",            "toyota.oempartsonline.com"),
    ("JTEVA5BR3T5091876", 2026, "Toyota",  "4Runner",       "",            "toyota.oempartsonline.com"),
]


async def probe_search_routing(backend, dealer: str, vin: str) -> dict:
    """Hit dealer search with VIN. Returns where the dealer routed us."""
    url = f"https://{dealer}/search?search_str={vin}"
    r = await backend.fetch(url)
    out = {
        "search_url": url,
        "search_ok": r.ok,
        "search_status": r.status,
        "search_final_url": r.final_url if r.ok else None,
        "search_route_year": None,
        "search_route_model": None,
    }
    if r.ok and r.final_url:
        # Parse year from /v-YYYY-make-model path
        m = re.search(r"/v-(\d{4})-([a-z]+)-([a-z0-9\-]+?)(?:--|/|\?|$)",
                      r.final_url.lower())
        if m:
            out["search_route_year"] = int(m.group(1))
            out["search_route_model"] = m.group(3)
    return out


async def probe_vin_aware_product(
    backend, dealer: str, pn: str, vin: str, year: int, make: str, model: str
) -> dict:
    """Visit candidate product page with ?vin= and look for fitment widget."""
    if not pn:
        return {"product_url": None, "skipped": "no predicted PN"}

    # Try the canonical Revolution Parts product URL pattern.
    pn_compact = pn.replace("-", "").lower()
    slug_guesses = [
        # Toyota uses transmitter-sub-assembly-electrical-key-...
        f"{make.lower()}-transmitter-sub-assembly-electrical-key-{pn_compact}",
        f"{make.lower()}-keyless-entry-transmitter-{pn_compact}",
        f"{make.lower()}-transmitter-{pn_compact}",
        f"{make.lower()}-fob-smart-key-{pn_compact}",
        f"{make.lower()}-smart-key-fob-{pn_compact}",
    ]
    product_url = None
    page_html = None
    page_final_url = None
    for slug in slug_guesses:
        url = f"https://{dealer}/oem-parts/{slug}?vin={vin}"
        r = await backend.fetch(url)
        if r.ok and "/oem-parts/" in (r.final_url or ""):
            product_url = url
            page_html = r.html
            page_final_url = r.final_url
            break

    out = {
        "product_url": product_url,
        "product_final_url": page_final_url,
        "found_product_page": page_html is not None,
        "title": None,
        "fitment_indicators": [],
        "vehicle_panel_text": None,
        "year_in_title": False,
        "model_in_title": False,
    }
    if not page_html:
        return out

    soup = BeautifulSoup(page_html, "lxml")
    title = (soup.title.string or "").strip() if soup.title else ""
    out["title"] = title[:200]
    out["year_in_title"] = str(year) in title
    out["model_in_title"] = model.lower() in title.lower()

    text = soup.get_text(" ", strip=True)

    # Hunt for the dealer's "selected vehicle" / "fits this vehicle" widget.
    # Revolution Parts renders this with class names like:
    #   .vehicle-context, .vehicle-panel, .vehicle-selector
    #   .confirmed-fit, .fits-vehicle, .vehicle-applies
    # Plus marketing copy like "Fits this vehicle" / "Confirmed for your..."
    for sel in [
        ".vehicle-context", ".vehicle-panel", ".vehicle-selector",
        ".confirmed-fit", ".fits-vehicle", "[class*='fitment']",
        "[class*='vehicle-selected']", "[data-vehicle]",
    ]:
        for el in soup.select(sel):
            txt = el.get_text(" ", strip=True)
            if txt and len(txt) < 400:
                out["fitment_indicators"].append(f"{sel}: {txt[:180]}")
                if not out["vehicle_panel_text"]:
                    out["vehicle_panel_text"] = txt[:200]

    # Marketing-copy markers
    for pat in [
        r"fits\s+this\s+vehicle",
        r"confirmed\s+for\s+your",
        r"confirmed\s+fit",
        r"will\s+fit\s+your\s+\d{4}",
        r"perfectly\s+fit\s+your\s+\d{4}",
        r"selected\s+vehicle[:\s]",
        r"your\s+(\d{4})\s+toyota",
        r"your\s+(\d{4})\s+hyundai",
        r"your\s+(\d{4})\s+kia",
    ]:
        for m in re.finditer(pat, text, re.IGNORECASE):
            ctx_start = max(0, m.start() - 30)
            ctx_end = min(len(text), m.end() + 120)
            ctx = text[ctx_start:ctx_end]
            out["fitment_indicators"].append(f"copy: ...{ctx[:200]}...")
            break  # first match per pattern

    return out


async def main():
    backend = get_backend()
    print(f"{'VIN':18s}  {'Search→year':12s}  {'Route model':18s}  {'Product page':14s}  {'Title-year':10s}  {'Title-model':12s}  Fitment evidence")
    print("=" * 160)
    for vin, year, make, model, pn, dealer in TESTS:
        sr = await probe_search_routing(backend, dealer, vin)
        pr = await probe_vin_aware_product(backend, dealer, pn, vin, year, make, model)

        rt_year = sr.get("search_route_year") or "—"
        rt_model = (sr.get("search_route_model") or "—")[:18]
        prod_found = "found" if pr.get("found_product_page") else "no-page"
        yr_in_title = "✓" if pr.get("year_in_title") else "✗"
        mod_in_title = "✓" if pr.get("model_in_title") else "✗"
        fit = pr.get("fitment_indicators") or []
        fit_summary = f"{len(fit)} marker(s)" if fit else "none"
        print(f"{vin:18s}  {str(rt_year):12s}  {rt_model:18s}  {prod_found:14s}  {yr_in_title:10s}  {mod_in_title:12s}  {fit_summary}")
        if fit:
            for f in fit[:2]:
                print(f"    └─ {f[:140]}")

    print()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
