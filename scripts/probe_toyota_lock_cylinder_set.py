"""Probe the EXACT Revolution Parts URL for Toyota fob per AKS guide:
`{vehicle_url}/body--lock-cylinder-set` should contain 89070-*/89904-* fobs.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

VEHICLE = "https://toyota.oempartsonline.com/v-2024-toyota-camry--se--2-5l-l4-gas"
CANDIDATES = [
    f"{VEHICLE}/body--lock-cylinder-set",       # AKS guide says THIS
    f"{VEHICLE}/body--lock-and-hardware",       # we found this had 64 cards
    f"{VEHICLE}/electrical--anti-theft-system", # already swept by current driver
]
TOYOTA_KEY_PN_PREFIXES = ("89070", "89904", "89742", "89745", "69515", "69058")


async def main() -> None:
    backend = get_backend()
    try:
        for url in CANDIDATES:
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
            cards = soup.select(".marketplace-info-col")
            print(f"  cards: {len(cards)}")
            fob_hits = 0
            for c in cards[:30]:
                pn_el = c.select_one(".product-partnum a")
                name_el = c.select_one(".product-title a")
                if not pn_el:
                    continue
                pn = pn_el.get_text(strip=True)
                name = name_el.get_text(strip=True) if name_el else ""
                pn_clean = pn.replace("-", "").lower()
                is_fob = any(pn_clean.startswith(p) for p in TOYOTA_KEY_PN_PREFIXES)
                if is_fob:
                    fob_hits += 1
                marker = "  <<< FOB" if is_fob else ""
                if is_fob or len(name) > 0:
                    print(f"    pn={pn:18s}  name={name[:50]:50s}{marker}")
            print(f"  >>> total fob PNs on this page: {fob_hits}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
