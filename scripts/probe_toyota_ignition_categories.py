"""Last-shot probe for Toyota fobs on toyota.oempartsonline.com:
the morning autopilot listed `electrical--ignition-lock`, `electrical--
ignition-system`, and 5 `ignition--*` sub-paths but capped at 8 probes
and missed these. Toyota smart keys are often filed under "Ignition" on
OEM diagrams."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

VEHICLE = "https://toyota.oempartsonline.com/v-2024-toyota-camry--se--2-5l-l4-gas"
CANDIDATES = [
    f"{VEHICLE}/electrical--ignition-lock",
    f"{VEHICLE}/electrical--ignition-system",
    f"{VEHICLE}/electrical--anti-theft-components",
    f"{VEHICLE}/ignition--switches-solenoids-and-actuators",
    f"{VEHICLE}/ignition--control-modules",
]
TOYOTA_KEY_PN_PREFIXES = ("89070", "89904", "89742", "89745")


async def main() -> None:
    backend = get_backend()
    try:
        for url in CANDIDATES:
            print("=" * 90)
            print(url)
            r = await backend.fetch(url)
            print(f"  status={r.status}  len={len(r.html or '')}")
            if not r.ok:
                continue
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.html, "lxml")
            cards = soup.select(".marketplace-info-col")
            print(f"  cards: {len(cards)}")
            fob_hits = 0
            relevant = []
            for c in cards:
                pn_el = c.select_one(".product-partnum a")
                name_el = c.select_one(".product-title a")
                if not pn_el:
                    continue
                pn = pn_el.get_text(strip=True)
                name = name_el.get_text(strip=True) if name_el else ""
                pn_clean = pn.replace("-", "").lower()
                if any(pn_clean.startswith(p) for p in TOYOTA_KEY_PN_PREFIXES):
                    fob_hits += 1
                    relevant.append((pn, name))
                elif any(kw in name.lower() for kw in (
                    "fob", "smart key", "transmitter", "key fob",
                    "remote control transmitter", "ignition key",
                )):
                    relevant.append((pn, name))
            print(f"  fob/key-relevant PNs: {fob_hits + len(relevant) - fob_hits} (fob family: {fob_hits})")
            for pn, name in relevant[:15]:
                print(f"    {pn:22s}  {name}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
