"""Look at the raw HTML of the Electric page. The first probe only found
4 part links and 0 sub-categories — likely there's image-map navigation
or JSON-driven render. Look at the actual page structure to understand
the real catalog layout.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402


URL = "https://parts.hyundaicanada.com/Hyundai_2017_Elantra-20L-AT/Electric.html"


async def main() -> None:
    backend = get_backend()
    try:
        r = await backend.fetch(URL)
        print(f"status={r.status}  len={len(r.html or '')}\n")

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.html, "lxml")
        # Dump the main content body
        # Look for any "category" lists, dropdowns, navigation
        for selector in [
            ".category", ".categories", ".part-categories",
            "#categories", "#categoryList", ".catalog-section",
            "nav", ".breadcrumb",
            ".part-list", ".product-list", ".products",
            ".group", ".section", "ul",
        ]:
            elements = soup.select(selector)
            if not elements:
                continue
            # Only show interesting ones
            for el in elements[:3]:
                text = el.get_text(" ", strip=True)[:200]
                if len(text) < 30:
                    continue
                print(f"  [{selector}] {text!r}")
                # Show child links
                ch_links = el.find_all("a", href=True)[:8]
                for a in ch_links:
                    print(f"    -> {a.get_text(strip=True)[:60]!r} {a['href'][:80]}")
                print()

        # Look at the raw HTML between certain markers
        html = r.html or ""
        for marker in ("Anti-Theft", "Anti Theft", "Keyless", "Smart Key",
                       "Transmitter", "Switches", "Antenna",
                       "Ignition", "Lock"):
            idx = html.find(marker)
            if idx > 0:
                snippet = html[max(0, idx-200):idx+400].replace("\n", " ")
                print(f"\n[{marker!r}] @ {idx}:\n    {snippet[:600]}")

        # Look for JSON blobs that may carry the catalog
        for needle in ("categoryList", "categories\\\":", "subCategoryList", "subCategories"):
            idx = html.find(needle)
            if idx > 0:
                snippet = html[max(0, idx-80):idx+400].replace("\n", " ")
                print(f"\n[{needle!r}] @ {idx}:\n    {snippet[:600]}")

        # Image-map style?
        for el in soup.find_all("area")[:8]:
            print(f"  area: {dict(el.attrs)}")
        for el in soup.find_all("map")[:3]:
            print(f"  map: name={el.get('name')!r}, areas={len(el.find_all('area'))}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
