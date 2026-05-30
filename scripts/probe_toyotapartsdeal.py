"""Probe toyotapartsdeal.com — AKS guide recommends THIS site for Toyota fobs
(not toyota.oempartsonline.com). Check whether (a) VIN search works,
(b) it actually carries the 89070-*/89904-* fob PNs Revolution Parts seems
to lack.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

VIN = "4T1G11AK6R0123456"  # 2024 Camry SE (computed valid VIN)
URLS = [
    f"https://www.toyotapartsdeal.com/genuine~vin~{VIN}.html",
    f"https://www.toyotapartsdeal.com/index.php?l=search_vin&vin={VIN}",
    f"https://www.toyotapartsdeal.com/vin/{VIN}",
    # Probably the search endpoint
    f"https://www.toyotapartsdeal.com/?s={VIN}",
    # Direct PN search
    "https://www.toyotapartsdeal.com/search.php?search=89070",
    "https://www.toyotapartsdeal.com/?s=89070",
    # Homepage to discover real VIN-search form action
    "https://www.toyotapartsdeal.com/",
]


async def main() -> None:
    backend = get_backend()
    try:
        for url in URLS:
            print("=" * 90)
            print(url)
            r = await backend.fetch(url)
            print(f"  status={r.status}  final={r.final_url}  len={len(r.html or '')}")
            if not r.ok:
                continue
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.html, "lxml")
            title = (soup.title.string or "").strip() if soup.title else ""
            print(f"  title: {title[:120]}")

            # Discover form actions (homepage)
            if "/" == url.rstrip("/").split("/")[-1] or url.endswith("toyotapartsdeal.com/"):
                for f in soup.find_all("form"):
                    action = f.get("action", "")
                    method = f.get("method", "GET")
                    inputs = [(i.get("name", ""), i.get("placeholder", "")) for i in f.find_all("input")]
                    print(f"  FORM action={action!r} method={method!r} inputs={inputs[:5]}")
                # Specific VIN-related inputs
                for el in soup.find_all("input"):
                    text = " ".join(str(v) for v in el.attrs.values() if isinstance(v, str)).lower()
                    if "vin" in text:
                        print(f"  VIN input: {dict(el.attrs)}")

            # Look for fob PN family on the page
            import re
            pns = re.findall(r"\b(8907\d|8990\d|8974\d)[\-\w]+", r.html or "")
            if pns:
                print(f"  Toyota fob-family PNs in HTML: {set(pns[:10])}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
