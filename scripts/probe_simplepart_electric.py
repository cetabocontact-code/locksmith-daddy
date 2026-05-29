"""Drill into the Electric category on SimplePart catalogs to find where
keyless entry / smart key / transmitter parts are listed. The vehicle
page exposes /Electric.html — we expect sub-category links from there
down to specific PNs.
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


URLS = [
    "https://parts.hyundaicanada.com/Hyundai_2017_Elantra-20L-AT/Electric.html",
    "https://parts.kia.com/Kia_2022_Telluride-38L-AT-4WD-SX/Electric.html",
]

KEY_KEYWORDS = (
    "keyless", "anti-theft", "transmitter", "fob", "smart-key", "smart key",
    "remote", "key", "immobilizer",
)


async def main() -> None:
    backend = get_backend()
    try:
        for url in URLS:
            print("=" * 100)
            print(url)
            r = await backend.fetch(url)
            print(f"  status={r.status}  final={r.final_url}  len={len(r.html or '')}")
            if r.error:
                print(f"  error: {r.error[:200]}")
                continue

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.html, "lxml")
            title = (soup.title.string or "").strip() if soup.title else ""
            print(f"  title: {title[:160]}")

            for h in soup.find_all(["h1", "h2", "h3"])[:5]:
                t = h.get_text(" ", strip=True)[:120]
                print(f"  H-tag: {t!r}")

            # ALL links on this page
            links = soup.find_all("a", href=True)
            print(f"\n  Total links: {len(links)}")

            # Sub-category links (within Electric)
            seen = set()
            sub_cats = []
            for a in links:
                href = a["href"]
                # Sub-categories under /Electric/ typically look like:
                #   /Hyundai_2017_Elantra-20L-AT/Electric/Something.html
                if "/Electric/" in href and href.endswith(".html"):
                    if href in seen:
                        continue
                    seen.add(href)
                    txt = a.get_text(" ", strip=True)[:80]
                    sub_cats.append((txt, href))
            print(f"\n  Electric sub-categories: {len(sub_cats)}")
            for txt, href in sub_cats[:25]:
                key_match = " <<<KEY" if any(k in (txt + href).lower() for k in KEY_KEYWORDS) else ""
                print(f"    {txt!r:60s} -> {href[:80]}{key_match}")

            # PART links (have /p/ in path)
            seen = set()
            parts = []
            for a in links:
                href = a["href"]
                if href.startswith("/p/") and href.endswith(".html"):
                    if href in seen:
                        continue
                    seen.add(href)
                    txt = a.get_text(" ", strip=True)[:80]
                    parts.append((txt, href))
            print(f"\n  Direct part links: {len(parts)}")
            for txt, href in parts[:15]:
                key_match = " <<<KEY" if any(k in (txt + href).lower() for k in KEY_KEYWORDS) else ""
                print(f"    {txt!r:60s} -> {href[:90]}{key_match}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
