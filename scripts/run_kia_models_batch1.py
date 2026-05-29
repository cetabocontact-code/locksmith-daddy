"""ScrapFly run: 5 strategic Kia VINs covering all 4 unverified models
(Niro, Carnival, Seltos, K5) plus one legacy 2017 Niro. Uses concurrency=5
to drain ~420 of ~423 remaining ScrapFly credits in ~60 seconds."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lbt1 import pipeline  # noqa: E402

VINS: list[tuple[str, str]] = [
    ("KNDCC3LC5H5090806", "2017 Kia Niro — legacy test"),
    ("KNDCT3LE8R5130346", "2024 Kia Niro — modern"),
    ("KNDNB4H32P6262664", "2023 Kia Carnival"),
    ("KNDETCA71R7567252", "2024 Kia Seltos"),
    ("5XXG64J26RG239648", "2024 Kia K5"),
]

BATCH_SIZE = 5  # ScrapFly free tier allows 5 concurrent
OUT = Path(__file__).resolve().parents[1] / "data" / "v1_run" / "kia_models_batch1.jsonl"
OUT.parent.mkdir(parents=True, exist_ok=True)


async def run_one(i: int, vin: str, purpose: str) -> dict:
    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(pipeline.lookup(vin), timeout=300.0)
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
    print(f"Kia models batch 1: {len(VINS)} VINs on ScrapFly (concurrency 5)")
    print(f"Started: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n", flush=True)
    t0 = time.monotonic()

    # All 5 in one go — ScrapFly free tier supports concurrency=5.
    results = await asyncio.gather(
        *[run_one(i, vin, purpose) for i, (vin, purpose) in enumerate(VINS)]
    )

    # Print each result.
    for r in results:
        tag = "VER" if r.get("status") == "DEALER_VERIFIED_BY_VIN" else "NV "
        vehicle = " ".join(
            str(x) for x in (r.get("year"), r.get("make"), r.get("model"), r.get("trim") or "") if x
        )
        primary = r.get("primary_pn") or "(none)"
        name = (r.get("primary_name") or "")[:30]
        alts = (r.get("alternates") or "—")[:50]
        print(
            f"[{r['i']+1}] {tag} {r['vin']:18s} | {r.get('purpose','')[:30]:30s} | "
            f"{vehicle[:30]:30s} | PN={primary:14s} ({name:30s}) "
            f"alts={alts:50s} | {r['duration_s']:>3}s {r.get('confidence_label','')}",
            flush=True,
        )

    # Save.
    with OUT.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, default=str) + "\n")

    elapsed = int(time.monotonic() - t0)
    verified = sum(1 for r in results if r.get("status") == "DEALER_VERIFIED_BY_VIN")
    print(f"\nDone in {elapsed}s. Verified: {verified}/{len(VINS)}", flush=True)
    print(f"Results: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
