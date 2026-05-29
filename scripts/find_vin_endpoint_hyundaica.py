"""Find the actual VIN-search endpoint on parts.hyundaicanada.com by
extracting GetVinResults from JS sources. The homepage has an ASP.NET
form and an inline JS function that posts the VIN somewhere — find that
"somewhere".
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


async def dump_js(backend, url: str) -> None:
    print("=" * 100)
    print(f"DUMP {url}")
    r = await backend.fetch(url)
    if not r.ok or r.error:
        print(f"  failed: status={r.status} err={r.error}")
        return
    html = r.html or ""

    # 1. Pull all inline <script> blocks that mention VIN
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    print("\n  Inline <script> blocks containing 'vin' (case-insensitive):")
    for i, s in enumerate(soup.find_all("script")):
        body = s.string or ""
        if "vin" in body.lower():
            preview = body.strip()[:1200].replace("\n", "\n      ")
            print(f"    --- script[{i}] ---")
            print(f"      {preview}")

    # 2. Pull external <script src=...> URLs that look custom (not jQuery/3p)
    print("\n  External script src= (custom-looking):")
    for s in soup.find_all("script", src=True):
        src = s["src"]
        if any(third in src.lower() for third in (
            "google", "jquery.min", "bootstrap", "fontawesome", "cdn.jsdelivr",
            "cloudflare", "yandex", "googletagmanager"
        )):
            continue
        print(f"    {src}")

    # 3. Regex-pull any '/api/...' or '/sd/...' or 'searchresult' references
    print("\n  Endpoint-shaped strings in HTML/JS:")
    seen = set()
    for m in re.finditer(r'["\'](/[\w\-./%]+(?:\?[\w=&%-]*)?)["\']', html):
        path = m.group(1)
        if any(k in path.lower() for k in (
            "vin", "search", "/sd/", "/api/", "vehicle", "result", "garage"
        )):
            if path not in seen and len(path) < 120:
                seen.add(path)
                print(f"    {path}")


async def main() -> None:
    backend = get_backend()
    try:
        await dump_js(backend, "https://parts.hyundaicanada.com/")
        # Also check parts.kia.com (similar SAP catalog — may share endpoints)
        await dump_js(backend, "https://parts.kia.com/")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
