"""parts.hyundaicanada.com is an OFFICIAL Hyundai Canada parts catalog
distinct from Revolution Parts. Submit our problem VIN and see whether
the Canadian catalog has 2026 Elantra electrical/keyless data the US
Revolution Parts feed doesn't have.

If yes → we add a HyundaiCanadaDriver to the fallback chain and gain
real coverage on 2026+ Elantra (and likely other new model years).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

VINS = [
    "KMHLM4DG3TU122912",  # 2026 Elantra SEL Sport / Sport Plus (user's case)
    "KMHLS4DG5TU123100",  # 2026 Elantra SEL Sport Premium (the original)
    # Baseline that works on US Revolution Parts — should also work here
    "5XYK6CDF8TG390982",  # 2026 Kia Sportage X-Line (Kia, just for comparison)
]


SEARCH_URL_PATTERNS = [
    # Common SAP Web parts catalog patterns
    "https://parts.hyundaicanada.com/search?searchString={vin}",
    "https://parts.hyundaicanada.com/Search?searchString={vin}",
    "https://parts.hyundaicanada.com/sd/searchresult.aspx?searchString={vin}",
    "https://parts.hyundaicanada.com/sd/?searchString={vin}",
    "https://parts.hyundaicanada.com/search/{vin}",
    "https://parts.hyundaicanada.com/api/vehicle/vin/{vin}",
]


async def probe_homepage(backend) -> None:
    print("=" * 100)
    print("Homepage scrape — discover form action + JS hooks")
    print("=" * 100)
    r = await backend.fetch("https://parts.hyundaicanada.com/")
    if r.error or not r.ok:
        print(f"  homepage fetch failed: status={r.status} error={r.error}")
        return
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.html, "lxml")
    # Forms
    print("  Forms:")
    for f in soup.find_all("form"):
        attrs = {k: v for k, v in f.attrs.items() if isinstance(v, str)}
        print(f"    action={attrs.get('action')!r}  method={attrs.get('method', 'GET')!r}  id={attrs.get('id')!r}")
    # Look at the JS to find VIN-search endpoints
    html_lc = (r.html or "").lower()
    for needle in (
        "vin-search", "vinsearch", "/searchresult", "/sd/", "/api/",
        "getvinresults", "vehicle/vin", "garageapi", "/garage",
    ):
        idx = html_lc.find(needle)
        if idx >= 0:
            snippet = r.html[max(0, idx-60):idx+140].replace("\n", " ")
            print(f"  [{needle!r}] @ {idx}: …{snippet}…")


async def submit_vin(backend, vin: str) -> None:
    print(f"\n{'='*100}")
    print(f"VIN search: {vin}")
    print("=" * 100)
    for tmpl in SEARCH_URL_PATTERNS:
        url = tmpl.format(vin=vin)
        try:
            r = await asyncio.wait_for(backend.fetch(url), timeout=45)
        except Exception as exc:  # noqa: BLE001
            print(f"  {tmpl}: EXCEPTION {type(exc).__name__}")
            continue
        if not r.ok or r.error:
            print(f"  TRY {url}\n    status={r.status} error={(r.error or '')[:80]}")
            continue

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.html, "lxml")
        title = (soup.title.string or "").strip() if soup.title else ""
        # Skip obvious 404s
        if "404" in title or "page not found" in title.lower():
            print(f"  TRY {url}\n    404 ({title[:80]!r})")
            continue
        print(f"  TRY {url}")
        print(f"    status={r.status}  final={r.final_url}")
        print(f"    title: {title[:160]}")
        print(f"    htmllen={len(r.html or '')}")

        # Look for vehicle confirmation + category breakdown
        # SAP catalogs typically show:
        #   <h1>2026 Hyundai Elantra</h1>
        #   <ul class="categories"> ...keyless entry...
        for tag in soup.find_all(["h1", "h2"]):
            t = tag.get_text(" ", strip=True)[:120]
            if any(x in t.lower() for x in ("elantra", "sportage", "soul", "2026", "vehicle")):
                print(f"    H-tag: {t!r}")
        # Catalog category hints
        html_lc = (r.html or "").lower()
        for kw in ("keyless entry", "anti-theft", "transmitter", "smart key",
                   "remote", "ignition", "categories", "category"):
            if kw in html_lc:
                idx = html_lc.find(kw)
                print(f"    [{kw!r} hint @ {idx}]: …{html_lc[max(0,idx-40):idx+80]}…")
                break

        # First few links
        links = soup.find_all("a", href=True)[:8]
        for a in links:
            href = a["href"][:120]
            txt = a.get_text(" ", strip=True)[:60]
            if href and not href.startswith(("#", "javascript:")):
                print(f"    link: {txt!r:40s} -> {href}")


async def main() -> None:
    backend = get_backend()
    try:
        await probe_homepage(backend)
        for vin in VINS:
            await submit_vin(backend, vin)
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
