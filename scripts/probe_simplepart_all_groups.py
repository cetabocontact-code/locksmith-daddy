"""Enumerate ALL schematic groups on Hyundai 2017 Elantra (Hyundai Canada)
and Kia 2022 Telluride (Kia US), across Body-and-Trim AND Electric, so we
can identify EVERY group name that contains key/fob/transmitter parts.

Reveals the gaps in our current keyword pattern set.
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


COMBOS = [
    ("Hyundai 2017 Elantra", "https://parts.hyundaicanada.com",
     "/Hyundai_2017_Elantra-20L-AT", ["Body-and-Trim", "Electric"]),
    ("Kia 2022 Telluride SX", "https://parts.kia.com",
     "/Kia_2022_Telluride-38L-AT-4WD-SX", ["Body-and-Trim", "Electric"]),
]


async def main() -> None:
    backend = get_backend()
    try:
        for label, host, vpath, cats in COMBOS:
            print("=" * 100)
            print(label)
            for cat in cats:
                url = f"{host}{vpath}/{cat}.html"
                print(f"\n  --- {cat} ---  {url}")
                r = await backend.fetch(url)
                if not r.ok:
                    print(f"    failed: {r.status} {r.error}")
                    continue
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(r.html, "lxml")
                # Extract every /a/.../{NAME}/{schid} link
                seen = set()
                groups = []
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if not href.startswith("/a/"):
                        continue
                    if href in seen:
                        continue
                    seen.add(href)
                    m = re.match(r"/a/[^/]+/_\d+_\d+/([^/]+)/", href)
                    name = (m.group(1) if m else "").upper()
                    if name:
                        groups.append(name)
                # Sort unique
                uniq = sorted(set(groups))
                print(f"    Total unique groups: {len(uniq)}")
                for nm in uniq:
                    marker = ""
                    for kw in (
                        "KEY", "FOB", "TRANSMITTER", "BURGLAR", "ANTI",
                        "REMOTE", "SMART", "IGNITION", "IMMOBIL",
                        "ALARM", "RECEIVER", "LOCKING", "ECU", "BCM",
                    ):
                        if kw in nm:
                            marker = f"  <<<{kw}"
                            break
                    print(f"      {nm}{marker}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
