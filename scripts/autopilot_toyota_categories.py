"""Autopilot AM investigation: find where Toyota files key fobs in their
Revolution Parts catalog. Yesterday's probe confirmed they're NOT under
electrical/keyless-entry-components (that page only has receivers + antennas
+ modules for 2024 Camry SE).

Approach:
  1. Fetch a 2024 Toyota Camry vehicle landing page.
  2. List ALL category sub-paths exposed (find body/locks, accessories, etc).
  3. For each candidate category that contains "key", "lock", "fob", "ignition",
     fetch it and look for parts whose PN starts with 89070/89904/89742 (Toyota
     key fob families).
  4. Output the actual category slugs where fobs live, ready to wire into
     ToyotaOempartsDriver.category_paths.

Cost target: ~$0.15 (3-5 category fetches).
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

VEHICLE = "https://toyota.oempartsonline.com/v-2024-toyota-camry--se--2-5l-l4-gas"
TOYOTA_KEY_PN_PREFIXES = ("89070", "89904", "89742", "89745", "69515", "69058")


async def main() -> None:
    backend = get_backend()
    try:
        # Step 1: vehicle landing page
        print("=" * 90)
        print(f"VEHICLE PAGE: {VEHICLE}")
        r = await backend.fetch(VEHICLE)
        print(f"  status={r.status}  len={len(r.html or '')}")
        if not r.ok:
            print(f"  fetch failed: {r.error}")
            return
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.html, "lxml")

        # Find every category-shape sub-path: /v-{slug}/{section}--{slug}
        seen = set()
        candidates = []
        path_prefix = VEHICLE.replace("https://toyota.oempartsonline.com", "")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if path_prefix in href and "--" in href.split("/")[-1]:
                if href in seen:
                    continue
                seen.add(href)
                # Last path segment = {section}--{slug}
                last = href.split("/")[-1].lower()
                txt = a.get_text(" ", strip=True)[:60]
                # Score by key-relevance keywords
                if any(kw in last + " " + txt.lower() for kw in (
                    "key", "lock", "fob", "ignition", "remote", "anti-theft",
                    "smart", "hardware",
                )):
                    candidates.append((last, href, txt))
        print(f"\n  Key-related category candidates: {len(candidates)}")
        for last, href, txt in candidates[:30]:
            print(f"    {txt[:40]:40s}  {last}")

        # Step 2: fetch each candidate, look for Toyota key PNs
        print("\n" + "=" * 90)
        print("DRILL INTO EACH CANDIDATE")
        print("=" * 90)
        winners = []
        for last, href, txt in candidates[:8]:  # cap to control cost
            full = "https://toyota.oempartsonline.com" + href if href.startswith("/") else href
            print(f"\n— {last}")
            rr = await backend.fetch(full)
            if not rr.ok:
                print(f"    fetch failed: status={rr.status}")
                continue
            s2 = BeautifulSoup(rr.html, "lxml")
            cards = s2.select(".marketplace-info-col")
            print(f"    cards: {len(cards)}")
            key_pns_found = []
            for c in cards:
                pn_el = c.select_one(".product-partnum a")
                name_el = c.select_one(".product-title a")
                if not pn_el:
                    continue
                pn = pn_el.get_text(strip=True)
                name = name_el.get_text(strip=True) if name_el else ""
                # Is this a Toyota key PN family?
                pn_clean = pn.replace("-", "").lower()
                if any(pn_clean.startswith(p) for p in TOYOTA_KEY_PN_PREFIXES):
                    key_pns_found.append((pn, name))
            if key_pns_found:
                print(f"    >>> {len(key_pns_found)} TOYOTA KEY FOB PN(s) FOUND")
                for pn, name in key_pns_found[:5]:
                    print(f"        {pn}  {name}")
                # Extract section/slug from URL: /v-.../{section}--{slug}
                m = re.search(r"/([\w-]+)--([\w-]+)$", href)
                if m:
                    winners.append((m.group(1), m.group(2), len(key_pns_found)))

        # Step 3: print the actionable category_paths for the driver
        print("\n" + "=" * 90)
        print("PROPOSED Toyota category_paths (replace in toyota.py):")
        print("=" * 90)
        if winners:
            print("category_paths = (")
            for section, slug, n in winners:
                print(f"    ({section!r}, {slug!r}),  # {n} key PN(s) found here")
            print(")")
        else:
            print("(no fob PNs found in probed categories — need to expand candidates)")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
