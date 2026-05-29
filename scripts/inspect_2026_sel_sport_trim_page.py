"""Now that we land on /v-2026-hyundai-elantra--sel-sport--2-0l-l4-gas
(verified the correct trim), the three sub-category sweep URLs all 410.
Inspect the actual trim page to see what category URLs are linked, and
whether the dealer routes keyless-entry/anti-theft parts under different
section/slug pairs for 2026 trims.
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
    "https://hyundai.oempartsonline.com/v-2026-hyundai-elantra--sel-sport--2-0l-l4-gas",
    "https://www.hyundaioempart.com/v-2026-hyundai-elantra--sel-sport--2-0l-l4-gas",
    # A 2025 trim that's known to work — what category URLs does IT link?
    "https://hyundai.oempartsonline.com/v-2025-hyundai-elantra--sel-sport--2-0l-l4-gas",
]


async def main() -> None:
    backend = get_backend()
    try:
        for url in URLS:
            print("=" * 100)
            print(url)
            r = await backend.fetch(url)
            print(f"  status={r.status}  final={r.final_url}  htmllen={len(r.html or '')}")
            if r.error:
                print(f"  error={r.error[:200]}")
                continue
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.html, "lxml")
            title = (soup.title.string or "").strip() if soup.title else ""
            print(f"  title: {title[:160]}")

            # All category links from this trim page
            links = soup.find_all("a", href=True)
            cat_links = []
            for a in links:
                href = a["href"]
                # Look for hrefs that go into category sub-paths under this trim
                if "--" in href and href.count("/") >= 3:
                    if any(kw in href.lower() for kw in (
                        "electrical", "keyless", "anti-theft", "remote",
                        "transmitter", "fob", "smart-key", "ignition",
                    )):
                        txt = a.get_text(" ", strip=True)[:80]
                        cat_links.append((txt, href))
            seen = set()
            print(f"  Key/electrical-related category links: ")
            for txt, href in cat_links:
                if href in seen:
                    continue
                seen.add(href)
                print(f"    {txt!r:55s} -> {href}")

            # Also list all top-level navigation/section links
            print(f"\n  All sub-paths off this trim page (top 30):")
            all_subpaths = set()
            for a in links:
                href = a["href"]
                # Restrict to relative or same-host paths that are sub-pages
                if "/v-2026-hyundai-elantra--sel-sport--2-0l-l4-gas/" in href \
                   or "/v-2025-hyundai-elantra--sel-sport--2-0l-l4-gas/" in href:
                    all_subpaths.add(href)
            for sp in sorted(all_subpaths)[:30]:
                print(f"    {sp}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
