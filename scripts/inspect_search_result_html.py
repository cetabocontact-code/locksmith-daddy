"""Dump what /search?search_str={VIN} actually returns on the failing VIN —
specifically the candidate /v- links the scorer chooses from. We saw the
scorer pick `--sel-sport-premium--2-0l-l4-gas` which doesn't exist on the
dealer's chooser page, meaning the search result HTML itself contains that
link (and the dealer silently 301s back to the trim chooser when you visit
it). Confirm + capture so we can fix the scorer.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

VIN = "KMHLS4DG5TU123100"
URLS = [
    f"https://hyundai.oempartsonline.com/search?search_str={VIN}",
    f"https://www.hyundaioempart.com/search?search_str={VIN}",
]


async def main() -> None:
    backend = get_backend()
    try:
        for url in URLS:
            print("=" * 100)
            print(url)
            r = await backend.fetch(url)
            print(f"  status={r.status}  final={r.final_url}")
            if r.error:
                print(f"  error={r.error[:200]}")
                continue

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.html, "lxml")
            title = (soup.title.string or "").strip() if soup.title else ""
            print(f"  title: {title[:160]}")

            # Look at all /v- candidate links plus their data attrs
            links = soup.select("a[data-trim], a[href*='/v-']")
            seen = set()
            print(f"  Candidate links: {len(links)}")
            for el in links:
                href = el.get("href", "")
                if href in seen:
                    continue
                seen.add(href)
                if "/v-" not in href:
                    continue
                attrs = {k: v for k, v in el.attrs.items() if isinstance(v, str) and k.startswith(("data-", "title", "href"))}
                txt = el.get_text(" ", strip=True)[:60]
                print(f"    {txt!r:50s}")
                print(f"        href: {href}")
                print(f"        attrs: {attrs}")

            # ALSO dump any element in the page that contains "sel-sport-premium" or "SEL Sport Premium"
            print()
            print(f"  Hits for 'sel-sport-premium' anywhere in HTML:")
            html_lc = (r.html or "").lower()
            idx = 0
            count = 0
            while True:
                idx = html_lc.find("sel-sport-premium", idx)
                if idx < 0 or count >= 5:
                    break
                snippet = r.html[max(0, idx-80):idx+120].replace("\n", " ")
                print(f"    @{idx}: …{snippet}…")
                idx += 1
                count += 1
            print(f"  Hits for 'SEL Sport Premium' (case-sensitive text):")
            idx = 0
            count = 0
            while True:
                idx = (r.html or "").find("SEL Sport Premium", idx)
                if idx < 0 or count >= 5:
                    break
                snippet = r.html[max(0, idx-80):idx+120].replace("\n", " ")
                print(f"    @{idx}: …{snippet}…")
                idx += 1
                count += 1
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
