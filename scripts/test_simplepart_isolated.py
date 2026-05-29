"""Direct exercise of HyundaiCanadaDriver / KiaUsOfficialDriver against
known-good VINs (the ones we confirmed return non-empty CreateVinLinks
responses). The pipeline normally short-circuits on Revolution Parts
hits, so this is the only way to verify the SimplePart driver actually
harvests PNs end to end.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.models import VehicleProfile  # noqa: E402
from lbt1.scrapers.simplepart import HyundaiCanadaDriver, KiaUsOfficialDriver  # noqa: E402
from lbt1.vin import decoder  # noqa: E402


CASES = [
    # (VIN, driver_cls)
    ("5NPD84LFXHH074817", HyundaiCanadaDriver),  # 2017 Elantra — confirmed has data
    ("5XYP5DHC5NG256061", KiaUsOfficialDriver),  # 2022 Telluride — confirmed has data
    ("KMHLM4DG3TU122912", HyundaiCanadaDriver),  # 2026 Elantra — expected empty
]


async def main() -> None:
    for vin, driver_cls in CASES:
        print("=" * 100)
        print(f"VIN: {vin}  driver: {driver_cls.__name__}")
        try:
            profile = await decoder.decode(vin)
            print(f"  NHTSA: {profile.display}")
        except Exception as exc:
            print(f"  NHTSA error: {exc}")
            profile = VehicleProfile(vin=vin)

        driver = driver_cls()
        try:
            parts = await driver.lookup_vin(vin, profile)
        finally:
            try:
                await driver.backend.close()
            except Exception:
                pass

        print(f"  → {len(parts)} part(s) returned")
        for p in parts[:10]:
            print(f"     pn={p.oem_part_number!r} name={p.part_name!r} key_type={p.key_type.value}")
            print(f"        src={p.source_url}")
        print(f"  research steps ({len(driver.steps)}):")
        for s in driver.steps[-8:]:
            print(f"     [{s.status}] {s.step}  -- {s.detail or ''}")


if __name__ == "__main__":
    asyncio.run(main())
