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
        # 2025-2026 luxury/sport trims use the NEW 8990H-* family (e.g.
        # 8990H-30260 Crown Signia, 8990H-12460 GR Corolla). Older trims
        # stay on 89070/89904/89742. Query the new family FIRST because
        # the 8 known 2026 Toyota gaps (Crown Signia, GR Corolla, Sequoia,
        # Sienna Limited, Grand Highlander, Crown, Corolla Cross) are all
        # on 8990H per Key4/SFFOBS/transponderisland listings (2026-05-30).
        ("toyota.oempartsonline.com", ("8990H", "89070", "89904", "89742")),
    ],
    "lexus":   [
        ("lexus.oempartsonline.com", ("8990H", "89070", "89904", "89742")),
        ("toyota.oempartsonline.com", ("8990H", "89070", "89904", "89742")),  # adjacent
    ],
    # ─── Experimental makes (only queried when env-var-gated drivers
    # for this make are enabled in pipeline._drivers_for_make). DDG
    # fallback itself doesn't check the env var — the gate is upstream.
    "honda": [
        ("honda.oempartsonline.com", ("72147", "35118", "35880")),
    ],
    "acura": [
        ("acura.oempartsonline.com", ("72147", "35118", "35880")),
        ("honda.oempartsonline.com", ("72147", "35118", "35880")),  # adjacent
    ],
    "nissan": [
        ("nissan.oempartsonline.com", ("285E3", "28268", "28630")),
    ],
    "infiniti": [
        ("infiniti.oempartsonline.com", ("285E3", "28268", "28630")),
        ("nissan.oempartsonline.com", ("285E3", "28268", "28630")),  # adjacent
    ],
    "subaru": [
        ("subaru.oempartsonline.com", ("57497", "88835", "88036")),
    ],
    "mazda": [
        ("mazda.oempartsonline.com", ("KD45", "GHP9", "GHR9", "BBM4", "BHN9")),
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
        make_lc = (profile.make or "").strip().lower()
        h1 = soup.find("h1")
        h1_text = h1.get_text(" ", strip=True).lower() if h1 else ""
        title_lc = title.lower()
        title_h1 = title_lc + " " + h1_text

        # CANONICAL FITMENT CHECK (final form 2026-05-31):
        #
        # The dealer's authoritative attestation lives in TWO places:
        #
        #   1. The page TITLE — Revolution Parts always titles dealer pages
        #      as "<year(s)> <make> <model> <part name> <pn>".
        #
        #   2. The canonical body sentence — every Revolution Parts page
        #      contains "...will perfectly fit your <year(s)> <make> <model>
        #      vehicle..." as a marketing template.
        #
        # We accept the page IF either authoritative location says our VIN
        # fits. Cross-references in dropdowns, "related parts", or
        # "customers also viewed" sections are NOT trusted — those caused
        # confirmed false positives on 2017 Toyota Camry → 8990H-08021
        # (Sienna PN) because the dropdown listed multiple recent models.
        if not (year and model_lc and make_lc):
            await self._emit(
                "Candidate dropped (missing year/make/model)", "info",
            )
            return None

        make_re = re.escape(make_lc)
        # Model may have spaces — "Santa Fe", "Land Cruiser", "Grand
        # Highlander", "Corolla Cross"
        model_re = re.escape(model_lc).replace(r"\ ", r"\s+")
        year_int = int(year)

        def _check_phrase(haystack: str, source_label: str) -> str | None:
            # Look for "<year> <make> <model>" (single year)
            single = rf"\b{year}\s+{make_re}\s+{model_re}\b"
            if re.search(single, haystack):
                return f"{source_label}: '{year} {make_lc} {model_lc}'"
            # Look for "<yyyy>-<yyyy> <make> <model>" (year range)
            rng = rf"\b(\d{{4}})\s*[\-–—]\s*(\d{{4}})\s+{make_re}\s+{model_re}\b"
            for m in re.finditer(rng, haystack):
                lo, hi = int(m.group(1)), int(m.group(2))
                if lo <= year_int <= hi:
                    return (
                        f"{source_label}: '{m.group(1)}-{m.group(2)} "
                        f"{make_lc} {model_lc}' covering {year}"
                    )
            return None

        # 1) Title/H1 must explicitly include our year + make + model
        #    (Revolution Parts title format: "<year(s)> <make> <model> <part>")
        fit_kind = _check_phrase(title_h1, "title")

        # 2) Canonical body fitment phrase: "fit your <year(s)> <make> <model>"
        if not fit_kind:
            # Extract just the canonical fitment sentence and check it.
            # Pattern: "(perfectly )?fit your <YYYY[-YYYY]> <make> <model> vehicle"
            canonical = re.search(
                r"fit\s+your\s+(\d{4}(?:\s*[\-–—]\s*\d{4})?)\s+"
                rf"{make_re}\s+{model_re}\s+vehicle",
                text,
            )
            if canonical:
                year_token = canonical.group(1)
                rng_m = re.match(r"(\d{4})\s*[\-–—]\s*(\d{4})", year_token)
                if rng_m:
                    lo, hi = int(rng_m.group(1)), int(rng_m.group(2))
                    if lo <= year_int <= hi:
                        fit_kind = (
                            f"canonical fitment: '{year_token} {make_lc} "
                            f"{model_lc}' covering {year}"
                        )
                elif year_token.strip() == year:
                    fit_kind = (
                        f"canonical fitment: '{year_token} {make_lc} "
                        f"{model_lc}'"
                    )

        if not fit_kind:
            await self._emit(
                "Candidate dropped (no dealer attestation for our year+make+model)",
                "info", f"title={title[:80]!r}",
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
            fitment_evidence=f"Page has {fit_kind}",
            dealer_verified=True,
            notes="Found via DDG fallback search of dealer site",
        )

    @staticmethod
    def _extract_pn(url: str, title: str, soup: BeautifulSoup) -> str:
        """Pull OEM PN from URL (last segment after final dash) or from
        title text. Normalize to canonical Make-specific format.

        Handles the OEM PN shapes we've observed across makes:
          - 95440-AA501       Hyundai/Kia/Genesis    (5d + 5alphanum)
          - 89070-06791       Toyota (older)         (5d + 5d)
          - 8990H-30260       Toyota (2025+)         (4d + LETTER + 5d)
          - 72147-TBA-A11     Honda/Acura            (5d + 3char + 3char)
          - 35118-TG7-A31     Honda/Acura            (same shape)
          - 285E3-1LA5A       Nissan/Infiniti        (5alphanum + 5alphanum)
          - 164-R8166         Ford/Lincoln (Rotunda) (3d + 1L + 4d)
          - 57497AA001        Subaru                 (5alphanum + 5alphanum, no dash)
          - KD45-67-5DY       Mazda                  (4char + 2d + 3char)

        We try the most-specific shapes first to avoid greedy mismatches.
        Title-based fallback if URL extraction fails.
        """
        url_lc = url.lower()

        # 1. Honda / Acura: 5-digit + 3-char + 3-char (e.g. 72147tba-a11 or 72147tbaa11)
        m = re.search(
            r"/oem-parts/[^/]*?(\d{5})[\-]?([a-z0-9]{3})[\-]?([a-z0-9]{3})(?:[?#]|$)",
            url_lc,
        )
        if m and m.group(1) in {"72147", "35118", "35880"}:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}".upper()

        # 2. Ford Rotunda: 3-digit + R + 4-digit
        m = re.search(r"/oem-parts/[^/]*?(164r\d{4})(?:[?#]|$)", url_lc)
        if m:
            raw = m.group(1)
            return f"164-{raw[3:].upper()}"

        # 3. Mazda 3-segment: 4-char + 2-digit + 3-char (e.g. kd45675dy)
        m = re.search(
            r"/oem-parts/[^/]*?([a-z]{2}\d{2})(\d{2})([a-z0-9]{3})(?:[?#]|$)",
            url_lc,
        )
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}".upper()

        # 4. Toyota 8990H: 4-digit + letter + 5-digit
        m = re.search(
            r"/oem-parts/[^/]*?(\d{4}[a-z]\d{5})(?:[?#]|$)", url_lc,
        )
        if m:
            raw = m.group(1)
            return f"{raw[:5]}-{raw[5:]}".upper()

        # 5. Standard: 5-digit + 4-8 alphanumerics
        # Catches: 95440AA501 (Hyundai/Kia), 8907006791 (Toyota),
        #          57497AA001 (Subaru)
        m = re.search(
            r"/oem-parts/[^/]*?(\d{5}[a-z0-9]{4,8})(?:[?#]|$)", url_lc,
        )
        if m:
            raw = m.group(1)
            if len(raw) >= 6 and raw[:5].isdigit():
                return f"{raw[:5]}-{raw[5:]}".upper()
            return raw.upper()

        # 6. Nissan/Infiniti 285E3-XXXXX: 3-digit + letter + digit + 4-5 alphanum
        # The 285E3 prefix isn't pure-5-digit so the standard pattern misses it.
        m = re.search(
            r"/oem-parts/[^/]*?(\d{3}[a-z]\d)([a-z0-9]{4,6})(?:[?#]|$)", url_lc,
        )
        if m:
            return f"{m.group(1)}-{m.group(2)}".upper()

        # 6. Title fallback — covers all the patterns above as printed text
        for pat in [
            r"\b(\d{5}-[A-Z0-9]{3}-[A-Z0-9]{3})\b",  # 72147-TBA-A11
            r"\b(164-R\d{4})\b",                       # 164-R8166
            r"\b([A-Z]{2}\d{2}-\d{2}-[A-Z0-9]{3})\b",  # KD45-67-5DY
            r"\b(\d{4}[A-Z]\d{5})\b",                  # 8990H30260
            r"\b(\d{5}[-\s]?[A-Z0-9]{4,8})\b",         # 95440-AA501
        ]:
            m = re.search(pat, title)
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
