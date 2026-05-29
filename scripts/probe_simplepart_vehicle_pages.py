"""Inspect SimplePart vehicle + category page structure to design the parser.

Inputs (confirmed working):
  - parts.hyundaicanada.com /Hyundai_2017_Elantra-20L-AT.html (from CreateVinLinks)
  - parts.kia.com /Kia_2022_Telluride-38L-AT-4WD-SX.html

For each:
  1. What category navigation does the vehicle page expose?
  2. Where do keyless entry / anti-theft / transmitter parts live?
  3. What's the part-card HTML structure (selector for part name + PN)?
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
    # Hyundai Canada — 2017 Elantra (confirmed has data)
    "https://parts.hyundaicanada.com/Hyundai_2017_Elantra-20L-AT.html",
    # Kia US Official — 2022 Telluride (confirmed has data)
    "https://parts.kia.com/Kia_2022_Telluride-38L-AT-4WD-SX.html",
]


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

            # Look at the H1 / vehicle confirmation
            for h in soup.find_all(["h1", "h2"])[:5]:
                t = h.get_text(" ", strip=True)[:120]
                print(f"  H-tag: {t!r}")

            # Find category navigation
            html_lc = (r.html or "").lower()
            print(f"\n  Category-shaped links (containing keyless/electrical/anti-theft/keychain):")
            links = soup.find_all("a", href=True)
            seen = set()
            for a in links:
                href = a["href"]
                href_lc = href.lower()
                if any(k in href_lc for k in (
                    "keyless", "anti-theft", "antitheft", "electrical",
                    "transmitter", "remote", "smart-key", "smartkey",
                    "ignition", "keychain",
                )):
                    if href in seen:
                        continue
                    seen.add(href)
                    txt = a.get_text(" ", strip=True)[:60]
                    print(f"    {txt!r:55s} -> {href[:80]}")

            # List the FIRST 25 category-shaped links (any /<vehicle>/<category>/)
            print(f"\n  First 25 unique outbound links (excluding nav/utility):")
            seen2 = set()
            ct = 0
            for a in links:
                href = a["href"]
                href_lc = href.lower()
                if any(x in href_lc for x in (
                    "#", "javascript:", "/cart", "/checkout", "/login", "/account",
                    "/contact", "/help", "/faq", "/shipping", "/returns", "/about",
                    "/policy", "/terms", "tel:", "mailto:",
                )):
                    continue
                if href in seen2:
                    continue
                seen2.add(href)
                txt = a.get_text(" ", strip=True)[:60]
                if not txt:
                    continue
                print(f"    {txt!r:55s} -> {href[:90]}")
                ct += 1
                if ct >= 25:
                    break
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
