"""See what trims the 2026 Hyundai Elantra chooser actually offers on both
dealers. Our scraper is constructing /v-2026-hyundai-elantra--sel-sport-premium--2-0l-l4-gas
and the dealer is silently 301-ing that back to the bare model page — meaning
the dealer doesn't have a trim called "SEL Sport Premium".

We need to know the dealer's actual trim names so we can match NHTSA's
"SEL Sport Premium" to the right one (or fall back to model-level parts).
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
    "https://hyundai.oempartsonline.com/v-2026-hyundai-elantra",
    "https://www.hyundaioempart.com/v-2026-hyundai-elantra",
    "https://hyundai.oempartsonline.com/v-2025-hyundai-elantra",   # baseline: 2025 should have full trim list
    "https://www.hyundaioempart.com/v-2025-hyundai-elantra",
]


async def main() -> None:
    backend = get_backend()
    try:
        for url in URLS:
            print("=" * 100)
            print(url)
            r = await backend.fetch(url)
            print(f"  status={r.status}  final={r.final_url}")
            if r.error:
                print(f"  error={r.error[:200]}")
                continue

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.html, "lxml")
            title = (soup.title.string or "").strip() if soup.title else ""
            print(f"  title: {title[:160]}")

            # The trim chooser usually lists each option as a link to a
            # /v-{year}-{make}-{model}--{trim}--{engine} URL.
            links = soup.find_all("a", href=True)
            trim_links = []
            for a in links:
                href = a.get("href", "")
                # Catch both `/v-2026-hyundai-elantra--...` and absolute versions
                if "/v-2026-hyundai-elantra--" in href or "/v-2025-hyundai-elantra--" in href:
                    trim_links.append((a.get_text(strip=True)[:60], href))

            seen = set()
            unique_trim_links = []
            for txt, href in trim_links:
                if href not in seen:
                    seen.add(href)
                    unique_trim_links.append((txt, href))

            print(f"  trim URLs found: {len(unique_trim_links)}")
            for txt, href in unique_trim_links:
                print(f"    {txt!r:40s} -> {href}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
