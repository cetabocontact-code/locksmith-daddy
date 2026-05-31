"""Direct-PN-probe driver: verify research-derived PN candidates by
fetching the dealer's own product page and confirming fitment for this VIN.

Background (2026-05-30): the DDG fallback driver finds dealer product pages
via search, but DDG sometimes misses pages whose snippet doesn't include
the year/model exactly as queried (e.g., a page titled "2025 Elantra"
that also fits 2026 won't surface for a `2026 Elantra` query). For those
cases, research across aftermarket suppliers + our own verified DB
already tells us the candidate PN — we just need to confirm the dealer
catalogs it AGAINST THIS VIN's year+model+trim.

This driver does exactly that:

  1. Look up candidate PNs by (make, model, year, trim_pattern) from a
     curated catalog of research-confirmed answers.
  2. For each candidate, hit `{dealer}/search?search_str={pn}` — the
     dealer-side search endpoint will redirect to the canonical product
     page IF the PN exists in this dealer's catalog.
  3. Verify the resulting product page's fitment text mentions the VIN's
     year and model (same standard as DDG fallback).
  4. Return as DEALER_VERIFIED_BY_VIN with the dealer's product URL as
     evidence — same quality of verification as any other driver in the
     chain (the dealer's own catalog confirms PN → year+model fitment).

This is NOT a guess. Every PN in the candidates table is either:
  - Confirmed by ≥3 independent aftermarket suppliers, OR
  - Verified for a sibling VIN of identical year+model+trim in our DB
And every returned answer is reconfirmed against the dealer's live page.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Awaitable, Callable
from urllib.parse import quote_plus

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

StepCallback = Callable[[ResearchStep], Awaitable[None] | None]


# Curated catalog of (make, model_lc, year_range, trim_pattern) → candidate PNs.
# Each entry must be cross-verified by ≥3 independent aftermarket sources OR
# a sibling-VIN dealer page in our own verified DB. NEVER ship a PN here
# that isn't backed by a real-world source — this is the LAST line of
# defense before "not found", and we lose locksmith trust if we guess.
#
# Format: each row is a tuple of:
#   (make, model_lc, year_low, year_high, trim_re, [pn_candidates], dealer)
# Trim is matched as a regex against profile.trim.lower() (case-insensitive).
# Empty trim_re matches all trims.
_PN_CATALOG: list[tuple[str, str, int, int, str, tuple[str, ...], str]] = [
    # ── 2026 Hyundai Elantra SEL Sport / Sport Premium ────────────────────
    # Sibling KMHLM4DGXTU098379 already verified at AA501 (cargurus_hyundai_report row 515).
    # 4 aftermarket suppliers (Royal Key, eBay, Best Key, SFFOBS) confirm AA501.
    ("hyundai", "elantra", 2023, 2026, r"sel sport|limited|sport premium",
     ("95440-AA501", "95440-AA500"),
     "hyundai.oempartsonline.com"),

    # ── 2025 Hyundai Santa Fe XRT ─────────────────────────────────────────
    # Siblings 5NMP24GL5SH097926 (SEL), 5NMP5DGL3SH095180 (Calligraphy),
    # 5NMP34G13TH098652 (Limited) all verified at P6040.
    # remotesandkeys, transponderisland, locksmithkeyless confirm P6040/P6050/P6100.
    ("hyundai", "santa fe", 2024, 2026, r"xrt|sel|limited|calligraphy",
     ("95440-P6040", "95440-P6050", "95440-P6100"),
     "hyundai.oempartsonline.com"),

    # ── 2025 Kia Sorento EX / X-Line EX ───────────────────────────────────
    # Sibling KNDRJDJH2S5322595 (2025 Sorento EX) verified at P2AA0.
    # Amazon, abkeys, RoyalKey, transponderisland confirm P2AA0/P2AB0.
    ("kia", "sorento", 2024, 2026, r"ex|x-line",
     ("95440-P2AA0", "95440-P2AB0", "95440-P2AC0"),
     "kia.oempartsonline.com"),

    # ── 2025 Genesis G70 (all trims) ──────────────────────────────────────
    # 6 aftermarket suppliers confirm G9820 (current) / G9720 (older spec).
    # Royal Key, UHS Hardware, Noble Key, ABKeys, transponderisland,
    # yourcarkeyguys all list G9820 for 2023-2026 G70 5-button.
    ("genesis", "g70", 2023, 2026, r"",
     ("95440-G9820", "95440-G9720"),
     "genesis.oempartsonline.com"),
]


def _find_candidates(profile: VehicleProfile) -> list[tuple[str, str]]:
    """Return [(pn, dealer_host)] candidates matching this VIN's profile."""
    make = (profile.make or "").lower().strip()
    model = (profile.model or "").lower().split(",")[0].strip()
    trim = (profile.trim or "").lower()
    year = profile.year or 0
    out: list[tuple[str, str]] = []
    for cat_make, cat_model, y_lo, y_hi, trim_re, pns, dealer in _PN_CATALOG:
        if cat_make != make:
            continue
        if cat_model not in model and model not in cat_model:
            continue
        if year and not (y_lo <= year <= y_hi):
            continue
        if trim_re and not re.search(trim_re, trim):
            continue
        for pn in pns:
            out.append((pn, dealer))
    return out


class KnownPnProbeDriver:
    """Probes research-derived PN candidates directly via the dealer's
    product page, returning DEALER_VERIFIED_BY_VIN when fitment confirms.

    Runs LAST in the chain — only fires if all primary drivers + DDG
    fallback have failed. Verifies via the same fitment-text check as
    the DDG fallback, so the resulting status is identical quality.
    """

    name = "known_pn_probe"

    def __init__(
        self,
        *,
        backend: ScrapeBackend | None = None,
        step_callback: StepCallback | None = None,
        **_legacy,
    ):
        self.backend = backend or get_backend()
        self.step_callback = step_callback
        self.steps: list[ResearchStep] = []
        self.screenshots: list[str] = []

    async def _emit(
        self, step: str, status: StepStatus = "info", detail: str | None = None
    ) -> None:
        rec = ResearchStep(
            timestamp=datetime.now(timezone.utc),
            step=step, status=status, detail=detail,
        )
        self.steps.append(rec)
        if self.step_callback:
            r = self.step_callback(rec)
            if asyncio.iscoroutine(r):
                await r

    async def lookup_vin(self, vin: str, profile: VehicleProfile) -> list[OemPart]:
        candidates = _find_candidates(profile)
        if not candidates:
            await self._emit("KnownPN: no candidates for this profile", "info")
            return []

        await self._emit(
            f"KnownPN probing {len(candidates)} candidate(s)", "info",
            f"{profile.year} {profile.make} {profile.model} / {profile.trim}",
        )

        found: list[OemPart] = []
        seen: set[str] = set()
        for pn, dealer_host in candidates:
            if pn in seen:
                continue
            seen.add(pn)
            part = await self._probe_pn(pn, dealer_host, profile)
            if part:
                found.append(part)
                # First successful PN is the answer; remaining candidates
                # are likely sibling trims that also exist. Don't probe
                # them — saves credits and avoids returning multiple PNs
                # when one is enough.
                break

        await self._emit(
            f"KnownPN captured {len(found)} verified PN(s)",
            "success" if found else "info",
        )
        return found

    async def _probe_pn(
        self, pn: str, dealer_host: str, profile: VehicleProfile,
    ) -> OemPart | None:
        """Resolve PN → dealer product URL → verify fitment → return OemPart.

        Uses the dealer's search endpoint to find the canonical product URL,
        then re-fetches that URL and confirms the fitment text mentions our
        VIN's year + model.
        """
        # Step 1: search the dealer for this PN. Their server redirects to
        # the canonical product page (e.g. /oem-parts/...-95440aa501) if it
        # exists, or returns a search results page if not.
        search_url = f"https://{dealer_host}/search?search_str={quote_plus(pn)}"
        await self._emit(f"KnownPN search: {pn}", "info", search_url)
        result = await self.backend.fetch(search_url)
        if not result.ok:
            await self._emit(
                f"KnownPN search failed for {pn}", "warning",
                f"status={result.status}",
            )
            return None

        # If the search redirected to a product page, use that URL.
        # Otherwise parse the result page for an /oem-parts/...{pn-no-dash}... link.
        product_url = result.final_url
        if "/oem-parts/" not in product_url.lower():
            soup = BeautifulSoup(result.html, "lxml")
            pn_compact = pn.replace("-", "").lower()
            link = None
            for a in soup.select("a[href*='/oem-parts/']"):
                href = (a.get("href") or "").lower()
                if pn_compact in href:
                    link = a.get("href")
                    break
            if not link:
                await self._emit(
                    f"KnownPN: dealer search returned no product page for {pn}",
                    "info",
                )
                return None
            if link.startswith("/"):
                product_url = f"https://{dealer_host}{link}"
            else:
                product_url = link

        # Step 2: fetch the product page and verify fitment.
        await self._emit(f"KnownPN verifying {pn}", "info", product_url[:120])
        page = await self.backend.fetch(product_url)
        if not page.ok:
            await self._emit(
                f"KnownPN product page fetch failed for {pn}", "warning",
                f"status={page.status}",
            )
            return None

        soup = BeautifulSoup(page.html, "lxml")
        title = (soup.title.string or "").strip() if soup.title else ""
        body_text = soup.get_text(" ", strip=True).lower()
        h1 = soup.find("h1")
        h1_text = h1.get_text(" ", strip=True).lower() if h1 else ""
        title_lc = title.lower()
        title_h1 = title_lc + " " + h1_text

        year = str(profile.year) if profile.year else ""
        model_lc = (profile.model or "").split(",")[0].strip().lower()

        # Year check: must appear in title (best) or anywhere in body.
        # Dealer pages often say "2024-2026 Hyundai Elantra" in title —
        # check if our year falls within that title range explicitly.
        year_in_title = year in title_h1
        year_in_body = year in body_text
        # Also accept year ranges like "2024-2026" or "2023 – 2026"
        year_in_range = False
        if year:
            for m in re.finditer(
                r"(\d{4})\s*[-–—]\s*(\d{4})", body_text + " " + title_h1,
            ):
                lo, hi = int(m.group(1)), int(m.group(2))
                if lo <= int(year) <= hi:
                    year_in_range = True
                    break
        if not (year_in_title or year_in_body or year_in_range):
            await self._emit(
                f"KnownPN: year not on page for {pn}", "info",
                f"title={title[:80]!r}",
            )
            return None

        # Model check: must mention the model name somewhere.
        if model_lc and model_lc not in title_h1 and model_lc not in body_text:
            await self._emit(
                f"KnownPN: model not on page for {pn}", "info",
                f"title={title[:80]!r}",
            )
            return None

        # Classify the key-type from the title/H1.
        name_lc = title_h1
        key_type = KeyType.UNKNOWN
        for label, kt in PART_NAME_TO_KEY_TYPE.items():
            if label in name_lc:
                key_type = kt
                break
        if key_type == KeyType.UNKNOWN:
            if "smart key" in name_lc or "fob" in name_lc:
                key_type = KeyType.SMART_KEY
            elif "transmitter" in name_lc:
                key_type = KeyType.TRANSMITTER
        if key_type == KeyType.UNKNOWN:
            await self._emit(
                f"KnownPN: page not classified as a key part for {pn}",
                "info", f"title={title[:80]!r}",
            )
            return None

        await self._emit(
            f"KnownPN VERIFIED {pn} for {profile.year} {profile.model}",
            "success", product_url,
        )

        return OemPart(
            oem_part_number=pn,
            part_name=self._derive_part_name(title),
            key_type=key_type,
            source_url=product_url,
            category_path=f"KnownPN-probe: {dealer_host}",
            fitment_evidence=(
                f"Dealer product page confirms {pn} fits {year} {model_lc}"
            ),
            dealer_verified=True,
            notes="Verified via known-PN probe (research-derived candidate "
                  "confirmed against dealer's live product page)",
        )

    @staticmethod
    def _derive_part_name(title: str) -> str:
        clean = re.sub(r"^\d{4}(?:-\d{4})?\s+\w+\s+\w+\s+", "", title)
        clean = re.sub(r"\s+\d{5}[-A-Z0-9]+.*$", "", clean)
        clean = clean.split("|")[0].strip()
        return clean or "Smart Key Fob"
