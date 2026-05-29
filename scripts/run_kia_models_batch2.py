"""Apify run: remaining 11 Kia VINs across Niro / Carnival / Seltos / K5
that weren't tested in the ScrapFly batch 1.

Apify's free $5/mo platform credit easily covers ~44 fetches.
Concurrency: 4 (Apify free tier safety).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Force apify backend regardless of .env setting.
os.environ["LBT1_SCRAPE_BACKEND"] = "apify"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lbt1 import pipeline  # noqa: E402

VINS: list[tuple[str, str]] = [
    # 2018 Niros (legacy era)
    ("KNDCC3LCXJ5143683", "2018 Kia Niro"),
    ("KNDCB3LC9J5127364", "2018 Kia Niro"),
    # Carnival year coverage
    ("KNDNB5K38S6455229", "2025 Kia Carnival"),
    ("KNDNE5H33R6344810", "2024 Kia Carnival"),
    ("KNDNC5H3XR6377020", "2024 Kia Carnival"),
    # Seltos year coverage
    ("KNDEUCAA1P7433685", "2023 Kia Seltos"),
    ("KNDEUCAA2R7498936", "2024 Kia Seltos"),
    ("KNDEU2AA3N7345700", "2022 Kia Seltos"),
    # K5 year coverage
    ("5XXG64J28NG083090", "2022 Kia K5"),
    ("KNAG24J71S5358819", "2025 Kia K5"),
    ("5XXG64J2XPG169097", "2023 Kia K5"),
]

BATCH_SIZE = 4
OUT = Path(__file__).resolve().parents[1] / "data" / "v1_run" / "kia_models_batch2.jsonl"
OUT.parent.mkdir(parents=True, exist_ok=True)


async def run_one(i: int, vin: str, purpose: str) -> dict:
    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(pipeline.lookup(vin), timeout=420.0)
    except asyncio.TimeoutError:
        return {"i": i, "vin": vin, "purpose": purpose, "status": "TIMEOUT",
                "duration_s": int(time.monotonic() - t0)}
    except Exception as exc:  # noqa: BLE001
        return {"i": i, "vin": vin, "purpose": purpose, "status": "ERROR",
                "error": str(exc), "duration_s": int(time.monotonic() - t0)}
    p = result.vehicle_profile
    primary = result.primary_result
    alts = [a.oem_part_number for a in result.alternative_matches]
    return {
        "i": i, "vin": vin, "purpose": purpose,
        "year": p.year, "make": p.make, "model": p.model, "trim": p.trim,
        "status": result.dealer_verification_status,
        "primary_pn": primary.oem_part_number if primary else None,
        "primary_name": primary.part_name if primary else None,
        "alternates": ", ".join(alts),
        "duration_s": int(time.monotonic() - t0),
        "confidence_label": result.confidence_label,
        "_full": result.model_dump(mode="json"),
    }


async def main() -> None:
    print(f"Kia models batch 2: {len(VINS)} VINs on Apify (concurrency {BATCH_SIZE})")
    print(f"Started: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n", flush=True)
    t0 = time.monotonic()

    results: list[dict] = []
    batches = [VINS[i : i + BATCH_SIZE] for i in range(0, len(VINS), BATCH_SIZE)]
    for batch_n, batch in enumerate(batches, 1):
        print(f"--- Batch {batch_n}/{len(batches)} ---", flush=True)
        offset = (batch_n - 1) * BATCH_SIZE
        batch_results = await asyncio.gather(
            *[run_one(offset + i, vin, purpose) for i, (vin, purpose) in enumerate(batch)]
        )
        for r in batch_results:
            tag = "VER" if r.get("status") == "DEALER_VERIFIED_BY_VIN" else "NV "
            vehicle = " ".join(
                str(x) for x in (r.get("year"), r.get("make"), r.get("model"), r.get("trim") or "") if x
            )
            primary = r.get("primary_pn") or "(none)"
            name = (r.get("primary_name") or "")[:25]
            alts = (r.get("alternates") or "—")[:45]
            print(
                f"[{r['i']+1:2}] {tag} {r['vin']:18s} | {r.get('purpose','')[:24]:24s} | "
                f"{vehicle[:28]:28s} | PN={primary:14s} ({name:25s}) "
                f"alts={alts:45s} | {r['duration_s']:>3}s {r.get('confidence_label','')}",
                flush=True,
            )
        results.extend(batch_results)

    with OUT.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, default=str) + "\n")

    elapsed = int(time.monotonic() - t0)
    verified = sum(1 for r in results if r.get("status") == "DEALER_VERIFIED_BY_VIN")
    print(f"\nDone in {elapsed}s. Verified: {verified}/{len(VINS)}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
