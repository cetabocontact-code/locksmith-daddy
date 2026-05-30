"""Test the 4 hardest known-unsolved real-VIN cases against the new
DDG fallback. These are NOT synthetic — they're real production cars
whose fobs we genuinely couldn't find before."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_DIAGNOSTICS"] = "1"

from lbt1 import pipeline  # noqa: E402

# All real-pattern VINs from the 30-VIN regression test that FAILED
HARDEST = [
    ("KM8R5DHC3SU081016", "2025 Hyundai Palisade Limited"),
    ("5NMP34GL7SN375837", "2025 Hyundai Santa Fe XRT"),
    ("KMTG54TE9SJ003881", "2025 Genesis G70 Sport Advanced"),
    ("KNDC34LD0RP458006", "2024 Kia EV6 Light/Wind"),
]


async def main() -> None:
    for vin, label in HARDEST:
        print("=" * 90)
        print(f"VIN: {vin}  ({label})")
        t0 = time.monotonic()
        try:
            result = await pipeline.lookup(vin)
        except Exception as exc:
            print(f"  EXCEPTION: {exc}")
            continue
        dur = int(time.monotonic() - t0)
        primary = result.primary_result
        print(f"  duration: {dur}s")
        print(f"  status:   {result.dealer_verification_status}")
        print(f"  primary:  {primary.oem_part_number if primary else '—'}")
        if primary:
            print(f"  source:   {primary.source_url}")
        print(f"  alts:     {[a.oem_part_number for a in result.alternative_matches]}")


if __name__ == "__main__":
    asyncio.run(main())
