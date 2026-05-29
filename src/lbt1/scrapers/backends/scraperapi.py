"""ScraperAPI backend — HTTP API with premium residential proxies + Cloudflare bypass.

Free tier: 5,000 credits one-time. Per-request cost:
  - Standard       :  1 credit
  - Premium        : 10 credits  (residential proxy)
  - Ultra premium  : 30 credits  (residential + stronger anti-bot)

Cloudflare-protected sites typically need at least Premium. We start with Premium
and escalate to Ultra Premium on detection failures (auto-retry pattern).

Docs: https://www.scraperapi.com/documentation/
"""

from __future__ import annotations

import asyncio
import logging
import random

import httpx

from lbt1.scrapers.backends.base import FetchResult, ScrapeBackend

log = logging.getLogger(__name__)

API_URL = "https://api.scraperapi.com/"
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=70.0, write=15.0, pool=10.0)
MAX_RETRIES = 3
RETRYABLE_STATUSES = {403, 408, 429, 500, 502, 503, 504}


class ScraperApiBackend(ScrapeBackend):
    """Routes fetches through ScraperAPI. Auto-escalates from premium to
    ultra_premium proxies on detection failures."""

    name = "scraperapi"

    def __init__(
        self,
        api_key: str,
        *,
        country_code: str = "us",
        render_js: bool = True,
        timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key:
            raise ValueError("ScraperApiBackend requires an API key")
        self.api_key = api_key
        self.country_code = country_code
        self.render_js = render_js
        self.timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def fetch(self, url: str) -> FetchResult:
        """Try premium first (10 credits). If detected, retry with ultra_premium
        (30 credits). Backs off between retries to spread proxy IPs."""
        # Each attempt escalates. Premium first (10 credits), then ultra
        # premium (30 credits) twice with fresh proxies for hostile sites.
        # Tuned for oempartsonline.com which 403s premium proxies routinely.
        attempts = [
            {"premium": "true"},
            {"ultra_premium": "true"},
            {"ultra_premium": "true", "session_number": "1"},  # force fresh proxy
        ]
        last_result: FetchResult | None = None
        for attempt_i, mode_params in enumerate(attempts, 1):
            result = await self._fetch_once(url, mode_params)

            # Success.
            if result.error is None and 200 <= result.status < 400:
                if attempt_i > 1:
                    log.info("ScraperAPI succeeded on attempt %d for %s", attempt_i, url)
                return result

            # Retryable failure?
            retry = (
                result.status in RETRYABLE_STATUSES
                or result.status == 0  # transport error
                or _looks_like_cloudflare_challenge(result.html)
            )
            last_result = result
            if not retry or attempt_i == len(attempts):
                return result

            delay = (1.5 * attempt_i) + random.uniform(0, 1.0)
            log.warning(
                "ScraperAPI attempt %d/%d failed for %s (status=%s) — retrying in %.1fs",
                attempt_i, len(attempts), url, result.status, delay,
            )
            await asyncio.sleep(delay)

        return last_result or FetchResult(status=0, final_url=url, html="", error="no result")

    async def _fetch_once(self, url: str, mode_params: dict[str, str]) -> FetchResult:
        params = {
            "api_key": self.api_key,
            "url": url,
            "country_code": self.country_code,
            "follow_redirect": "true",
            **mode_params,
        }
        if self.render_js:
            params["render"] = "true"

        try:
            response = await self._client.get(API_URL, params=params, timeout=self.timeout)
        except httpx.TimeoutException as exc:
            return FetchResult(status=0, final_url=url, html="", error=f"timeout: {exc}")
        except Exception as exc:  # noqa: BLE001
            return FetchResult(status=0, final_url=url, html="", error=f"transport: {exc}")

        # ScraperAPI returns the upstream HTTP status directly. Final URL is
        # in the `Sa-Final-Url` header (their convention).
        final_url = (
            response.headers.get("Sa-Final-Url")
            or response.headers.get("sa-final-url")
            or response.headers.get("X-Final-Url")
            or url
        )

        return FetchResult(
            status=response.status_code,
            final_url=final_url,
            html=response.text,
        )

    async def close(self) -> None:
        await self._client.aclose()


def _looks_like_cloudflare_challenge(html: str) -> bool:
    """Detect Cloudflare's interstitial 'Just a moment...' page so we can
    retry with a stronger proxy mode."""
    if not html:
        return False
    snippet = html[:600].lower()
    return (
        "just a moment" in snippet
        or "checking your browser" in snippet
        or "cf-browser-verification" in snippet
    )
