"""One-off: see what hyundai.oempartsonline.com does when we hit /search?search_str=VIN."""

from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

VIN = "5NPD84LF1LH559355"  # 2020 Elantra
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1366, "height": 900}, user_agent=UA
        )
        page = await ctx.new_page()
        url = f"https://hyundai.oempartsonline.com/search?search_str={VIN}"
        print(f"GET {url}")
        await page.goto(url, wait_until="domcontentloaded")
        print(f"  landed at: {page.url}")
        print(f"  title: {await page.title()}")

        # Try a couple of likely category URL patterns based on Kia's format.
        if "/v-" in page.url:
            vehicle = page.url.split("#")[0].rstrip("/")
            for trial in (
                f"{vehicle}/electrical--keyless-entry-components",
                f"{vehicle}/electrical--keyless-entry",
                f"{vehicle}/electrical--transmitter",
            ):
                print(f"\nGET {trial}")
                r = await page.goto(trial, wait_until="domcontentloaded")
                print(f"  status: {r.status if r else '?'}  url: {page.url}")
                print(f"  title:  {await page.title()}")
        else:
            print("  No /v-* redirect — page is probably a trim chooser or 404.")
            links = await page.evaluate(
                "() => Array.from(document.querySelectorAll('a[data-trim], a.recent-car, a[href*=\"/v-\"]')).slice(0,10).map(a => ({text: a.innerText.trim().slice(0,80), href: a.href}))"
            )
            for ln in links:
                print(f"  link: {ln['text']!r} -> {ln['href']}")

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
