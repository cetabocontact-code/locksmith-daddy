"""Autopilot AM session: deep-dive on Hyundai Sonata 23% coverage gap.

Picks 3 VINs that genuinely failed (still failing after c=2 retest = not
throttle artifacts) and runs them through pipeline with LBT1_DIAGNOSTICS=1.
The full research-step trail is captured to data/diagnostics/{date}.jsonl
for offline analysis — minimizes ScrapFly burn (3 VINs, ~$0.15) and gives
us everything we need to identify the failure mode.

After this script runs, the next morning step reads the JSONL to
hypothesize root cause and propose a code fix.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# CRITICAL: enable diagnostic capture so research_steps are persisted.
os.environ["LBT1_DIAGNOSTICS"] = "1"

from lbt1 import pipeline  # noqa: E402


# Three Sonata VINs that genuinely failed (confirmed by c=2 retest = not
# throttle artifacts). Mix of trims/years to look for patterns.
TARGETS = [
    ("5NPEH4J20R2028972", "2024 Sonata Limited"),
    ("5NPEG4JA1R5364137", "2024 Sonata SE"),
    ("5NPEL4JA2S5390229", "2025 Sonata SEL"),
]


async def main() -> None:
    for vin, label in TARGETS:
        print("=" * 80)
        print(f"VIN: {vin}  ({label})")
        print("=" * 80)
        t0 = time.monotonic()
        try:
            result = await pipeline.lookup(vin)
        except Exception as exc:
            print(f"  EXCEPTION: {type(exc).__name__}: {exc}")
            continue
        duration = int(time.monotonic() - t0)
        primary = result.primary_result
        alts = result.alternative_matches
        print(f"  duration: {duration}s")
        print(f"  status:   {result.dealer_verification_status}")
        print(f"  primary:  {primary.oem_part_number if primary else '—'}")
        print(f"  alts:     {[a.oem_part_number for a in alts]}")
        print(f"  warnings: {result.warnings}")


if __name__ == "__main__":
    asyncio.run(main())
