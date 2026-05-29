"""Two probes:
  1) accessories-keychain--keychain on 2026 SEL Sport — does this contain
     the smart-key/transmitter parts the dealer hasn't filed under
     electrical/keyless-entry-components?
  2) 2025 Elantra SEL Sport electrical--keyless-entry-components — confirm
     it has the parts we'd expect (so year-fallback is viable if 2026 stays
     empty).
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
    "https://hyundai.oempartsonline.com/v-2026-hyundai-elantra--sel-sport--2-0l-l4-gas/accessories-keychain--keychain",
    "https://www.hyundaioempart.com/v-2026-hyundai-elantra--sel-sport--2-0l-l4-gas/accessories-keychain--keychain",
    "https://hyundai.oempartsonline.com/v-2025-hyundai-elantra--sel-sport--2-0l-l4-gas/electrical--keyless-entry-components",
    "https://hyundai.oempartsonline.com/v-2025-hyundai-elantra--sel-sport--2-0l-l4-gas/electrical--anti-theft-system",
    # And ALL category slugs that exist on 2025 SEL Sport — to discover the
    # actual category for keys/transmitters
    "https://hyundai.oempartsonline.com/v-2025-hyundai-elantra--sel-sport--2-0l-l4-gas",
]


async def main() -> None:
    backend = get_backend()
    try:
        for url in URLS:
            print("=" * 100)
            print(url)
            r = await backend.fetch(url)
            print(f"  status={r.status}  final={r.final_url}  htmllen={len(r.html or '')}")
            if r.error:
                print(f"  error={r.error[:200]}")
                continue
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.html, "lxml")
            title = (soup.title.string or "").strip() if soup.title else ""
            print(f"  title: {title[:160]}")

            cards = soup.select(".marketplace-info-col")
            print(f"  .marketplace-info-col cards: {len(cards)}")
            for i, c in enumerate(cards[:15]):
                name_el = c.select_one(".product-title a") or c.select_one(".product-title")
                pn_el = c.select_one(".product-partnum a") or c.select_one(".product-partnum")
                desc_el = c.select_one(".contextual_description")
                name = name_el.get_text(strip=True) if name_el else None
                pn = pn_el.get_text(strip=True) if pn_el else None
                desc = desc_el.get_text(strip=True) if desc_el else None
                print(f"    [{i:2d}] name={name!r}")
                print(f"           pn={pn!r}  desc={desc!r}")

            # For the bare trim page, list all KEY-related sub-paths
            if url.endswith("--sel-sport--2-0l-l4-gas") or url.endswith("--sel-sport--2-0l-l4-gas/"):
                print(f"  Looking for ANY sub-path with key/keyless/remote/transmitter/fob/anti-theft/electrical:")
                links = soup.find_all("a", href=True)
                seen = set()
                for a in links:
                    href = a["href"]
                    href_lc = href.lower()
                    if any(k in href_lc for k in (
                        "keyless", "transmitter", "remote", "fob", "smart-key",
                        "electrical--", "anti-theft", "ignition",
                    )):
                        if href in seen:
                            continue
                        seen.add(href)
                        txt = a.get_text(" ", strip=True)[:80]
                        print(f"    {txt!r:55s} -> {href}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
