"""Apify backend — uses the `apify/puppeteer-scraper` actor for managed JS rendering.

Free tier: $5/mo platform credit + free Apify Proxy datacenter group + free SERP.
Residential proxies cost $12.50/GB (NOT in free tier).

Pricing per fetch (with puppeteer-scraper):
  - ~$0.001 of compute per page load (~1 sec of browser time)
  - + Proxy bandwidth (datacenter: ~free, residential: paid)

So with $5/mo and datacenter proxies, the bottleneck is whether the dealer's
Cloudflare lets the datacenter IPs through. If not, escalate to residential
(paid). For testing, we start with datacenter to see if it works.

Docs: https://docs.apify.com/api/v2
"""

from __future__ import annotations

import json
import logging

import httpx

from lbt1.scrapers.backends.base import FetchResult, ScrapeBackend

log = logging.getLogger(__name__)

# This endpoint synchronously runs the actor and returns the dataset items.
# We use puppeteer-scraper which is Apify's official browser-based scraper.
ACTOR_RUN_URL = (
    "https://api.apify.com/v2/acts/apify~puppeteer-scraper/run-sync-get-dataset-items"
)
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=15.0, pool=10.0)

PAGE_FUNCTION = """
async function pageFunction(context) {
    const { request, page, log } = context;
    // Puppeteer API (NOT Playwright). The actor calls pageFunction AFTER page
    // load completes, so no extra waitForNavigation is needed. Optionally
    // wait a beat for late JS redirects (the /search → /v-* redirect is
    // server-side so this is just defensive).
    try {
        await page.waitForSelector('body', { timeout: 5000 });
    } catch (e) {}
    const html = await page.content();
    const finalUrl = page.url();
    let title = '';
    try { title = await page.title(); } catch (e) {}
    return { url: finalUrl, html: html, title: title, status: 200 };
}
"""


class ApifyBackend(ScrapeBackend):
    """Drives Apify's puppeteer-scraper actor for each fetch.

    The actor is a managed Puppeteer browser; we send it a URL list and a
    page function, and it returns rendered HTML + final URL.
    """

    name = "apify"

    def __init__(
        self,
        token: str,
        *,
        proxy_group: str = "RESIDENTIAL",  # try residential first; falls back to datacenter
        country: str = "US",
        timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ):
        if not token:
            raise ValueError("ApifyBackend requires a token")
        self.token = token
        self.proxy_group = proxy_group
        self.country = country
        self.timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def fetch(self, url: str) -> FetchResult:
        payload = {
            "startUrls": [{"url": url}],
            "pageFunction": PAGE_FUNCTION,
            "proxyConfiguration": {
                "useApifyProxy": True,
                "apifyProxyGroups": [self.proxy_group],
                "apifyProxyCountry": self.country,
            },
            "maxPagesPerCrawl": 1,
            "maxRequestRetries": 1,
            # Tell the actor not to follow links — we control which URLs to fetch.
            "linkSelector": "",
            "pseudoUrls": [],
            "headless": True,
            "useChrome": False,
            "ignoreCorsAndCsp": True,
            "ignoreSslErrors": True,
            "downloadMedia": False,
            "downloadCss": False,
        }

        try:
            response = await self._client.post(
                ACTOR_RUN_URL,
                params={"token": self.token},
                json=payload,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            return FetchResult(status=0, final_url=url, html="", error=f"timeout: {exc}")
        except Exception as exc:  # noqa: BLE001
            return FetchResult(status=0, final_url=url, html="", error=f"transport: {exc}")

        # Apify run-sync-get-dataset-items returns 200 (success) or 201 (created
        # — when the run completes and data is in the dataset). Both are success.
        if response.status_code not in (200, 201):
            snippet = response.text[:300]
            return FetchResult(
                status=response.status_code,
                final_url=url,
                html="",
                error=f"Apify API HTTP {response.status_code}: {snippet}",
            )

        try:
            items = response.json()
        except (ValueError, json.JSONDecodeError):
            return FetchResult(
                status=0, final_url=url, html=response.text,
                error="Apify returned non-JSON",
            )

        if not items:
            return FetchResult(
                status=0, final_url=url, html="",
                error="Apify actor returned empty dataset (browser failed?)",
            )

        # The actor may have flagged the run with #error=true if the pageFunction
        # threw, BUT if it still captured `url` and `html`, that's enough for us.
        item = items[0]
        html = item.get("html") or ""
        final_url = item.get("url") or url

        if not html:
            # Truly empty — surface the error
            err = item.get("errorMessage") or "Apify returned no HTML"
            return FetchResult(
                status=0, final_url=final_url, html="",
                error=f"Apify actor: {err}",
            )

        return FetchResult(
            status=int(item.get("status", 200)),
            final_url=final_url,
            html=html,
        )

    async def close(self) -> None:
        await self._client.aclose()
