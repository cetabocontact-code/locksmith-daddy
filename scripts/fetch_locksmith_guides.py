"""Fetch the two locksmith industry guides the user pointed at — they'll
tell us where Toyota fob PNs actually live in dealer catalogs and may
flag additional source sites we can wire as backup.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

URLS = [
    "https://www.americankeysupply.com/pages/finding-oem-parts-by-vin",
    "https://northcoastkeyless.com/how-to-find-the-right-oem-key-fob-for-your-vehicle-using-your-vin-number/",
]


async def main() -> None:
    backend = get_backend()
    try:
        for url in URLS:
            print("=" * 100)
            print(url)
            r = await backend.fetch(url)
            print(f"  status={r.status}  len={len(r.html or '')}")
            if not r.ok:
                print(f"  error: {r.error}")
                continue
            # Save raw HTML to disk for reading
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.html, "lxml")
            # Extract just the article text
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text("\n", strip=True)
            slug = url.replace("https://", "").replace("/", "_").replace(":", "_")[:80]
            out = Path(__file__).resolve().parents[1] / "data" / "runs" / f"guide_{slug}.txt"
            out.write_text(text, encoding="utf-8")
            print(f"  wrote {out}")
            print()
            # Print first 1500 chars for inspection
            print(text[:1500])
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
