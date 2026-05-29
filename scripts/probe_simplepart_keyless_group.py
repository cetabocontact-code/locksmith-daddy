"""Search the SimplePart Electric page for the KEYLESS / SMART KEY /
TRANSMITTER schematic group, then probe that group page to find actual PNs.
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

KEY_GROUP_PATTERNS = (
    "KEYLESS", "SMART KEY", "SMART-KEY", "TRANSMITTER", "ANTI-THEFT",
    "ANTI THEFT", "ANTITHEFT", "BURGLAR", "FOB", "REMOTE", "IMMOBILIZER",
    "KEY & CYLINDER", "KEY AND CYLINDER", "IGNITION SWITCH",
)


async def probe(backend, url: str) -> list[tuple[str, str]]:
    print("=" * 100)
    print(url)
    r = await backend.fetch(url)
    print(f"  status={r.status}  len={len(r.html or '')}")
    if not r.ok or r.error:
        print(f"  failed: {r.error}")
        return []

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.html, "lxml")
    # All /a/ schematic group links
    seen = set()
    groups = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/a/") and href not in seen:
            seen.add(href)
            txt = a.get_text(" ", strip=True)[:60]
            # The group name might be in the URL too — extract
            m = re.match(r"/a/[^/]+/_\d+_\d+/([^/]+)/", href)
            url_name = m.group(1) if m else ""
            groups.append((txt or url_name, href))

    print(f"  Total /a/ schematic group links: {len(groups)}")
    # Filter for key-related
    key_groups = []
    for txt, href in groups:
        haystack = (txt + " " + href).upper()
        if any(kw in haystack for kw in KEY_GROUP_PATTERNS):
            key_groups.append((txt, href))
    print(f"  Key-related groups: {len(key_groups)}")
    for txt, href in key_groups:
        print(f"    {txt!r:50s} -> {href[:90]}")

    # Also dump all group names (uniqued by URL path) so we see what taxonomy exists
    print(f"\n  All distinct group names found:")
    distinct_names = set()
    for txt, href in groups:
        m = re.match(r"/a/[^/]+/_\d+_\d+/([^/]+)/", href)
        nm = m.group(1) if m else txt
        if nm:
            distinct_names.add(nm)
    for nm in sorted(distinct_names)[:60]:
        print(f"    {nm}")
    return key_groups


async def fetch_group(backend, url: str) -> None:
    print("\n" + "─" * 100)
    print(f"GROUP PAGE: {url}")
    r = await backend.fetch(url)
    print(f"  status={r.status}  len={len(r.html or '')}")
    if not r.ok or r.error:
        print(f"  failed: {r.error}")
        return

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.html, "lxml")
    title = (soup.title.string or "").strip() if soup.title else ""
    print(f"  title: {title[:160]}")

    # Look for /p/ part links (these have PN in URL)
    seen = set()
    parts = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/p/") and href.endswith(".html") and href not in seen:
            seen.add(href)
            txt = a.get_text(" ", strip=True)[:80]
            # Extract part number from /p/Make_Year_Model/Name/id/PN.html
            m = re.match(r"/p/[^/]+/[^/]+/\d+/([^.?]+)\.html", href)
            pn = m.group(1) if m else "?"
            parts.append((txt, pn, href))

    print(f"  Direct part links on this group page: {len(parts)}")
    for txt, pn, href in parts[:20]:
        print(f"    pn={pn!r:25s} name={txt!r:50s} href={href[:80]}")


async def main() -> None:
    backend = get_backend()
    try:
        for url in URLS:
            key_groups = await probe(backend, url)
            # Visit each key group page
            for txt, href in key_groups[:5]:
                if href.startswith("/"):
                    full = url.split("/", 3)[0] + "//" + url.split("/", 3)[2] + href
                else:
                    full = href
                await fetch_group(backend, full)
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
