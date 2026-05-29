"""User insight: enter VIN + a clearly wrong key-fob PN, the dealer's
site says "this doesn't fit your vehicle — try these similar parts that
DO fit". Those alternatives are then VIN-verified by the dealer's own
fitment checker.

Test this technique on:
  - Revolution Parts (hyundai.oempartsonline.com) — does it expose
    "similar parts that fit"?
  - SimplePart (parts.hyundaicanada.com) — same question.

Approach:
  1. Pick a known-good vehicle URL (2017 Elantra has data).
  2. Visit the URL pattern for a wrong PN: /oem-parts/.../{WRONG_PN}.
  3. Check the response for fitment messages + alternative-part hints.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402


# Probe URLs to test:
URLS = [
    # ─── Revolution Parts ───────────────────────────────────────────────
    # Search by wrong PN
    "https://hyundai.oempartsonline.com/search?search_str=95440-XX9999",
    "https://kia.oempartsonline.com/search?search_str=95440-XX9999",
    # Search by valid-format PN on a wrong-trim vehicle (after navigating)
    # would happen via cookie; not easily reproducible without a session.
    #
    # Direct product page for a possibly-wrong PN URL pattern
    "https://hyundai.oempartsonline.com/oem-parts/hyundai-fob-smart-key-95440XX9999",
    "https://hyundai.oempartsonline.com/oem-parts/hyundai-fob-smart-key-95440S9000",  # Kia PN on Hyundai site
    # An OBVIOUSLY mismatched PN on a known-vehicle page
    # (Revolution Parts does fitment check on /oem-parts/ pages)

    # ─── SimplePart ─────────────────────────────────────────────────────
    # Search by wrong PN on parts.hyundaicanada.com
    "https://parts.hyundaicanada.com/productSearch.aspx?searchTerm=95440-XX9999",
    # Direct deep-link to a non-existent PN
    "https://parts.hyundaicanada.com/p/Hyundai_2017_Elantra/wrong-part/999999/95440XX9999.html",
    # Direct link to a valid PN ON THE WRONG VEHICLE (95440-S9000 is a
    # Telluride fob, visited under 2017 Elantra context)
    "https://parts.hyundaicanada.com/p/Hyundai_2017_Elantra/FOB-SMART-KEY/125888008/95440S9000.html",
]


async def probe(backend, url: str) -> None:
    print("=" * 100)
    print(url)
    r = await backend.fetch(url)
    print(f"  status={r.status}  final={r.final_url}  len={len(r.html or '')}")
    if r.error:
        print(f"  error: {r.error[:200]}")
        return

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.html, "lxml")
    title = (soup.title.string or "").strip() if soup.title else ""
    print(f"  title: {title[:160]}")

    # Look for fitment hints (positive or negative)
    text_lc = soup.get_text(" ", strip=True).lower()
    for needle in (
        "does not fit", "doesn't fit", "won't fit", "wrong vehicle",
        "this part fits", "fits your", "similar parts", "view similar",
        "related parts", "alternative parts", "compatible parts",
        "looking for similar", "no longer available",
        "fits the following", "applicable models", "fits these vehicles",
        "we found these", "this doesn't match",
    ):
        idx = text_lc.find(needle)
        if idx >= 0:
            ctx = text_lc[max(0, idx-100):idx+200]
            print(f"  [HINT {needle!r}]: …{ctx}…")

    # Look for "similar parts" UI elements
    for selector in (
        ".similar-parts", ".related-parts", ".alternative-parts",
        ".fitment-info", ".fit-vehicle", ".part-fits",
        ".product-fitment", ".recommend-products",
    ):
        els = soup.select(selector)
        if els:
            print(f"  [CSS {selector!r}]: {len(els)} elements")
            for el in els[:2]:
                print(f"    {el.get_text(' ', strip=True)[:300]!r}")

    # Sniff for any list of PNs in the response
    import re
    pns = re.findall(r"\b95[0-9]{3}[-A-Z0-9]{5,8}\b", r.html or "")
    pns = list(dict.fromkeys(pns))[:15]
    print(f"  PNs in response: {len(pns)}: {pns[:8]}")


async def main() -> None:
    backend = get_backend()
    try:
        for url in URLS:
            await probe(backend, url)
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
