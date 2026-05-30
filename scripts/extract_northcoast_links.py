"""Pull the make-to-dealer URLs from NorthCoast Keyless's guide.
Each `Key Fob VIN Search` button links to the dealer site they recommend
for that make."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

URL = "https://northcoastkeyless.com/how-to-find-the-right-oem-key-fob-for-your-vehicle-using-your-vin-number/"


async def main() -> None:
    backend = get_backend()
    try:
        r = await backend.fetch(URL)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.html, "lxml")
        # Each "Key Fob VIN Search" button is an <a> tag near a make name
        # Strategy: find <h3>/<h4>/<strong> with make name, find the next <a>
        anchors = soup.find_all("a", href=True)
        # Likely external dealer URLs
        external = []
        for a in anchors:
            href = a["href"]
            if href.startswith(("http://", "https://")):
                if "northcoastkeyless.com" in href.lower():
                    continue
                text = a.get_text(" ", strip=True)[:60]
                external.append((text, href))
        seen = set()
        uniq = []
        for t, h in external:
            if h not in seen:
                seen.add(h)
                uniq.append((t, h))
        print(f"External links: {len(uniq)}")
        for t, h in uniq:
            print(f"  {t:55s}  ->  {h}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
