"""Inspect hyundaioempart.com to discover:
  - Homepage layout + VIN search input
  - URL pattern after VIN submission
  - Trim chooser behavior
  - Part card HTML structure on category pages

Burns ~4 ScrapFly ASP calls (~84 credits = $0.013).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Force the right backend
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

VINS_TO_INSPECT = [
    "KMHLS4DG5TU123100",   # 2026 Elantra SEL Sport Premium — the one that failed on Revolution Parts
    "5NPD84LFXHH074817",   # 2017 Elantra SE — works on Revolution Parts (baseline)
]


async def inspect_homepage(backend) -> None:
    print("=" * 70)
    print("STEP 1: Fetching homepage hyundaioempart.com")
    print("=" * 70)
    result = await backend.fetch("https://www.hyundaioempart.com/")
    print(f"  Status: {result.status}")
    print(f"  Final URL: {result.final_url}")
    print(f"  HTML length: {len(result.html)}")
    if result.error:
        print(f"  ERROR: {result.error}")
        return

    # Look for VIN search input
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(result.html, "lxml")
    inputs = soup.find_all("input")
    print(f"  Total input fields: {len(inputs)}")
    print()
    print("  Inputs that mention 'vin' (in name/placeholder/title):")
    for inp in inputs:
        attrs = {k: v for k, v in inp.attrs.items() if isinstance(v, str)}
        text = " ".join(attrs.values()).lower()
        if "vin" in text:
            print(f"    {attrs}")
    print()
    print("  All forms:")
    for form in soup.find_all("form"):
        print(f"    action={form.get('action')!r} method={form.get('method', 'GET')!r}")


async def inspect_vin_search(backend, vin: str) -> None:
    print("=" * 70)
    print(f"STEP 2: VIN search for {vin}")
    print("=" * 70)
    # Try common VIN search URL patterns
    candidates = [
        f"https://www.hyundaioempart.com/search?search_str={vin}",
        f"https://www.hyundaioempart.com/search?q={vin}",
        f"https://www.hyundaioempart.com/?vin={vin}",
        f"https://www.hyundaioempart.com/vehicle/{vin}",
    ]
    for url in candidates:
        result = await backend.fetch(url)
        print(f"\n  Tried: {url}")
        print(f"    Status: {result.status}")
        print(f"    Final:  {result.final_url}")
        print(f"    HTML len: {len(result.html)}")
        if result.error:
            print(f"    error: {result.error[:120]}")
            continue
        # Did it land on a vehicle page?
        if "/v-" in result.final_url or "/vehicle/" in result.final_url:
            print(f"    [match] Landed on vehicle-like URL.")
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(result.html, "lxml")
            title = soup.title.string.strip() if soup.title else ""
            print(f"    Title: {title[:120]}")
            return result
    return None


async def inspect_vehicle_html(backend, vin: str) -> None:
    print("=" * 70)
    print(f"STEP 3: What does the search land on for {vin}?")
    print("=" * 70)
    result = await backend.fetch(f"https://www.hyundaioempart.com/search?search_str={vin}")
    print(f"  Final URL: {result.final_url}")
    print(f"  Status: {result.status}")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(result.html, "lxml")
    if soup.title:
        print(f"  Title: {soup.title.string.strip()[:120]}")
    # Find links to category pages
    links = soup.find_all("a", href=True)
    interesting = [
        a for a in links
        if any(k in (a.get_text() or "").lower() for k in ("keyless", "transmitter", "smart key", "fob"))
    ]
    print(f"\n  Links matching key-related keywords: {len(interesting)}")
    for a in interesting[:10]:
        href = a["href"]
        text = a.get_text(strip=True)[:60]
        print(f"    {text!r} -> {href}")
    # Check if category URLs follow oempartsonline pattern
    cat_links = [a for a in links if "/electrical--keyless-entry-components" in a.get("href","")]
    if cat_links:
        cat_url = cat_links[0]["href"]
        if cat_url.startswith("/"):
            cat_url = "https://www.hyundaioempart.com" + cat_url
        print(f"\n  STEP 4: Fetching keyless-entry-components page directly")
        print(f"    URL: {cat_url}")
        r2 = await backend.fetch(cat_url)
        print(f"    Status: {r2.status}")
        if r2.html:
            soup2 = BeautifulSoup(r2.html, "lxml")
            cards = soup2.select(".marketplace-info-col")
            print(f"    .marketplace-info-col cards found: {len(cards)}")
            for i, c in enumerate(cards[:8]):
                title = c.select_one(".product-title a")
                pn = c.select_one(".product-partnum a")
                desc = c.select_one(".contextual_description")
                print(f"      [{i}] name={title.get_text(strip=True) if title else None!r}")
                print(f"          pn={pn.get_text(strip=True) if pn else None!r}")
                print(f"          desc={desc.get_text(strip=True) if desc else None!r}")


async def main() -> None:
    backend = get_backend()
    try:
        await inspect_homepage(backend)
        print()
        await inspect_vin_search(backend, VINS_TO_INSPECT[0])
        print()
        await inspect_vehicle_html(backend, VINS_TO_INSPECT[0])
        print()
        await inspect_vehicle_html(backend, VINS_TO_INSPECT[1])
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
