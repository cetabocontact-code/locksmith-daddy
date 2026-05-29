"""Look directly at the KEY--CYLINDER-SET and FRONT-DOOR-LOCKING pages on
a SMART-KEY-era Hyundai (2024 Elantra) and Kia (2022 Telluride). Want to
confirm whether 95440-* smart fobs ARE under KEY--CYLINDER-SET for newer
vehicles, or if they live in a different group.

Also probes the productSearch.aspx endpoint to test VIN-scoping.
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


VEHICLES = [
    # vehicle_url, base_url
    ("https://parts.kia.com/Kia_2022_Telluride-38L-AT-4WD-SX",
     "https://parts.kia.com"),
    ("https://parts.hyundaicanada.com/Hyundai_2017_Elantra-20L-AT",
     "https://parts.hyundaicanada.com"),
]


async def list_groups(backend, vehicle_url: str, cat: str) -> list[tuple[str, str]]:
    """Return all (group_name, full_group_url) pairs under a top category."""
    cat_url = f"{vehicle_url}/{cat}.html"
    r = await backend.fetch(cat_url)
    if not r.ok:
        return []
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.html, "lxml")
    seen = set()
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("/a/"):
            continue
        if href in seen:
            continue
        seen.add(href)
        m = re.match(r"/a/[^/]+/_\d+_\d+/([^/]+)/", href)
        nm = (m.group(1) if m else "").upper()
        if nm:
            from urllib.parse import urljoin
            out.append((nm, urljoin(cat_url, href)))
    return out


async def dump_group(backend, url: str, group_label: str) -> None:
    print(f"\n  ── {group_label}")
    print(f"     {url}")
    r = await backend.fetch(url)
    if not r.ok:
        print(f"     status={r.status} err={r.error}")
        return
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.html, "lxml")
    # Every /p/.../{PN}.html on this page
    seen = set()
    parts = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.match(r"/p/[^/]+/([^/]+)/\d+/([^.?]+)\.html", href)
        if not m:
            continue
        if href in seen:
            continue
        seen.add(href)
        name = m.group(1).replace("-", " ")
        pn = m.group(2)
        txt = a.get_text(" ", strip=True)[:60]
        parts.append((pn, name, txt))
    print(f"     {len(parts)} part links on this page")
    for pn, name, txt in parts[:25]:
        marker = "  <<<FOB" if pn.startswith(("95440", "95430", "95431", "95446", "95442")) else ""
        print(f"       pn={pn!r:25s}  name={name!r:55s}  label={txt!r:25s}{marker}")


async def main() -> None:
    backend = get_backend()
    try:
        for vehicle_url, base in VEHICLES:
            print("=" * 100)
            print(vehicle_url)
            for cat in ("Body-and-Trim", "Electric"):
                groups = await list_groups(backend, vehicle_url, cat)
                # All groups under this category — dump only the ones with names
                # that might host fobs/keys
                key_like_groups = [
                    (nm, url) for nm, url in groups
                    if any(k in nm for k in (
                        "KEY", "LOCKING", "LOCK", "RECEIVER", "RELAY",
                        "MODULE", "BURGLAR", "ANTI", "FOB", "TRANSMITTER",
                        "REMOTE", "ALARM",
                    ))
                ]
                print(f"\n  -- {cat} -- {len(groups)} groups, {len(key_like_groups)} candidate(s)")
                for nm, url in key_like_groups:
                    await dump_group(backend, url, f"{cat} > {nm}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
