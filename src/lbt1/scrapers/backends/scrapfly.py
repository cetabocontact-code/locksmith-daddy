"""ScrapFly backend — HTTP API with Anti-Scraping Protection (ASP) bypass.

Free tier: 1,000 credits/month (recurring). Each ASP+JS request costs ~21 credits
(5 premium proxy + 5 JS render + 10 ASP + 1 base). ~47 successful Cloudflare
bypasses per free month.

Docs: https://scrapfly.io/docs/scrape-api/getting-started
"""

from __future__ import annotations

import asyncio
import json
import logging
import random

import httpx

from lbt1.scrapers.backends.base import FetchResult, ScrapeBackend

log = logging.getLogger(__name__)

API_URL = "https://api.scrapfly.io/scrape"
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=70.0, write=15.0, pool=10.0)
MAX_RETRIES = 2  # Conservative — credits are precious
RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}


class ScrapFlyBackend(ScrapeBackend):
    """Routes fetches through ScrapFly's ASP (Anti-Scraping Protection) feature.
    Specifically engineered for Cloudflare-protected sites."""

    name = "scrapfly"

    def __init__(
        self,
        api_key: str,
        *,
        country: str = "us",
        asp: bool = True,
        render_js: bool = True,
        timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key:
            raise ValueError("ScrapFlyBackend requires an API key")
        self.api_key = api_key
        self.country = country
        self.asp = asp
        self.render_js = render_js
        self.timeout = timeout
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def fetch(self, url: str) -> FetchResult:
        last_result: FetchResult | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            result = await self._fetch_once(url)
            if result.error is None and 200 <= result.status < 400:
                if attempt > 1:
                    log.info("ScrapFly succeeded on attempt %d for %s", attempt, url)
                return result

            retry = (
                result.status in RETRYABLE_HTTP
                or result.status == 0
                or (200 <= result.status < 400 and _is_cf_challenge(result.html))
            )
            last_result = result
            if not retry or attempt == MAX_RETRIES:
                return result

            delay = (2.0 * attempt) + random.uniform(0, 1.0)
            log.warning(
                "ScrapFly attempt %d/%d failed for %s (status=%s err=%s) — retrying in %.1fs",
                attempt, MAX_RETRIES, url, result.status, result.error, delay,
            )
            await asyncio.sleep(delay)

        return last_result or FetchResult(status=0, final_url=url, html="", error="no result")

    async def get_credit_status(self) -> dict | None:
        """Hit the ScrapFly account endpoint and return credit status.
        Returns: {plan, used, limit, remaining, period_end, quota_reached}."""
        try:
            resp = await self._client.get(
                "https://api.scrapfly.io/account",
                params={"key": self.api_key},
                timeout=10.0,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            sub = data.get("subscription", {})
            scrape = sub.get("usage", {}).get("scrape", {})
            return {
                "plan": sub.get("plan_name"),
                "used": scrape.get("current"),
                "limit": scrape.get("limit"),
                "remaining": scrape.get("remaining"),
                "period_end": sub.get("period", {}).get("end"),
                "quota_reached": data.get("project", {}).get("quota_reached", False),
            }
        except Exception:
            return None

    async def _fetch_once(self, url: str) -> FetchResult:
        params = {
            "key": self.api_key,
            "url": url,
            "country": self.country,
            "asp": "true" if self.asp else "false",
            "render_js": "true" if self.render_js else "false",
            # Follow redirects so /search?VIN can resolve to /v-*
            "auto_scroll": "false",
        }

        try:
            response = await self._client.get(API_URL, params=params, timeout=self.timeout)
        except httpx.TimeoutException as exc:
            return FetchResult(status=0, final_url=url, html="", error=f"timeout: {exc}")
        except Exception as exc:  # noqa: BLE001
            return FetchResult(status=0, final_url=url, html="", error=f"transport: {exc}")

        # ScrapFly always returns JSON; upstream content is inside `result.content`.
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            return FetchResult(
                status=response.status_code,
                final_url=url,
                html=response.text,
                error=f"non-JSON response (HTTP {response.status_code})",
            )

        # API-level error (auth, quota, etc.)
        if response.status_code != 200 or data.get("result") is None:
            err_msg = data.get("message") or response.text[:200]
            return FetchResult(
                status=response.status_code,
                final_url=url,
                html="",
                error=f"ScrapFly API error: {err_msg}",
            )

        result_data = data["result"]
        upstream_status = int(result_data.get("status_code", 200))
        final_url = result_data.get("url") or url
        html = result_data.get("content") or ""

        return FetchResult(status=upstream_status, final_url=final_url, html=html)

    async def fetch_json_post(
        self,
        url: str,
        *,
        json_body: dict,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        """POST a JSON body to the target URL via ScrapFly's scrape API.

        Used by SimplepartDriver for ASMX endpoints like /wm.aspx/CreateVinLinks.
        Confirmed working 2026-05-28 against parts.hyundaicanada.com and
        parts.kia.com. Same retry semantics as GET — fetch_with_retry handles
        transient 403/timeout via the underlying retry loop, but POST goes
        through a single attempt here (the endpoint is fast and the retries
        usually aren't useful for these well-behaved official catalogs).
        """
        merged_headers = {
            "Content-Type": "application/json; charset=utf-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
        if headers:
            merged_headers.update(headers)

        params = {
            "key": self.api_key,
            "url": url,
            "country": self.country,
            "method": "POST",
            "asp": "true" if self.asp else "false",
            "render_js": "false",
        }
        for k, v in merged_headers.items():
            params[f"headers[{k}]"] = v

        body_bytes = json.dumps(json_body).encode("utf-8")
        try:
            response = await self._client.post(
                API_URL,
                params=params,
                content=body_bytes,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except httpx.TimeoutException as exc:
            return FetchResult(status=0, final_url=url, html="", error=f"timeout: {exc}")
        except Exception as exc:  # noqa: BLE001
            return FetchResult(status=0, final_url=url, html="", error=f"transport: {exc}")

        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            return FetchResult(
                status=response.status_code,
                final_url=url,
                html=response.text,
                error=f"non-JSON response (HTTP {response.status_code})",
            )

        if response.status_code != 200 or data.get("result") is None:
            err_msg = data.get("message") or response.text[:200]
            return FetchResult(
                status=response.status_code, final_url=url, html="",
                error=f"ScrapFly API error: {err_msg}",
            )

        result_data = data["result"]
        upstream_status = int(result_data.get("status_code", 200))
        final_url = result_data.get("url") or url
        content = result_data.get("content") or ""
        return FetchResult(status=upstream_status, final_url=final_url, html=content)

    async def close(self) -> None:
        await self._client.aclose()


def _is_cf_challenge(html: str) -> bool:
    if not html:
        return False
    snippet = html[:600].lower()
    return (
        "just a moment" in snippet
        or "checking your browser" in snippet
        or "cf-browser-verification" in snippet
    )
