"""ScrapingAnt backend — HTTP API with browser-rendered residential-proxy fetches.

Pricing (as of 2026-05): residential + browser = 25 credits per fetch.
Free tier: 10,000 credits/month. Paid plans start at $19/mo for 50k credits.

Reliability notes from 2026-05 testing:
  - oempartsonline.com fingerprints ScrapingAnt's default browser on some
    requests. Retrying with a fresh proxy usually succeeds. The backend
    auto-retries 2x on HTTP 423 ("browser was detected").
  - Tight timeouts are essential — a small fraction of requests hang
    indefinitely without per-request limits.

Docs: https://docs.scrapingant.com/
"""

from __future__ import annotations

import asyncio
import logging
import random

import httpx

from lbt1.scrapers.backends.base import FetchResult, ScrapeBackend

log = logging.getLogger(__name__)

API_URL = "https://api.scrapingant.com/v2/general"
# Connect quickly; read can be slow because Cloudflare interstitial takes time.
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=15.0, pool=10.0)
MAX_RETRIES = 3  # initial attempt + 2 retries
# Status codes ScrapingAnt returns when its OWN browser was detected and we
# should try again with a fresh session.
RETRYABLE_API_STATUSES = {423, 502, 503, 504, 429}


class ScrapingAntBackend(ScrapeBackend):
    """Routes fetches through ScrapingAnt's managed browser with residential
    proxies. Bypasses Cloudflare's interstitial challenge reliably."""

    name = "scrapingant"

    def __init__(
        self,
        api_key: str,
        *,
        residential_proxy: bool = True,
        render_js: bool = True,
        timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key:
            raise ValueError("ScrapingAntBackend requires an API key")
        self.api_key = api_key
        self.residential_proxy = residential_proxy
        self.render_js = render_js
        self.timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def fetch(self, url: str) -> FetchResult:
        """Fetch with up to MAX_RETRIES attempts. Retries on:
          - HTTP 423 (ScrapingAnt: "browser was detected by target")
          - 5xx and 429 (transient API issues)
          - timeouts and transport errors

        A retry gets a fresh ScrapingAnt session, which usually rotates the
        proxy IP and browser fingerprint."""
        last_result: FetchResult | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            result = await self._fetch_once(url)

            # Successful upstream → done.
            if result.error is None and result.status < 400:
                if attempt > 1:
                    log.info("ScrapingAnt: %s succeeded on attempt %d", url, attempt)
                return result

            # Decide whether to retry.
            should_retry = (
                result.status in RETRYABLE_API_STATUSES
                or result.error is not None
            )
            last_result = result
            if not should_retry or attempt == MAX_RETRIES:
                return result

            # Backoff before next attempt: 1.5s, 4s with jitter.
            delay = (1.5 * attempt) + random.uniform(0, 1.0)
            log.warning(
                "ScrapingAnt attempt %d/%d failed for %s (status=%s err=%s) — "
                "retrying in %.1fs",
                attempt, MAX_RETRIES, url, result.status, result.error, delay,
            )
            await asyncio.sleep(delay)

        # Defensive — shouldn't reach here.
        return last_result or FetchResult(status=0, final_url=url, html="", error="no result")

    async def _fetch_once(self, url: str) -> FetchResult:
        # Empirically, oempartsonline.com fingerprints ScrapingAnt's default
        # browser. The combination that consistently bypasses Cloudflare on
        # the Kia/Hyundai dealer sites:
        #   - residential proxy (premium tier, 25 credits)
        #   - US proxy country (US-targeted site → US IP looks legitimate)
        #   - browser=true (JS-side redirect from /search → /v-…)
        #   - wait_for_selector forces ScrapingAnt to wait until the page is
        #     fully rendered post-Cloudflare-challenge.
        params = {
            "url": url,
            "x-api-key": self.api_key,
            "browser": "true" if self.render_js else "false",
            "wait_for_selector": "body",
        }
        if self.residential_proxy:
            params["proxy_type"] = "residential"
            params["proxy_country"] = "US"

        try:
            response = await self._client.get(API_URL, params=params, timeout=self.timeout)
        except httpx.TimeoutException as exc:
            return FetchResult(status=0, final_url=url, html="", error=f"timeout: {exc}")
        except Exception as exc:  # noqa: BLE001
            return FetchResult(status=0, final_url=url, html="", error=f"transport: {exc}")

        # The API itself returns 200 even when the upstream site returns 4xx/5xx;
        # the upstream status is inside the JSON body. A non-200 API status means
        # the API call itself failed (auth, quota, internal error).
        if response.status_code != 200:
            snippet = response.text[:300]
            return FetchResult(
                status=response.status_code,
                final_url=url,
                html="",
                error=f"ScrapingAnt API HTTP {response.status_code}: {snippet}",
            )

        try:
            data = response.json()
        except ValueError:
            # Sometimes ScrapingAnt returns raw HTML — treat as direct content.
            return FetchResult(
                status=200,
                final_url=url,
                html=response.text,
            )

        # JSON response shape: { content, status_code, url, cookies, ... }
        upstream_status = int(data.get("status_code", 200))
        final_url = data.get("url") or url
        html = data.get("content") or ""

        if upstream_status >= 400:
            log.warning(
                "ScrapingAnt: upstream returned %d for %s (title: %r)",
                upstream_status,
                url,
                _peek_title(html),
            )

        return FetchResult(status=upstream_status, final_url=final_url, html=html)

    async def close(self) -> None:
        await self._client.aclose()


def _peek_title(html: str) -> str:
    """Tiny helper for logging: grab the <title> for diagnostic context."""
    lo = html.lower()
    i = lo.find("<title")
    if i < 0:
        return ""
    j = lo.find(">", i)
    k = lo.find("</title>", j)
    if j < 0 or k < 0:
        return ""
    return html[j + 1 : k].strip()[:120]
