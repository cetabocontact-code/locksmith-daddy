"""Find where SimplePart catalogs hide keyless entry transmitters.
Hyundai/Kia OEM PN 95440-* is the established key fob family. Check
Body, Chassis, Engine top-level categories on the 2017 Elantra (which
we know has 95440-AA500-class fobs in Revolution Parts).

Also: try the SmartSearch endpoint directly with '95440' or 'transmitter'
to see if their search returns key parts.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402


TOP_CAT_URLS = [
    "https://parts.hyundaicanada.com/Hyundai_2017_Elantra-20L-AT/Body-and-Trim.html",
    "https://parts.hyundaicanada.com/Hyundai_2017_Elantra-20L-AT/Chassis.html",
    "https://parts.kia.com/Kia_2022_Telluride-38L-AT-4WD-SX/Body-and-Trim.html",
    "https://parts.kia.com/Kia_2022_Telluride-38L-AT-4WD-SX/Chassis.html",
]

# Try search-by-keyword with terms locksmiths would use, on both sites.
SEARCH_URLS = [
    "https://parts.hyundaicanada.com/productSearch.aspx?searchTerm={q}",
    "https://parts.kia.com/productSearch.aspx?searchTerm={q}",
]
QUERIES = ["95440", "Transmitter", "Keyless"]


KEY_KEYWORDS = (
    "keyless", "key fob", "smart key", "smart-key", "transmitter",
    "anti-theft", "anti theft", "antitheft", "burglar", "remote", "key cylinder",
    "immobilizer",
)


async def probe_category(backend, url: str) -> None:
    print("=" * 100)
    print(url)
    r = await backend.fetch(url)
    print(f"  status={r.status}  len={len(r.html or '')}")
    if not r.ok or r.error:
        print(f"  failed: {r.error}")
        return

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.html, "lxml")
    # All schematic group links
    seen = set()
    groups = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/a/") and href not in seen:
            seen.add(href)
            m = re.match(r"/a/[^/]+/_\d+_\d+/([^/]+)/", href)
            nm = m.group(1) if m else a.get_text(strip=True)
            if nm:
                groups.append((nm, href))

    # Filter for key-related (case-insensitive)
    key_groups = [(n, h) for n, h in groups if any(k in (n + h).lower() for k in KEY_KEYWORDS)]
    print(f"  groups: {len(groups)}  key-related: {len(key_groups)}")
    for nm, href in groups[:30]:
        m = " <<<KEY" if any(k in (nm + href).lower() for k in KEY_KEYWORDS) else ""
        print(f"    {nm}{m}")


async def probe_search(backend, host_url: str, query: str) -> None:
    url = host_url.format(q=quote(query))
    print(f"\n{'='*100}")
    print(f"SEARCH: {url}")
    r = await backend.fetch(url)
    print(f"  status={r.status}  final={r.final_url}  len={len(r.html or '')}")
    if not r.ok or r.error:
        print(f"  failed: {r.error}")
        return

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.html, "lxml")
    title = (soup.title.string or "").strip() if soup.title else ""
    print(f"  title: {title[:160]}")
    # Look for /p/ part links
    seen = set()
    parts = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/p/") and href.endswith(".html") and href not in seen:
            seen.add(href)
            txt = a.get_text(" ", strip=True)[:80]
            m = re.match(r"/p/[^/]+/[^/]+/\d+/([^.?]+)\.html", href)
            pn = m.group(1) if m else "?"
            parts.append((txt, pn, href))
    print(f"  Part hits: {len(parts)}")
    for txt, pn, href in parts[:15]:
        print(f"    pn={pn!r:25s} name={txt!r:55s}")


async def main() -> None:
    backend = get_backend()
    try:
        for url in TOP_CAT_URLS:
            await probe_category(backend, url)
        for host in SEARCH_URLS:
            for q in QUERIES:
                await probe_search(backend, host, q)
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
