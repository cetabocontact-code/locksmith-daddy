"""Find the Site/site header value the JS sends with every API request."""

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
    "https://www.toyotapartsdeal.com/",
    "https://www.toyotapartsdeal.com/js/vendor.js?v=2026052803",
    "https://www.toyotapartsdeal.com/js/common.js?v=2026052803",
    "https://www.toyotapartsdeal.com/js/main.js?v=2026052803",
]


async def main() -> None:
    backend = get_backend()
    try:
        for url in URLS:
            print("=" * 90)
            print(url)
            r = await backend.fetch(url)
            body = r.html or ""
            print(f"  len={len(body)}")

            # Look for serverConfig / siteInfo / site_id mentions with surrounding context
            for pat in [
                r"serverConfig\s*[:=]\s*[\{\"'][^,]{0,200}",
                r"siteInfo[^,]{0,200}",
                r"['\"`]Site['\"`]\s*:\s*['\"`][^'\"`]+['\"`]",
                r"['\"`]X-Site[^'\"`]*['\"`]",
                r"site_id\s*[:=]\s*['\"`][^'\"`]+",
                r"siteId\s*[:=]\s*['\"`][^'\"`]+",
                r"window\.__INITIAL_STATE__\s*=\s*['\"`{\[][^\\n]{0,1500}",
                # Default axios config
                r"axios\.defaults[^;]{0,400}",
                r"headers\s*[:=]\s*\{[^}]{0,300}\}",
            ]:
                for m in re.finditer(pat, body, re.IGNORECASE | re.DOTALL):
                    snip = m.group(0)[:400].replace("\n", " ")
                    print(f"  MATCH [{pat[:40]!r}]: {snip}")

            # If it's the homepage HTML, look for inline window.__INITIAL_STATE__
            if "https://www.toyotapartsdeal.com/" == url:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(body, "lxml")
                for s in soup.find_all("script"):
                    code = s.string or ""
                    if "site" in code.lower() and "config" in code.lower():
                        preview = code.strip()[:2000].replace("\n", " ")
                        print(f"\n  INLINE inline-script preview: {preview}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
