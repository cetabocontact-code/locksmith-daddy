"""Bright Data Web Unlocker backend — production-grade Cloudflare bypass.

Pricing (as of 2026-05): ~$1.50 per 1,000 successful requests. Best
economics at high volume (>10k/mo).

This is the production target. Wired in but inactive until the user has a
verified Bright Data account and a Web Unlocker zone configured.

Docs: https://docs.brightdata.com/scraping-automation/web-unlocker/
"""

from __future__ import annotations

import logging

import httpx

from lbt1.scrapers.backends.base import FetchResult, ScrapeBackend

log = logging.getLogger(__name__)

API_URL = "https://api.brightdata.com/request"
DEFAULT_TIMEOUT = 90.0


class BrightDataWebUnlockerBackend(ScrapeBackend):
    """Routes fetches through Bright Data's Web Unlocker zone."""

    name = "brightdata"

    def __init__(
        self,
        api_key: str,
        zone: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key:
            raise ValueError("BrightDataWebUnlockerBackend requires an API key")
        if not zone:
            raise ValueError("BrightDataWebUnlockerBackend requires a zone name")
        self.api_key = api_key
        self.zone = zone
        self.timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def fetch(self, url: str) -> FetchResult:
        payload = {
            "zone": self.zone,
            "url": url,
            "format": "raw",
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._client.post(
                API_URL, json=payload, headers=headers, timeout=self.timeout
            )
        except httpx.TimeoutException as exc:
            return FetchResult(status=0, final_url=url, html="", error=f"timeout: {exc}")
        except Exception as exc:  # noqa: BLE001
            return FetchResult(status=0, final_url=url, html="", error=f"transport: {exc}")

        # Bright Data Web Unlocker returns the raw HTML body with the original
        # upstream HTTP status. Final URL is reported via the `x-final-url`
        # response header.
        final_url = response.headers.get("x-final-url") or url
        return FetchResult(
            status=response.status_code,
            final_url=final_url,
            html=response.text,
        )

    async def close(self) -> None:
        await self._client.aclose()
