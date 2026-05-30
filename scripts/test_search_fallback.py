"""End-to-end test of the new DDG-search-fallback against previously
unsolved VINs. If this works, coverage jumps significantly."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_DIAGNOSTICS"] = "1"

from lbt1 import pipeline  # noqa: E402

TARGETS = [
    # Toyota Camry 2024 SE — was 0/X (no Toyota coverage)
    ("4T1G11AK6R0123456", "2024 Toyota Camry SE"),
    # Hyundai Sonata SEL 2024 — failed in c=2 retest (synthetic VIN)
    ("KMHL14JA3RJ254507", "2024 Hyundai Sonata SEL"),
    # Kia EV6 2024 — was 0/3 (trim disambiguation issue)
    ("KNDC34LD0RP458006", "2024 Kia EV6 Light/Wind"),
]


async def main() -> None:
    for vin, label in TARGETS:
        print("=" * 90)
        print(f"VIN: {vin}  ({label})")
        t0 = time.monotonic()
        try:
            result = await pipeline.lookup(vin)
        except Exception as exc:
            print(f"  EXCEPTION: {exc}")
            continue
        duration = int(time.monotonic() - t0)
        primary = result.primary_result
        alts = result.alternative_matches
        print(f"  duration: {duration}s")
        print(f"  status:   {result.dealer_verification_status}")
        print(f"  primary:  {primary.oem_part_number if primary else '—'}")
        if primary:
            print(f"  source:   {primary.source_url}")
        print(f"  alts:     {[a.oem_part_number for a in alts]}")


if __name__ == "__main__":
    asyncio.run(main())
