"""Reproduce my scraper's session() context settings exactly, then run the
inspector's 2-step flow (search ->category). Identifies which context option
is causing Cloudflare to flag the session."""

from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)

SEARCH = "https://kia.oempartsonline.com/search?search_str=5XYK6CDF8TG390982"
CATEGORY = (
    "https://kia.oempartsonline.com/v-2026-kia-sportage--x-line--2-5l-l4-gas/"
    "electrical--keyless-entry-components"
)


async def try_variant(label: str, **context_kwargs) -> None:
    print(f"\n=== {label} ===")
    print(f"  context kwargs: {list(context_kwargs.keys())}")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(**context_kwargs)
        page = await ctx.new_page()
        r1 = await page.goto(SEARCH, wait_until="domcontentloaded")
        print(f"  search ->status {r1.status if r1 else '?'} | now at {page.url}")
        r2 = await page.goto(CATEGORY, wait_until="domcontentloaded")
        print(f"  category ->status {r2.status if r2 else '?'} | title {(await page.title())!r}")
        await ctx.close()
        await browser.close()


async def main() -> None:
    base = {"viewport": {"width": 1366, "height": 900}, "user_agent": UA}

    await try_variant("MINIMAL (matches working inspector)", **base)
    await try_variant("+ locale en-US", **base, locale="en-US")
    await try_variant("+ timezone America/New_York", **base, timezone_id="America/New_York")
    await try_variant(
        "+ locale + timezone (matches scraper)",
        **base,
        locale="en-US",
        timezone_id="America/New_York",
    )


if __name__ == "__main__":
    asyncio.run(main())
