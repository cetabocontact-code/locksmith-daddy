"""Use the scraper's actual session() context manager, but skip all the
helper steps (wait_for_url, emit, dismiss, screenshot). Find out whether the
bug is in session setup or in the helper logic on top of it."""

from __future__ import annotations

import asyncio
from pathlib import Path

from lbt1.scrapers.kia import KiaOempartsDriver

SEARCH = "https://kia.oempartsonline.com/search?search_str=5XYK6CDF8TG390982"
CATEGORY = (
    "https://kia.oempartsonline.com/v-2026-kia-sportage--x-line--2-5l-l4-gas/"
    "electrical--keyless-entry-components"
)


async def variant(label: str, prefn) -> None:
    print(f"\n=== {label} ===")
    driver = KiaOempartsDriver(headless=True)
    async with driver.session() as page:
        r1 = await page.goto(SEARCH, wait_until="domcontentloaded")
        print(f"  search -> status {r1.status if r1 else '?'} | at {page.url}")
        if prefn is not None:
            await prefn(page)
        r2 = await page.goto(CATEGORY, wait_until="domcontentloaded")
        print(f"  category -> status {r2.status if r2 else '?'} | title {(await page.title())!r}")


CAT2 = (
    "https://kia.oempartsonline.com/v-2026-kia-sportage--x-line--2-5l-l4-gas/"
    "electrical--anti-theft-system"
)
CAT3 = (
    "https://kia.oempartsonline.com/v-2026-kia-sportage--x-line--2-5l-l4-gas/"
    "electrical--electrical-components"
)


async def multi_nav(label: str, harvest_between: bool) -> None:
    print(f"\n=== {label} ===")
    driver = KiaOempartsDriver(headless=True)
    async with driver.session() as page:
        for i, url in enumerate([SEARCH, CATEGORY, CAT2, CAT3]):
            r = await page.goto(url, wait_until="domcontentloaded")
            status = r.status if r else "?"
            title = (await page.title())[:60]
            print(f"  [{i}] status {status} | {title!r}")
            if harvest_between and i >= 1:
                # Simulate harvest: query DOM for any links
                count = await page.locator("a").count()
                print(f"      (probed {count} links)")


async def main() -> None:
    await multi_nav("M1) 4 raw navigations, no DOM probing", harvest_between=False)
    await multi_nav("M2) 4 navigations with DOM probing", harvest_between=True)


if __name__ == "__main__":
    asyncio.run(main())
