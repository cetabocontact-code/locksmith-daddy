"""Test whether category URLs work in a clean session (no prior navigation)
or require the vehicle landing page to be visited first."""

from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

VEHICLE_URL = "https://kia.oempartsonline.com/v-2026-kia-sportage--x-line--2-5l-l4-gas"
CATEGORY_URL = f"{VEHICLE_URL}/electrical--keyless-entry-components"


async def test(label: str, urls: list[str]) -> None:
    print(f"\n=== {label} ===")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/127.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        for url in urls:
            response = await page.goto(url, wait_until="domcontentloaded")
            status = response.status if response else "?"
            title = await page.title()
            print(f"  [{status}] {url[:80]}")
            print(f"        title: {title!r}")
            print(f"        landed at: {page.url}")
        await context.close()
        await browser.close()


async def main() -> None:
    await test("A) Direct to category, no prior navigation", [CATEGORY_URL])
    await test("B) Vehicle landing, then category", [VEHICLE_URL, CATEGORY_URL])
    await test(
        "C) /search redirect, then category",
        [
            "https://kia.oempartsonline.com/search?search_str=5XYK6CDF8TG390982",
            CATEGORY_URL,
        ],
    )


if __name__ == "__main__":
    asyncio.run(main())
