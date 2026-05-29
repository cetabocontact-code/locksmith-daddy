"""Base class for oempartsonline.com dealer-site scrapers.

Backend-agnostic: the driver calls `self.backend.fetch(url)` and parses the
returned HTML with BeautifulSoup. Swap backends (ScrapingAnt, Bright Data,
local Playwright) via config without touching driver logic.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Awaitable, Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from lbt1.models import (
    PART_NAME_TO_KEY_TYPE,
    KeyType,
    OemPart,
    ResearchStep,
    StepStatus,
    VehicleProfile,
)
from lbt1.scrapers.backends import ScrapeBackend, get_backend

log = logging.getLogger(__name__)

StepCallback = Callable[[ResearchStep], Awaitable[None] | None]


class ScraperError(Exception):
    """Raised when the driver cannot complete the lookup."""


# Part-name keywords that mean "this isn't the key itself" — batteries, brackets,
# button modules, shells. We reject anything whose name contains these even if
# it also mentions a key-type word.
ACCESSORY_KEYWORDS = (
    "battery",
    "bracket",
    "antenna",
    "module",
    "receiver",
    "switch",
    "case",
    "cover",
    "shell",
    "blade",
    "holder",
    "harness",
    "sensor",
    "label",
    "start button",
)


class OempartsonlineDriver:
    """Abstract driver for the oempartsonline.com family of dealer sites
    (Kia, Hyundai, Genesis — all built on the same Revolution Parts CMS).

    Subclasses set `base_url`. Selectors and category paths are inherited
    and only overridden when a make-specific site diverges.
    """

    base_url: str = ""

    key_part_labels: tuple[str, ...] = tuple(PART_NAME_TO_KEY_TYPE.keys())

    # Section/slug pairs that compose category URLs:
    #   {vehicle_url}/{section}--{slug}
    # Confirmed live for Kia 2014-present; same paths exist on Hyundai/Genesis.
    category_paths: tuple[tuple[str, str], ...] = (
        ("electrical", "keyless-entry-components"),
        ("electrical", "anti-theft-system"),
        ("electrical", "electrical-components"),
    )

    def __init__(
        self,
        *,
        backend: ScrapeBackend | None = None,
        step_callback: StepCallback | None = None,
        **_legacy_kwargs,  # accept (and ignore) old Playwright-era kwargs
    ):
        self.backend = backend or get_backend()
        self.step_callback = step_callback
        self.steps: list[ResearchStep] = []
        self.screenshots: list[str] = []  # kept for API compatibility, unused

    async def _emit(
        self, step: str, status: StepStatus = "info", detail: str | None = None
    ) -> None:
        record = ResearchStep(
            timestamp=datetime.now(timezone.utc),
            step=step,
            status=status,
            detail=detail,
        )
        self.steps.append(record)
        log.info("[%s] %s — %s", status, step, detail or "")
        if self.step_callback is not None:
            result = self.step_callback(record)
            if asyncio.iscoroutine(result):
                await result

    @staticmethod
    def classify_part_name(name: str) -> KeyType:
        lowered = (name or "").strip().lower()
        for label, key_type in PART_NAME_TO_KEY_TYPE.items():
            if label in lowered:
                return key_type
        return KeyType.UNKNOWN

    def _is_key_part(self, name: str) -> bool:
        lowered = (name or "").lower()
        return any(label in lowered for label in self.key_part_labels)

    # ─── Main flow ─────────────────────────────────────────────────────────

    async def lookup_vin(self, vin: str, profile: VehicleProfile) -> list[OemPart]:
        """Resolve VIN → vehicle URL, sweep key category pages, return parts.

        Strict policy for OEM dealer sources (Kia/Hyundai/Genesis): we ONLY
        return parts that the dealer has actually catalogued AGAINST THIS
        SPECIFIC model year + trim + engine. Year-fallback / "looks close"
        guesses are NEVER returned, because the dealer's fitment checker
        will reject prior-year PNs even when the trim name matches.
        (Locksmith trust > coverage; verified 2026-05-28 against
        KMHLS4DG5TU123100 where 2025 PN 95440-AA500 is explicitly "does
        not fit" on the 2026 Elantra.)
        """
        await self._emit(f"Starting lookup for {profile.display}", "info", vin)

        vehicle_url = await self._resolve_vehicle_url(vin, profile)
        if vehicle_url is None:
            await self._emit("Could not resolve VIN to a vehicle URL", "error")
            return []
        await self._emit("Vehicle URL", "info", vehicle_url)

        found = await self._sweep_categories(vehicle_url)
        await self._emit(
            f"Captured {len(found)} part(s)" if found else "Captured 0 part(s)",
            "success" if found else "info",
        )
        return list(_dedupe_by_pn(found).values())

    async def _sweep_categories(self, vehicle_url: str) -> list[OemPart]:
        """Sweep self.category_paths under vehicle_url and return harvested parts."""
        # Parallelize the 3 category sweeps within a dealer — they're
        # independent requests against the same vehicle URL. ~3x latency win
        # vs sequential. Throttle-wise this stays safe because we cap dealer
        # concurrency at the pipeline level (see _drivers_for_make policy)
        # and ScrapFly rotates IPs per request.
        async def sweep_one(section: str, slug: str) -> list[OemPart]:
            crumb = f"{section} > {slug.replace('-', ' ')}"
            url = f"{vehicle_url}/{section}--{slug}"
            await self._emit(f"Sweeping {crumb}", "info", url)
            result = await self.backend.fetch(url)
            if not result.ok:
                title = _peek_title(result.html)
                await self._emit(
                    f"Category fetch failed: {crumb}",
                    "warning",
                    f"status={result.status} title={title!r} error={result.error}",
                )
                return []
            if "Just a moment" in _peek_title(result.html):
                await self._emit(
                    f"Cloudflare challenge on {crumb}", "warning", url
                )
                return []
            parts = self._harvest_parts_from_html(result.html, crumb, result.final_url)
            await self._emit(
                f"Found {len(parts)} key PN(s) under {crumb}",
                "success" if parts else "info",
            )
            return parts

        sweep_results = await asyncio.gather(
            *(sweep_one(s, slug) for s, slug in self.category_paths),
            return_exceptions=False,
        )
        found: list[OemPart] = []
        for r in sweep_results:
            found.extend(r)
        return found

    async def _resolve_vehicle_url(
        self, vin: str, profile: VehicleProfile
    ) -> str | None:
        """Submit /search?search_str=<VIN> and resolve to a fully-specified
        vehicle URL.

        The dealer's response varies by site & ambiguity:
          1. /v-{year}-{make}-{model}--{trim}--{engine}       → uniquely resolved
          2. /v-{year}-{make}-{model}?vin=...                  → soft chooser (model-level, must pick trim)
          3. /search?...  (HTML chooser inline)                → hard chooser
          4. error / no match                                  → return None

        For (2) and (3), we use NHTSA's full profile to pick a specific trim URL.
        """
        search_url = f"{self.base_url.rstrip('/')}/search?search_str={vin}"
        await self._emit("Submitting VIN", "info", search_url)

        result = await self.backend.fetch(search_url)
        if not result.ok:
            await self._emit(
                "VIN search failed",
                "error",
                f"status={result.status} error={result.error}",
            )
            return None

        title = _peek_title(result.html)
        if "Just a moment" in title:
            await self._emit("Cloudflare challenge on /search", "error", search_url)
            return None

        # Case 1: fully-resolved vehicle URL (path has trim/engine after model).
        if _is_fully_resolved_vehicle_url(result.final_url):
            clean = _strip_query_and_fragment(result.final_url)
            await self._emit("Landed on vehicle page", "success", clean)
            return clean

        # Case 2 or 3: soft chooser (model-level URL with ?vin=, or /search
        # still showing). Parse HTML and let NHTSA pick a specific trim URL.
        soup = BeautifulSoup(result.html, "lxml")
        vehicle_href = self._find_vehicle_link(soup, profile)
        if vehicle_href:
            full = _strip_query_and_fragment(urljoin(result.final_url, vehicle_href))
            await self._emit("Picked trim via NHTSA disambiguation", "success", full)
            return full

        await self._emit(
            "Dealer + NHTSA could not resolve VIN to a specific trim",
            "warning",
            f"final_url={result.final_url} title={title!r}",
        )
        return None

    def _find_vehicle_link(
        self, soup: BeautifulSoup, profile: VehicleProfile
    ) -> str | None:
        """On a trim/engine chooser page, use ALL NHTSA fields to pick the
        best-matching link. Return the best match found — only return None
        when there's no make+model match at all.

        Design contract (per user 2026-05-26):
          - User only types a VIN. NHTSA is the only source of truth.
          - When the dealer chooser appears, USE NHTSA to choose: engine
            displacement, cylinder count, fuel type, drive type, transmission,
            body class — every signal counts.
          - Don't return "no PN found" out of excess caution. Pick the best
            match NHTSA can identify, and LOG the disambiguation decision
            (data/disambiguation.log) so we can study the data and improve.
          - The dealer-uniquely-resolved case (search → /v-*) is still the
            highest-confidence path; this method only fires when the dealer
            falls back to a chooser.
        """
        candidates = soup.select("a[data-trim], a[href*='/v-']")
        make_slug = _slugify(profile.make or "")
        raw_model = (profile.model or "").split(",")[0].strip()
        model_slug = _slugify(raw_model.split()[0] if raw_model else "")

        # NHTSA can list multiple trims for one VIN. Score against ALL.
        # We keep TWO slug shapes because they each match different surfaces:
        #   - solid: "sel-sport-premium" → "selsportpremium" (matches data-trim
        #     attrs and concatenated text)
        #   - hyphen: "SEL Sport Premium" → "sel-sport-premium" (matches the
        #     dealer's URL trim segment + chooser link text where Revolution
        #     Parts uses hyphens)
        trim_slugs = [_slugify(t) for t in profile.trim_candidates() if t]
        trim_hyphen_slugs = [
            _hyphen_slugify(t) for t in profile.trim_candidates() if t
        ]
        engine_slugs = profile.engine_slug_variants()  # ["2-5l-l4-gas", ...]
        cyl_slug = f"l{profile.engine_cylinders}" if profile.engine_cylinders else ""
        disp_slug = (
            f"{profile.displacement_l:g}l".replace(".", "-")
            if profile.displacement_l else ""
        )
        fuel_first = (profile.fuel_type or "").lower().split()[0][:3]  # 'gas'/'die'/'ele'
        drive_short = ""  # "fwd", "awd", "4wd"
        if profile.drive_type:
            dt = profile.drive_type.lower()
            if "front" in dt or "fwd" in dt: drive_short = "fwd"
            elif "rear" in dt: drive_short = "rwd"
            elif "all" in dt or "awd" in dt: drive_short = "awd"
            elif "4wd" in dt or "4x4" in dt: drive_short = "4wd"

        # PASS 1 — filter to make + model + YEAR. The year requirement is
        # critical (2026-05-29 diagnostic finding): year-less stub URLs like
        # `/v-hyundai-sonata` are "browse navigation" links the dealer shows
        # for catalog navigation, NOT real vehicle pages. If we pick one,
        # category sweeps 404 because there's no real vehicle context.
        # Real vehicle URLs always follow `/v-{YYYY}-{make}-{model}[...]`.
        profile_year_str = str(profile.year) if profile.year else ""
        filtered: list[tuple[str, dict]] = []
        for el in candidates:
            href = el.get("href") or ""
            if "/v-" not in href:
                continue
            href_lc = href.lower()
            data_make = (el.get("data-make") or "").lower()
            data_model = (el.get("data-model") or "").lower()

            make_ok = (not make_slug) or (
                make_slug in href_lc or make_slug in data_make
            )
            model_ok = (not model_slug) or (
                model_slug in href_lc or model_slug in data_model
            )
            # Year requirement: the path between `/v-` and the next `-` must
            # be a 4-digit year. Rejects `/v-hyundai-sonata` (no year) but
            # accepts `/v-2024-hyundai-sonata` and trimmed variants.
            year_ok = _has_year_segment(href_lc, profile_year_str)
            if make_ok and model_ok and year_ok:
                filtered.append((href, {
                    "trim_attr": (el.get("data-trim") or "").lower(),
                    "engine_attr": (el.get("data-engine") or "").lower(),
                    "text": el.get_text(" ", strip=True).lower(),
                    "href_lc": href_lc,
                    "is_ghost": False,  # filled in below
                }))

        if not filtered:
            return None

        # Single make+model match — dealer already resolved it. Safe to take.
        if len(filtered) == 1:
            return filtered[0][0]

        # ── GHOST-LINK DETECTION ──────────────────────────────────────────
        # Revolution Parts injects a "smart suggestion" anchor near the top
        # of the search-result page whose href is *templated from the VIN's
        # NHTSA decode* (data-trim="sel-sport-premium"). For trims the dealer
        # actually catalogs, the templated URL matches a real trim-chooser
        # link. For trims the dealer doesn't carry (e.g. 2026 Elantra "SEL
        # Sport Premium" — dealer only has "SEL Sport"), the templated URL
        # silently 301s back to the bare model chooser, yielding 0 PNs.
        #
        # The real trim-chooser links (one per dealer trim) don't carry the
        # data-trim/data-engine attrs and live in the page's trim list. We
        # treat any link bearing data-trim whose href is NOT also present as
        # a plain chooser link as a "ghost" and skip it.
        chooser_hrefs = {h.lower() for h, a in filtered if not a["trim_attr"]}
        for h, a in filtered:
            if a["trim_attr"] and h.lower() not in chooser_hrefs:
                a["is_ghost"] = True

        non_ghosts = [(h, a) for h, a in filtered if not a["is_ghost"]]
        scoring_pool = non_ghosts if non_ghosts else filtered

        if len(scoring_pool) == 1:
            return scoring_pool[0][0]

        # PASS 2 — score each (non-ghost) link against every NHTSA field we have.
        scored: list[tuple[int, str, dict]] = []
        for href, attrs in scoring_pool:
            score = 0
            haystack = " ".join((attrs["trim_attr"], attrs["text"], attrs["href_lc"]))

            # Exact engine slug match — strongest signal (data-engine="2-5l-l4-gas")
            for eng in engine_slugs:
                if eng and eng in attrs["engine_attr"]:
                    score += 8
                    break
            # Engine slug also lives inside href on chooser links that lack
            # data-engine attrs (e.g. ".../v-2026-...--sel-sport--2-0l-l4-gas").
            for eng in engine_slugs:
                if eng and eng in attrs["href_lc"]:
                    score += 6
                    break

            # Partial engine fragments (displacement, cylinders, fuel)
            if disp_slug and disp_slug in haystack:
                score += 4
            if cyl_slug and cyl_slug in haystack:
                score += 3
            if fuel_first and fuel_first in haystack:
                score += 1
            if drive_short and drive_short in haystack:
                score += 2

            # Trim match — try every NHTSA trim candidate. Score by best
            # token overlap so NHTSA "SEL Sport Premium" can match dealer
            # "SEL Sport" (dealer is the shorter form / Premium is a
            # package, not a separate dealer trim).
            #
            # We compare on the hyphenated slug (e.g. "sel-sport-premium" vs
            # "sel-sport") so token overlap on hyphen-split words works.
            dealer_trim_slug = _extract_trim_slug_from_href(
                attrs["href_lc"], model_slug
            )
            best_trim_score = 0
            for trim_hyphen, trim_solid in zip(trim_hyphen_slugs, trim_slugs):
                if not trim_hyphen and not trim_solid:
                    continue
                # Direct hyphen-slug substring either way (handles "sel-sport"
                # inside "sel-sport-premium" AND vice versa).
                if dealer_trim_slug and trim_hyphen and (
                    dealer_trim_slug in trim_hyphen or trim_hyphen in dealer_trim_slug
                ):
                    overlap = _trim_token_overlap(trim_hyphen, dealer_trim_slug)
                    # Reward proportional length-overlap so "sel-sport" (2/3
                    # tokens of "sel-sport-premium") beats "se" (0 token
                    # overlap, just a leading-letter coincidence).
                    best_trim_score = max(best_trim_score, 3 + overlap)
                elif trim_solid and (
                    trim_solid in attrs["trim_attr"]
                    or trim_solid in _slugify(attrs["text"])
                ):
                    best_trim_score = max(best_trim_score, 3)
            score += best_trim_score

            scored.append((score, href, attrs))

        # Sort by score desc; pick the top.
        scored.sort(key=lambda x: x[0], reverse=True)
        top_score, top_href, top_attrs = scored[0]
        runner_up_score = scored[1][0] if len(scored) > 1 else -999

        # Log the disambiguation decision so we can study it and improve later.
        _log_disambiguation(
            vin=profile.vin,
            profile=profile,
            candidates=[{"score": s, "href": h, "attrs": a} for s, h, a in scored],
            chosen=top_href,
            margin=top_score - runner_up_score,
        )

        # Always return SOMETHING when make+model match — let the locksmith
        # see the best NHTSA-disambiguated result + any alternates from same
        # PN list. None only when filtered was empty (no make+model match).
        return top_href

    def _harvest_parts_from_html(
        self, html: str, category_path: str, source_url: str
    ) -> list[OemPart]:
        """Parse a category-page HTML and extract key-related part cards.

        Card structure (verified live 2026-05-25 on kia.oempartsonline.com):

            <div class="marketplace-info-col">
              <strong class="product-title">
                <a href="..." title="...">PART NAME</a>
              </strong>
              <div class="product-partnum"><a href="...">PART-NUMBER</a></div>
              <p class="contextual_description">CONTEXTUAL NAME</p>
              <p class="specific_description">FITMENT NOTES</p>
            </div>
        """
        soup = BeautifulSoup(html, "lxml")
        results: list[OemPart] = []

        for card in soup.select(".marketplace-info-col"):
            pn_el = card.select_one(".product-partnum a")
            title_el = card.select_one(".product-title a")
            desc_el = card.select_one(".contextual_description")
            spec_el = card.select_one(".specific_description")

            pn = (pn_el.get_text(strip=True) if pn_el else "").strip()
            if not pn:
                continue

            name = (title_el.get_text(strip=True) if title_el else "").strip()
            description = (desc_el.get_text(strip=True) if desc_el else "").strip()
            fitment = (spec_el.get_text(" ", strip=True) if spec_el else "").strip()

            # Reject accessories that share a key-related word but aren't keys.
            if _is_accessory(name) or _is_accessory(description):
                continue

            if self._is_key_part(name):
                key_type = self.classify_part_name(name)
            elif self._is_key_part(description):
                key_type = self.classify_part_name(description)
            else:
                continue

            href = None
            if title_el and title_el.get("href"):
                href = urljoin(source_url, title_el["href"])
            elif pn_el and pn_el.get("href"):
                href = urljoin(source_url, pn_el["href"])

            results.append(
                OemPart(
                    oem_part_number=pn,
                    part_name=name or description or None,
                    key_type=key_type,
                    source_url=href,
                    category_path=category_path,
                    fitment_evidence=fitment or None,
                    dealer_verified=True,
                )
            )
        return results


# ─── Module-level helpers ────────────────────────────────────────────────────


def _is_accessory(text: str) -> bool:
    lowered = (text or "").lower()
    return any(kw in lowered for kw in ACCESSORY_KEYWORDS)


def _slugify(text: str) -> str:
    """Lowercase + alphanumerics-only, for comparing NHTSA fields against
    URL slugs and data-* attributes on chooser pages."""
    return "".join(c for c in text.lower() if c.isalnum())


def _hyphen_slugify(text: str) -> str:
    """Lowercase, alphanumerics joined by single hyphens — matches the
    convention Revolution Parts uses in URLs and chooser text.

    "SEL Sport Premium" → "sel-sport-premium"
    "Limited 2.0L L4"   → "limited-2-0l-l4"
    """
    out: list[str] = []
    cur: list[str] = []
    for ch in (text or "").lower():
        if ch.isalnum():
            cur.append(ch)
        else:
            if cur:
                out.append("".join(cur))
                cur = []
    if cur:
        out.append("".join(cur))
    return "-".join(out)


def _log_disambiguation(
    *,
    vin: str,
    profile,  # VehicleProfile
    candidates: list[dict],
    chosen: str,
    margin: int,
) -> None:
    """Append a disambiguation decision to a structured log so we can study
    what NHTSA fields successfully disambiguated, and improve the matcher
    for future deployment briefs.

    Logs to data/disambiguation.log as one JSON line per decision.
    Best-effort — never raises.
    """
    try:
        import json
        from datetime import datetime, timezone
        from pathlib import Path

        from lbt1 import config

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "vin": vin,
            "profile": {
                "year": profile.year,
                "make": profile.make,
                "model": profile.model,
                "trim": profile.trim,
                "trim_candidates": profile.trim_candidates(),
                "engine_model": profile.engine_model,
                "displacement_l": profile.displacement_l,
                "engine_cylinders": profile.engine_cylinders,
                "fuel_type": profile.fuel_type,
                "drive_type": profile.drive_type,
                "transmission_style": profile.transmission_style,
                "body_class": profile.body_class,
                "engine_slug_variants": profile.engine_slug_variants(),
            },
            "candidate_count": len(candidates),
            "candidates": candidates,
            "chosen_href": chosen,
            "score_margin": margin,
            # Confidence level the locksmith can read: HIGH=clear NHTSA winner,
            # MEDIUM=narrow margin, LOW=picked best-of-many but really uncertain
            "confidence": "high" if margin >= 4 else "medium" if margin >= 2 else "low",
        }
        log_path = Path(config.DATA_DIR) / "disambiguation.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to log disambiguation decision: %s", exc)


def _dedupe_by_pn(parts: list[OemPart]) -> dict[str, OemPart]:
    out: dict[str, OemPart] = {}
    for p in parts:
        if p.oem_part_number not in out:
            out[p.oem_part_number] = p
    return out


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _peek_title(html: str) -> str:
    if not html:
        return ""
    m = _TITLE_RE.search(html)
    return m.group(1).strip()[:200] if m else ""


def _strip_query_and_fragment(url: str) -> str:
    """Remove ?query and #fragment from a URL, keeping just the path."""
    base = url.split("#", 1)[0]
    base = base.split("?", 1)[0]
    return base.rstrip("/")


def _is_fully_resolved_vehicle_url(url: str) -> bool:
    """True iff the URL is a fully-specified vehicle page
    (e.g. /v-2026-kia-sportage--x-line--2-5l-l4-gas), as opposed to a
    model-level page (/v-2020-kia-soul?vin=...) or a search/error page.

    Heuristic: the path contains '/v-' AND has at least one '--' separator
    after the slug (which marks the trim+engine segments).
    """
    if "/v-" not in url:
        return False
    # Strip query+fragment for the path-only check.
    path = url.split("?", 1)[0].split("#", 1)[0]
    # The '/v-' slug itself may contain hyphens (e.g. 'v-2026'); we need a
    # '--' (double-dash) which only appears at trim/engine separators.
    after_v = path.split("/v-", 1)[1]
    return "--" in after_v


def _has_year_segment(href_lc: str, profile_year_str: str = "") -> bool:
    """True iff the URL contains a 4-digit year segment right after `/v-`.

    Real vehicle URLs follow `/v-{YYYY}-{make}-{model}[--{trim}--{engine}]`.
    Year-less stubs like `/v-hyundai-sonata` are dealer "browse navigation"
    links — not real vehicle pages. Picking one of these stubs causes the
    category sweep to 404, costing ~50 ScrapFly credits per failed lookup.

    When profile_year_str is provided, ALSO requires the URL's year to
    match — prevents accidentally picking last year's catalog entry from
    a multi-year search-result page. Pass "" to accept any 4-digit year.
    """
    import re
    m = re.search(r"/v-(\d{4})-", href_lc)
    if not m:
        return False
    if profile_year_str and m.group(1) != profile_year_str:
        return False
    return True


def _extract_trim_slug_from_href(href: str, model_slug: str) -> str:
    """Pull the dealer's trim slug out of a /v-YYYY-make-model--trim--engine href.

    Returns "" when the href is model-level (no trim segment) or when the
    model slug can't be located. Example:
        /v-2026-hyundai-elantra--sel-sport--2-0l-l4-gas
        with model_slug='elantra' → 'sel-sport'
    """
    if not href or not model_slug:
        return ""
    h = href.lower().split("?", 1)[0].split("#", 1)[0]
    # The trim sits between `--` after model and the next `--` (engine).
    needle = model_slug + "--"
    if needle not in h:
        return ""
    tail = h.split(needle, 1)[1]
    # tail looks like 'sel-sport--2-0l-l4-gas' or 'sel-sport'
    return tail.split("--", 1)[0]


def _trim_token_overlap(a: str, b: str) -> int:
    """Bonus points (0–3) for shared hyphen-split tokens between two trim slugs.

    Lets us prefer "sel-sport" over "sel-convenience" when NHTSA says
    "sel-sport-premium": both share the "sel" token, but only "sel-sport"
    also shares the "sport" token. Maxes out at 3 so engine match still
    dominates.
    """
    if not a or not b:
        return 0
    ta = {t for t in a.split("-") if t}
    tb = {t for t in b.split("-") if t}
    return min(3, len(ta & tb))
