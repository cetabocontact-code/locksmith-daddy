"""Autopilot AM session #2: Bug #2 hypothesis test.

Hypothesis: when Revolution Parts returns a /v?vin=... placeholder page
(no real /v- candidates), the dealer might be doing server-side async
lookup that resolves a second later. Re-fetching after 2-3s might give
us the real chooser HTML.

Test plan:
  1. Take 3 VINs that we KNOW return the placeholder pattern (from
     Bug #1 diagnostic — all 3 Sonata VINs).
  2. Fetch /search?search_str={VIN} directly via the backend.
  3. If returned URL pattern matches /v?vin=... (placeholder), wait 3s
     then re-fetch the SAME final_url.
  4. Compare: does the second fetch have /v- candidates that the first
     lacked?

Cost: 3 VINs * 2 fetches * ~50 credits = ~300 credits ($0.04).
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"
os.environ["LBT1_DIAGNOSTICS"] = "1"

from lbt1.scrapers.backends import get_backend  # noqa: E402

VINS = [
    "5NPEH4J20R2028972",  # 2024 Sonata Limited — confirmed placeholder
    "5NPEG4JA1R5364137",  # 2024 Sonata SE — confirmed placeholder
    "5NPEL4JA2S5390229",  # 2025 Sonata SEL — confirmed placeholder
]
SEARCH_BASE = "https://hyundai.oempartsonline.com/search?search_str="


def count_v_candidates(html: str) -> int:
    """Count /v- href occurrences with year segment."""
    import re
    return len(re.findall(r'href="(/v-\d{4}-[^"]+)"', html or ""))


async def main() -> None:
    backend = get_backend()
    try:
        for vin in VINS:
            print("=" * 90)
            print(f"VIN: {vin}")
            url = SEARCH_BASE + vin
            r1 = await backend.fetch(url)
            yc1 = count_v_candidates(r1.html)
            print(f"  Attempt 1: status={r1.status}  final={r1.final_url}")
            print(f"             year-segment candidates: {yc1}  htmllen={len(r1.html or '')}")

            # Is this the placeholder pattern?
            if "/v?vin=" in r1.final_url or yc1 == 0:
                print(f"  >>> PLACEHOLDER detected, waiting 3s then re-fetching final_url")
                await asyncio.sleep(3)
                r2 = await backend.fetch(r1.final_url)
                yc2 = count_v_candidates(r2.html)
                print(f"  Attempt 2: status={r2.status}  final={r2.final_url}")
                print(f"             year-segment candidates: {yc2}  htmllen={len(r2.html or '')}")
                if yc2 > yc1:
                    print(f"  ✓ HYPOTHESIS CONFIRMED: retry revealed {yc2} new candidates")
                else:
                    print(f"  ✗ HYPOTHESIS REJECTED: still no real candidates after retry")
            else:
                print(f"  (no placeholder — first response had {yc1} candidates)")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
