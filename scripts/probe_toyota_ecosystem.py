"""Toyota OEM dealer ecosystem map (mirrors what we did for Hyundai/Kia).

Goal: identify Toyota dealer sites + their CMS, find the VIN search endpoint,
note which platform (Revolution Parts vs SimplePart vs custom).

Cheap probe — just homepages, no VIN searches yet. ~$0.10 total.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

TOYOTA_TARGETS = [
    # Manufacturer-direct
    "https://parts.toyota.com/",
    "https://www.toyota.com/owners/parts/",
    # Revolution Parts family (most likely candidates based on Hyundai/Kia pattern)
    "https://toyota.oempartsonline.com/",
    "https://www.toyotapartsdeal.com/",
    "https://www.toyotapartsnow.com/",
    "https://www.toyotaoempart.com/",
    "https://www.toyotapartshouse.com/",
    "https://www.toyotagenuineparts.com/",
    "https://parts.toyotaofgrenada.com/",
    "https://parts.toyotaofdallas.com/",
    # Canada
    "https://parts.toyota.ca/",
]


async def probe(backend, url: str) -> None:
    print("=" * 100)
    print(url)
    try:
        r = await asyncio.wait_for(backend.fetch(url), timeout=45)
    except Exception as exc:  # noqa: BLE001
        print(f"  EXCEPTION: {type(exc).__name__}")
        return
    print(f"  status={r.status}  final={r.final_url}  len={len(r.html or '')}")
    if r.error:
        print(f"  error: {r.error[:120]}")
        return

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.html or "", "lxml")
    title = (soup.title.string or "").strip() if soup.title else ""
    print(f"  title: {title[:120]}")

    # CMS detection
    html_lc = (r.html or "").lower()
    cms = []
    if "marketplace-info-col" in html_lc or "revolutionparts" in html_lc:
        cms.append("Revolution Parts")
    if "spapp" in html_lc or "/wm.aspx/createvinlinks" in html_lc:
        cms.append("SimplePart")
    if "ais-shop" in html_lc or "ais.toyota" in html_lc:
        cms.append("AIS Toyota Tech")
    print(f"  CMS: {cms or ['unknown/custom']}")

    # VIN input detection
    vin_inputs = []
    for el in soup.find_all("input"):
        haystack = " ".join(str(v) for v in el.attrs.values() if isinstance(v, str)).lower()
        if "vin" in haystack:
            vin_inputs.append({k: v for k, v in el.attrs.items() if isinstance(v, str)})
    print(f"  VIN inputs: {len(vin_inputs)}")
    for i in vin_inputs[:2]:
        print(f"    {i}")


async def main() -> None:
    backend = get_backend()
    try:
        for url in TOYOTA_TARGETS:
            await probe(backend, url)
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
