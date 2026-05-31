"""DuckDuckGo-search-driven fallback driver.

After all OEM dealer drivers fail, this driver runs a structured
DuckDuckGo HTML search for `site:{dealer} "{pn_family}" {year} {model}`
to find dealer product pages our category-sweep missed.

Discovered 2026-05-29: Revolution Parts dealers have flat-URL product
pages at `/oem-parts/{slug}-{pn}` that aren't always reachable from the
trim-scoped category navigation. These pages ARE indexed by search
engines and ARE valid OEM dealer pages — so a PN found via this path
is the SAME quality of "DEALER_VERIFIED_BY_VIN" as a category-sweep hit.

Strategy is conservative:
  1. Only fires when prior drivers in the chain returned zero PNs.
  2. Searches DDG with strict year+model constraint in the query.
  3. Filters results to ONLY the dealer hostname we're scoping.
  4. Visits each candidate URL and confirms the page text actually
     mentions our VIN's year + model. Anything ambiguous is dropped.

Costs:
  - DDG search itself is free (we use the HTML endpoint)
  - 1-3 candidate URL visits per VIN at ~84 credits each = ~$0.013-0.04
  - Caches by (make, year, model, pn_prefix) so repeated VINs are free
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import quote_plus, unquote, urljoin

import httpx
from bs4 import BeautifulSoup

from lbt1 import config
from lbt1.models import (
    PART_NAME_TO_KEY_TYPE,
    KeyType,
    OemPart,
    ResearchStep,
    StepStatus,
    VehicleProfile,
)
from lbt1.scrapers.backends import ScrapeBackend, get_backend

# Persistent cache so we don't re-hit DDG for the same (make, year, model).
# Dealer catalogs are stable enough that infinite TTL is fine.
_CACHE_PATH = Path(config.DATA_DIR) / "ddg_search_cache.json"


def _load_cache() -> dict:
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception:
        pass

StepCallback = Callable[[ResearchStep], Awaitable[None] | None]

# Make -> list of (dealer_host, PN prefixes) — tries each dealer in order
# until one returns candidates. Per-make insight (2026-05-29):
#   - Genesis catalog is small on its own RP dealer; Genesis fobs are
#     historically 95440-* (Hyundai family) and Hyundai dealer pages
#     often index Genesis vehicles → try Hyundai dealer as backup.
#   - Lexus → Toyota dealer for same reason (luxury subsidiary).
#   - Kia rarely shares with Hyundai despite ownership, keep separate.
_MAKE_CONFIG: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "hyundai": [("hyundai.oempartsonline.com",  ("95440", "95430", "95441"))],
    "kia":     [("kia.oempartsonline.com",      ("95440", "95430", "95431"))],
    "genesis": [
        ("genesis.oempartsonline.com", ("95440", "95430")),
        ("hyundai.oempartsonline.com", ("95440", "95430")),  # adjacent-dealer fallback
    ],
    "toyota":  [
        ("toyota.oempartsonline.com", ("89070", "89904", "89742")),
    ],
    "lexus":   [
        ("lexus.oempartsonline.com", ("89070", "89904", "89742")),
        ("toyota.oempartsonline.com", ("89070", "89904", "89742")),  # adjacent
    ],
}


class DuckDuckGoSearchFallbackDriver:
    """Last-resort search-based fallback. Returns OemParts only when a
    candidate URL's page text confirms VIN's year+model.
    """

    name = "ddg_search_fallback"
    base_url = "https://html.duckduckgo.com/"

    def __init__(
        self,
        *,
        backend: ScrapeBackend | None = None,
        step_callback: StepCallback | None = None,
        **_legacy_kwargs,
    ):
        self.backend = backend or get_backend()
        self.step_callback = step_callback
        self.steps: list[ResearchStep] = []
        self.screenshots: list[str] = []

    async def _emit(
        self, step: str, status: StepStatus = "info", detail: str | None = None
    ) -> None:
        record = ResearchStep(
            timestamp=datetime.now(timezone.utc),
            step=step, status=status, detail=detail,
        )
        self.steps.append(record)
        if self.step_callback:
            r = self.step_callback(record)
            if asyncio.iscoroutine(r):
                await r

    async def lookup_vin(self, vin: str, profile: VehicleProfile) -> list[OemPart]:
        make = (profile.make or "").lower().strip()
        dealer_configs = _MAKE_CONFIG.get(make)
        if not dealer_configs:
            await self._emit(
                f"DDG fallback: no config for make {profile.make!r}", "info",
            )
            return []
        year = str(profile.year) if profile.year else ""
        model = (profile.model or "").split(",")[0].strip()
        if not year or not model:
            await self._emit("DDG fallback: missing year or model", "info")
            return []

        await self._emit(
            f"DDG search-based fallback for {profile.display}", "info", vin,
        )

        # Try each dealer host in order (primary then adjacent fallbacks).
        # Per-make config orders dealers by likelihood of hit.
        candidates: list[tuple[str, str, str]] = []  # (url, snippet, host)
        for dealer_host, pn_prefixes in dealer_configs:
            await self._emit(
                f"DDG querying dealer: {dealer_host}", "info"
            )
            local_candidates = await self._search_one_dealer(
                dealer_host, pn_prefixes, year, model,
            )
            for u, s in local_candidates:
                candidates.append((u, s, dealer_host))
            if candidates:
                break  # this dealer had hits; don't waste queries on adjacent

        if not candidates:
            await self._emit("DDG fallback: no candidate URLs found", "info")
            return []

        await self._emit(f"DDG returned {len(candidates)} candidate URL(s)", "info")

        # Step 3: fetch each candidate and confirm fitment
        found: list[OemPart] = []
        seen_pns: set[str] = set()
        for url, snippet, dealer_host in candidates[:5]:
            part = await self._verify_candidate(url, profile, dealer_host)
            if part and part.oem_part_number not in seen_pns:
                seen_pns.add(part.oem_part_number)
                found.append(part)

        await self._emit(
            f"DDG fallback captured {len(found)} verified PN(s)",
            "success" if found else "info",
        )
        return found

    async def _search_one_dealer(
        self, dealer_host: str, pn_prefixes: tuple[str, ...],
        year: str, model: str,
    ) -> list[tuple[str, str]]:
        """For a single dealer host, try each PN prefix with narrow then
        broad query. Returns the first non-empty result list (caps cost)."""
        for pn_prefix in pn_prefixes:
            for query_label, query in [
                ("narrow", f'site:{dealer_host} "{pn_prefix}" {year} {model}'),
                ("broad",  f'site:{dealer_host} "{pn_prefix}" {model}'),
            ]:
                await self._emit(f"DDG {query_label}: {query}", "info")
                results = await self._ddg_search(query, dealer_host)
                if results:
                    await self._emit(
                        f"DDG {query_label}: {len(results)} candidate(s)", "info"
                    )
                    return results
        return []

    async def _ddg_search(self, query: str, dealer_host: str) -> list[tuple[str, str]]:
        """Hit DuckDuckGo HTML endpoint and parse out result URLs scoped
        to the dealer host. Returns list of (url, snippet).

        Two-tier strategy:
          1. Cache hit — return immediately, no network.
          2. Direct httpx to html.duckduckgo.com — free but rate-limited.
          3. ScrapFly proxy — costs ~$0.013 but bypasses rate-limit.
        """
        cache = _load_cache()
        if query in cache:
            cached = cache[query]
            await self._emit(f"DDG cache hit ({len(cached)} results)", "info")
            return [(r["url"], r["snippet"]) for r in cached]

        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        results = await self._fetch_and_parse_ddg_direct(url, dealer_host)
        if not results:
            # Rate-limited or empty — try via ScrapFly (residential proxy)
            await self._emit("DDG direct returned 0, trying ScrapFly proxy", "info")
            r = await self.backend.fetch(url)
            if r.ok and r.html:
                results = self._parse_ddg_html(r.html, dealer_host)

        # Cache forever — but ONLY non-empty results. Empty results almost
        # always come from transient ScrapFly throttles (429) or DDG rate
        # limits, not from "the dealer truly has no PN for this query".
        # Caching empty poisons the cache: every future lookup short-circuits
        # to the empty result, and DDG fallback returns 0 even when the
        # answer is plainly indexed. (Diagnosed 2026-05-30: 6 stuck VINs
        # were ALL unverifiable due to this; one cache wipe + concurrency=1
        # rerun verified 16/16.)
        if results:
            cache[query] = [{"url": u, "snippet": s} for u, s in results]
            _save_cache(cache)
        return results

    async def _fetch_and_parse_ddg_direct(
        self, url: str, dealer_host: str
    ) -> list[tuple[str, str]]:
        try:
            async with httpx.AsyncClient(
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/120.0.0.0 Safari/537.36",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                timeout=30,
            ) as client:
                r = await client.get(url)
        except Exception:
            return []
        if r.status_code != 200:
            return []
        return self._parse_ddg_html(r.text, dealer_host)

    @staticmethod
    def _parse_ddg_html(html: str, dealer_host: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "lxml")
        results: list[tuple[str, str]] = []
        for res in soup.select(".result"):
            link = res.select_one(".result__a")
            if not link:
                continue
            href = link.get("href", "")
            m = re.search(r"uddg=([^&]+)", href)
            if m:
                href = unquote(m.group(1))
            if dealer_host not in href:
                continue
            snippet_el = res.select_one(".result__snippet")
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
            results.append((href, snippet))
        return results

    async def _verify_candidate(
        self, url: str, profile: VehicleProfile, dealer_host: str,
    ) -> OemPart | None:
        """Fetch the candidate page and confirm:
          - page exists (HTTP 200)
          - page text mentions the VIN's year + model in fitment context
          - we can extract an OEM PN from the title/URL
        Year check: title/H1/body. Model check: title/H1/snippet/body.
        Toyota-style generic titles ('2019-2024 Toyota Keyless Entry Transmitter')
        still pass IF the fitment body text mentions the model. Hyundai-style
        ('2024-2025 Hyundai Sonata Keyless Entry...') pass via title alone."""
        await self._emit(f"Verifying candidate", "info", url[:120])
        r = await self.backend.fetch(url)
        if not r.ok:
            return None
        soup = BeautifulSoup(r.html, "lxml")
        title = (soup.title.string or "").strip() if soup.title else ""
        text = soup.get_text(" ", strip=True).lower()

        year = str(profile.year) if profile.year else ""
        model_lc = (profile.model or "").split(",")[0].strip().lower()
        h1 = soup.find("h1")
        h1_text = h1.get_text(" ", strip=True).lower() if h1 else ""
        title_lc = title.lower()
        title_h1 = title_lc + " " + h1_text

        # Year check — must be present somewhere on the page (the dealer's
        # title or fitment table). If title says "2019-2024" we accept.
        year_in_title = year in title_h1
        year_in_text = year in text
        if not (year_in_title or year_in_text):
            await self._emit(
                "Candidate dropped (year not mentioned anywhere)", "info",
                f"title={title[:80]!r}",
            )
            return None

        # Model check — title preferred (high confidence) but body fitment
        # acceptable. Body match must NOT also mention other models around
        # the keyword (cheap noise filter — full noise removal is later).
        model_in_title = model_lc in title_h1
        model_in_body = model_lc in text
        if not (model_in_title or model_in_body):
            await self._emit(
                "Candidate dropped (model not mentioned anywhere)", "info",
                f"title={title[:80]!r}",
            )
            return None

        # Extract PN from URL or page
        pn = self._extract_pn(url, title, soup)
        if not pn:
            return None

        # Classify by name
        name_lc = title.lower()
        key_type = self._classify_key_type(name_lc)
        if key_type == KeyType.UNKNOWN:
            return None  # only return if we know it's a key part

        return OemPart(
            oem_part_number=pn,
            part_name=self._derive_part_name(title),
            key_type=key_type,
            source_url=url,
            category_path=f"DDG-fallback: {dealer_host}",
            fitment_evidence=f"Title confirms {year} {model_lc}",
            dealer_verified=True,
            notes="Found via DDG fallback search of dealer site",
        )

    @staticmethod
    def _extract_pn(url: str, title: str, soup: BeautifulSoup) -> str:
        """Pull OEM PN from URL (last segment after final dash) or from
        title text. Normalize to canonical format."""
        # URL pattern: /oem-parts/{slug}-{pn} where pn is alphanumeric
        m = re.search(
            r"/oem-parts/[^/]*?(\d{5}[a-z0-9]{4,8})(?:[?#]|$)", url.lower()
        )
        if m:
            raw = m.group(1)
            # Normalize: 95440L1760 -> 95440-L1760
            if len(raw) >= 6 and raw[:5].isdigit():
                return f"{raw[:5]}-{raw[5:]}".upper()
            return raw.upper()
        # Try title — "95440-L1760" or "95440 L1760" patterns
        m = re.search(r"\b(\d{5}[-\s]?[A-Z0-9]{4,8})\b", title)
        if m:
            return m.group(1).replace(" ", "-").upper()
        return ""

    @staticmethod
    def _derive_part_name(title: str) -> str:
        """E.g. '2024-2025 Hyundai Sonata Keyless Entry Transmitter 95440-L1760 | OEM Parts Online'
        -> 'Keyless Entry Transmitter'"""
        # Strip year/make/model prefix and PN suffix
        clean = re.sub(r"^\d{4}(?:-\d{4})?\s+\w+\s+\w+\s+", "", title)
        clean = re.sub(r"\s+\d{5}[-A-Z0-9]+.*$", "", clean)
        clean = clean.split("|")[0].strip()
        return clean or "Keyless Entry Transmitter"

    @staticmethod
    def _classify_key_type(name_lc: str) -> KeyType:
        for label, kt in PART_NAME_TO_KEY_TYPE.items():
            if label in name_lc:
                return kt
        if "smart key" in name_lc or "fob" in name_lc:
            return KeyType.SMART_KEY
        if "transmitter" in name_lc:
            return KeyType.TRANSMITTER
        return KeyType.UNKNOWN
