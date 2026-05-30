"""High-level orchestration shared by the CLI and the FastAPI app.

Wraps the four layers (validate → NHTSA decode → Playwright scrape → result
assembly) so callers get a single `lookup()` to invoke.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

import json

from lbt1 import db, diagnostics
from lbt1.models import KeyType, LookupResult, OemPart, ResearchStep, VehicleProfile
from lbt1.scrapers.base import OempartsonlineDriver
from lbt1.scrapers.genesis import GenesisOempartsDriver
from lbt1.scrapers.hyundai import HyundaiOempartsDriver
from lbt1.scrapers.hyundaioempart import HyundaiOemPartDriver
from lbt1.scrapers.kia import KiaOempartsDriver
from lbt1.scrapers.search_fallback import DuckDuckGoSearchFallbackDriver
from lbt1.scrapers.simplepart import (
    HyundaiCanadaDriver, KiaUsOfficialDriver, SimplepartDriver,
)
from lbt1.scrapers.toyota import ToyotaOempartsDriver
from lbt1.vin import decoder, validator

log = logging.getLogger(__name__)

StepCallback = Callable[[ResearchStep], Awaitable[None] | None]


async def lookup(
    vin: str,
    *,
    step_callback: StepCallback | None = None,
) -> LookupResult:
    """Run the full pipeline for a single VIN and return a LookupResult.

    Even when scraping fails or NHTSA errors, this returns a LookupResult
    (with warnings populated) rather than raising — the locksmith UI should
    always have something to display.
    """
    try:
        normalized = validator.validate(vin)
    except validator.VinValidationError as exc:
        return LookupResult(
            vin=vin,
            vehicle_profile=VehicleProfile(vin=vin),
            dealer_verification_status="NOT_DEALER_VERIFIED_BY_VIN",
            warnings=[f"VIN format invalid: {exc}"],
            confidence_score=0.0,
            confidence_label="LOW",
        )

    # NO cache shortcut. Every lookup runs the full live pipeline. The seeded
    # results in the DB are reference data for the system to learn from, never
    # served back to users as if they were fresh. (User policy 2026-05-26.)

    try:
        profile = await decoder.decode(normalized)
    except decoder.NhtsaDecodeError as exc:
        return LookupResult(
            vin=normalized,
            vehicle_profile=VehicleProfile(vin=normalized),
            dealer_verification_status="NOT_DEALER_VERIFIED_BY_VIN",
            warnings=[f"NHTSA decode failed: {exc}"],
            confidence_score=0.0,
            confidence_label="LOW",
        )

    make = (profile.make or "").lower()
    drivers = _drivers_for_make(make)
    if not drivers:
        return LookupResult(
            vin=normalized,
            vehicle_profile=profile,
            dealer_verification_status="NOT_DEALER_VERIFIED_BY_VIN",
            warnings=[
                f"No dealer-site scraper available for make {profile.make!r}. "
                "Currently supported: Kia, Hyundai, Genesis."
            ],
            confidence_score=0.0,
            confidence_label="LOW",
        )

    # Try each dealer in order. Stop as soon as one returns at least one PN.
    # The chain captures real-world catalog gaps — one dealer might have a
    # brand-new trim's data before another does.
    all_steps: list = []
    last_exception: Exception | None = None
    dealer_attempted: list[str] = []

    for i, driver_cls in enumerate(drivers):
        driver = driver_cls(step_callback=step_callback)
        dealer_attempted.append(driver_cls.__name__)
        try:
            parts = await driver.lookup_vin(normalized, profile)
        except Exception as exc:  # noqa: BLE001 — pipeline must not crash
            log.exception("Scraper %s raised for VIN %s", driver_cls.__name__, normalized)
            all_steps.extend(driver.steps)
            last_exception = exc
            continue

        all_steps.extend(driver.steps)

        if parts:
            # First dealer that has any PNs wins. Tag the result so the locksmith
            # knows which dealer answered.
            if i > 0:
                # Fallback fired — add a research step explaining why.
                from datetime import datetime, timezone
                from lbt1.models import ResearchStep
                all_steps.append(ResearchStep(
                    timestamp=datetime.now(timezone.utc),
                    step=f"Fallback dealer used: {driver_cls.__name__}",
                    status="info",
                    detail=(
                        f"Primary {drivers[0].__name__} returned zero key parts; "
                        f"{driver_cls.__name__} had data. "
                        f"Tried in order: {dealer_attempted}"
                    ),
                ))
            result = _assemble_result(
                vin=normalized,
                profile=profile,
                parts=parts,
                steps=all_steps,
                screenshots=driver.screenshots,
            )
            if diagnostics.diagnostics_enabled():
                diagnostics.record({
                    "vin": normalized,
                    "year": profile.year,
                    "make": profile.make,
                    "model": profile.model,
                    "trim": profile.trim,
                    "dealers_attempted": dealer_attempted,
                    "answering_dealer": driver_cls.__name__,
                    "fallback_tier": i,  # 0 = primary, 1 = secondary, etc.
                    "pn_count": len(parts),
                    "primary_pn": result.primary_result.oem_part_number if result.primary_result else None,
                    "status": result.dealer_verification_status,
                    "outcome": "verified",
                })
            return result

        # No parts — try next dealer in the chain.
        if i + 1 < len(drivers):
            from datetime import datetime, timezone
            from lbt1.models import ResearchStep
            all_steps.append(ResearchStep(
                timestamp=datetime.now(timezone.utc),
                step=f"Trying fallback: {drivers[i+1].__name__}",
                status="info",
                detail=f"{driver_cls.__name__} returned no key parts",
            ))

    # All dealers exhausted with no PNs.
    warnings: list[str] = []
    if last_exception is not None:
        warnings.append(f"Last dealer error: {last_exception}")
    result = _assemble_result(
        vin=normalized,
        profile=profile,
        parts=[],
        steps=all_steps,
        screenshots=[],
    )
    # Capture diagnostic record for autopilot offline analysis (only when
    # explicitly enabled via LBT1_DIAGNOSTICS=1 — zero overhead on live
    # user lookups).
    if diagnostics.diagnostics_enabled():
        diagnostics.record({
            "vin": normalized,
            "year": profile.year,
            "make": profile.make,
            "model": profile.model,
            "trim": profile.trim,
            "dealers_attempted": dealer_attempted,
            "last_exception": str(last_exception) if last_exception else None,
            "research_steps": [
                {"step": s.step, "status": s.status, "detail": s.detail}
                for s in all_steps
            ],
            "status": result.dealer_verification_status,
            "primary_pn": result.primary_result.oem_part_number if result.primary_result else None,
            "outcome": "unverified",
        })
    return result


def _driver_for_make(make: str) -> type | None:
    """Pick the primary scraper for a NHTSA-decoded make (legacy single-driver API).

    Most call sites should use _drivers_for_make() to get the full fallback chain.
    """
    drivers = _drivers_for_make(make)
    return drivers[0] if drivers else None


def _drivers_for_make(make: str) -> list[type]:
    """Return the ordered list of dealer scrapers to try for a make.

    The lookup pipeline calls each in turn — if the primary returns zero key
    PNs (catalog gap on that dealer), it falls back to the next.

    Fallback tiers per make (2026-05-28):
      Kia    → KiaOempartsDriver (Revolution Parts)
             → KiaUsOfficialDriver (parts.kia.com SimplePart)
      Hyundai → HyundaiOempartsDriver (Revolution Parts)
              → HyundaiOemPartDriver (Revolution Parts secondary)
              → HyundaiCanadaDriver (parts.hyundaicanada.com SimplePart)
      Genesis → GenesisOempartsDriver (Revolution Parts)

    SimplePart drivers hit a different upstream OEM feed than Revolution
    Parts and sometimes carry trims missing from RP — but they also miss
    newest model years (2026 confirmed empty on both feeds).
    """
    m = (make or "").strip().lower()
    if m == "kia":
        return [KiaOempartsDriver, KiaUsOfficialDriver,
                DuckDuckGoSearchFallbackDriver]
    if m == "hyundai":
        return [HyundaiOempartsDriver, HyundaiOemPartDriver, HyundaiCanadaDriver,
                DuckDuckGoSearchFallbackDriver]
    if m == "genesis":
        return [GenesisOempartsDriver, DuckDuckGoSearchFallbackDriver]
    if m == "toyota":
        return [ToyotaOempartsDriver, DuckDuckGoSearchFallbackDriver]
    return []


_KEY_TYPE_PRIORITY: dict[KeyType, int] = {
    KeyType.SMART_KEY: 0,
    KeyType.TRANSMITTER: 1,
    KeyType.KEYLESS_ENTRY_TX: 2,
    KeyType.REMOTE_CONTROL: 3,
    KeyType.KEYLESS_LOCK_PAD: 4,
    KeyType.UNKNOWN: 5,
}

_CATEGORY_PRIORITY = (
    ("keyless entry", 0),
    ("anti-theft", 1),
    ("anti theft", 1),
    ("electrical components", 2),
)


def _assemble_result(
    *,
    vin: str,
    profile: VehicleProfile,
    parts: list[OemPart],
    steps: list[ResearchStep],
    screenshots: list[str],
) -> LookupResult:
    """Sort parts by key-type then category, pick primary, score confidence.

    Sort priority:
      1. Specific key type (smart key > transmitter > keyless entry tx > remote > lock pad)
      2. Category (Keyless Entry Components > Anti-Theft > Electrical Components > other)
      3. Part number (stable order)
    """

    def category_priority(p: OemPart) -> int:
        cat = (p.category_path or "").lower()
        for needle, pri in _CATEGORY_PRIORITY:
            if needle in cat:
                return pri
        return 9

    def sort_key(p: OemPart) -> tuple[int, int, str]:
        return (
            _KEY_TYPE_PRIORITY.get(p.key_type, 9),
            category_priority(p),
            p.oem_part_number,
        )

    sorted_parts = sorted(parts, key=sort_key)
    primary = sorted_parts[0] if sorted_parts else None
    alternatives = sorted_parts[1:] if len(sorted_parts) > 1 else []

    # Strict OEM-verified-only policy for Kia/Hyundai/Genesis: never present
    # a primary PN unless the dealer catalogued it for THIS exact VIN's
    # year+trim+engine. The dealer's own fitment checker rejects close-but-
    # wrong PNs (verified 2026-05-28: 2025 95440-AA500 is "does not fit" on
    # the 2026 Elantra even though both are "SEL Sport 2.0L"). A wrong PN is
    # worse than no PN for a locksmith.
    if primary:
        status = "DEALER_VERIFIED_BY_VIN"
        score = 0.9 if len(sorted_parts) >= 2 else 0.8
        label = "HIGH" if score >= 0.8 else "MEDIUM"
    else:
        status = "NOT_DEALER_VERIFIED_BY_VIN"
        score = 0.0
        label = "LOW"

    # Only log "couldn't resolve" cases — useful for deployment brief review.
    # When dealer + NHTSA both can't pick a trim, we log VIN + profile for
    # later study to improve the matcher.
    if not primary:
        _log_unresolved(vin, profile, steps)

    return LookupResult(
        vin=vin,
        vehicle_profile=profile,
        dealer_verification_status=status,
        primary_result=primary,
        alternative_matches=alternatives,
        confidence_score=score,
        confidence_label=label,
        research_steps=steps,
        source_screenshots=screenshots,
    )


def _log_unresolved(
    vin: str, profile: VehicleProfile, steps: list[ResearchStep]
) -> None:
    """Append unresolved VIN to data/unresolved.log so we can study failure
    patterns and improve the matcher for future deployment briefs.
    Best-effort, never raises."""
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
            },
            "last_steps": [
                {"step": s.step, "status": s.status, "detail": s.detail}
                for s in steps[-6:]
            ],
        }
        log_path = Path(config.DATA_DIR) / "unresolved.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:  # noqa: BLE001
        pass
