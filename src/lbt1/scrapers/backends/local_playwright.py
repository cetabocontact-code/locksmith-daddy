"""Local Chromium backend — for offline development and zero-cost testing.

Will get blocked by Cloudflare on protected dealer sites (that's why the
ScrapingAnt and BrightData backends exist). Kept as a fallback so the code
runs end-to-end without an API key.
"""

from __future__ import annotations

import logging

from playwright.async_api import async_playwright

from lbt1.scrapers.backends.base import FetchResult, ScrapeBackend

log = logging.getLogger(__name__)


class LocalPlaywrightBackend(ScrapeBackend):
    """Spins up a local Chromium for each fetch. Slow and gets blocked by
    Cloudflare, but useful for development against non-protected pages."""

    name = "local_playwright"

    def __init__(self, *, headless: bool = True, timeout_ms: int = 30_000):
        self.headless = headless
        self.timeout_ms = timeout_ms

    async def fetch(self, url: str) -> FetchResult:
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=self.headless)
                try:
                    ctx = await browser.new_context(
                        viewport={"width": 1366, "height": 900},
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/127.0.0.0 Safari/537.36"
                        ),
                    )
                    page = await ctx.new_page()
                    response = await page.goto(
                        url, wait_until="domcontentloaded", timeout=self.timeout_ms
                    )
                    status = response.status if response else 0
                    final_url = page.url
                    html = await page.content()
                    return FetchResult(status=status, final_url=final_url, html=html)
                finally:
                    await browser.close()
        except Exception as exc:  # noqa: BLE001
            return FetchResult(status=0, final_url=url, html="", error=f"playwright: {exc}")
