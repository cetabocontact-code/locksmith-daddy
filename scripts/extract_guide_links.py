"""Extract the make-to-dealer-site link map from American Key Supply's
guide page. Each line says e.g. "Toyota / Lexus (Body > Lock Cylinder Set)"
with a hyperlink to the dealer parts site they recommend.

Run after fetch_locksmith_guides.py has saved the HTML.
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

URL = "https://www.americankeysupply.com/pages/finding-oem-parts-by-vin"


async def main() -> None:
    backend = get_backend()
    try:
        r = await backend.fetch(URL)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.html, "lxml")

        # Each make is a hyperlink. Find anchors whose text contains
        # a make name OR whose href points to a known dealer-parts domain.
        anchors = soup.find_all("a", href=True)
        # Common dealer-parts substrings to recognize
        dealer_substrs = (
            "oempartsonline", "parts.", "oempart", "partsdeal", "partsnow",
            "genuineparts", "oem.", "parts-",
        )
        results = []
        for a in anchors:
            href = a["href"]
            text = a.get_text(" ", strip=True)
            if not href.startswith(("http://", "https://")):
                continue
            if any(s in href.lower() for s in dealer_substrs):
                results.append((text[:60], href))

        # Dedupe by href
        seen = set()
        uniq = []
        for t, h in results:
            if h not in seen:
                seen.add(h)
                uniq.append((t, h))

        print(f"Found {len(uniq)} dealer-parts links:\n")
        for t, h in uniq:
            print(f"  {t:55s}  ->  {h}")

        # Also find every <li> entry with a make name + category in parens
        print("\n" + "=" * 90)
        print("Make → Category map (from inline text):")
        print("=" * 90)
        # Pattern: make name then "(Category > Subcategory)"
        body_text = soup.get_text("\n", strip=True)
        for m in re.finditer(r"^([A-Z][\w/ ]+?)\n\(([^)]+)\)", body_text, re.MULTILINE):
            make = m.group(1).strip()
            cat = m.group(2).strip()
            print(f"  {make:25s}  →  {cat}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
