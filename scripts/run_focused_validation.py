"""Focused 8-VIN validation using ScrapFly's free tier (1k credits/mo).

Picks a representative sample:
  - 2 previously-failed Kia VINs (validates the soft-chooser bug fix)
  - 1 previously-failed Hyundai Elantra (validates multi-trim NHTSA matcher)
  - 5 new 2017–2019 VINs (validates broader year coverage)

Budget: ~32 fetches × 21 credits = ~672 ScrapFly credits — fits in 1k free.
Writes to data/v1_run/focused_results.csv + focused_results.jsonl.
"""

from __future__ import annotations

import asyncio
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lbt1 import pipeline  # noqa: E402

# 8 VINs — purpose-built sample for $0 validation.
VINS: list[tuple[str, str]] = [
    # — Previously-failed cases (validating bug fixes)
    ("KNDJ23AUXL7735176", "2020 Kia Soul — soft-chooser bug fix"),
    ("5XYK6CAFXPG116936", "2023 Kia Sportage X-LINE — soft-chooser bug fix"),
    ("5NPD84LF1LH559355", "2020 Hyundai Elantra — multi-trim NHTSA match"),
    # — New 2017–2019 VINs (validating year coverage)
    ("5NPD84LFXHH074817", "2017 Hyundai Elantra"),
    ("5NPE34AB1HH562511", "2017 Hyundai Sonata"),
    ("KM8J3CA25JU630050", "2018 Hyundai Tucson"),
    ("KNDPN3AC5H7214690", "2017 Kia Sportage"),
    ("3KPFL4A76JE257547", "2018 Kia Forte"),
]

BATCH_SIZE = 2

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "v1_run"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CSV_PATH = OUT_DIR / "focused_results.csv"
JSONL_PATH = OUT_DIR / "focused_results.jsonl"

CSV_FIELDS = [
    "i", "vin", "purpose", "year", "make", "model", "trim",
    "status", "primary_pn", "primary_name", "alternates",
    "duration_s", "confidence_label",
]


async def run_one(i: int, vin: str, purpose: str) -> dict:
    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(pipeline.lookup(vin), timeout=300.0)
    except asyncio.TimeoutError:
        return {
            "i": i, "vin": vin, "purpose": purpose,
            "duration_s": int(time.monotonic() - t0),
            "status": "TIMEOUT",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "i": i, "vin": vin, "purpose": purpose,
            "duration_s": int(time.monotonic() - t0),
            "status": "ERROR", "error": str(exc),
        }

    p = result.vehicle_profile
    primary = result.primary_result
    alts = [a.oem_part_number for a in result.alternative_matches]
    return {
        "i": i,
        "vin": vin,
        "purpose": purpose,
        "year": p.year,
        "make": p.make,
        "model": p.model,
        "trim": p.trim,
        "status": result.dealer_verification_status,
        "primary_pn": primary.oem_part_number if primary else None,
        "primary_name": primary.part_name if primary else None,
        "alternates": ", ".join(alts),
        "duration_s": int(time.monotonic() - t0),
        "confidence_label": result.confidence_label,
        "_full": result.model_dump(mode="json"),
    }


def format_row(r: dict) -> str:
    status_tag = "VER" if r.get("status") == "DEALER_VERIFIED_BY_VIN" else "NV "
    vehicle = " ".join(str(x) for x in (r.get("year"), r.get("make"), r.get("model"), r.get("trim") or "") if x)
    primary = r.get("primary_pn") or "(none)"
    name = (r.get("primary_name") or "")[:30]
    alts = r.get("alternates") or "—"
    return (
        f"[{r['i']+1}] {status_tag} {r['vin']:18s} | {r.get('purpose','')[:38]:38s} | "
        f"{vehicle[:30]:30s} | PN={primary:14s} ({name:30s}) "
        f"alts={alts[:55]:55s} | {r['duration_s']:>3}s {r.get('confidence_label','')}"
    )


def save(rows: list[dict]) -> None:
    for p in (CSV_PATH, JSONL_PATH):
        try:
            p.unlink()
        except FileNotFoundError:
            pass

    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k) for k in CSV_FIELDS})

    with JSONL_PATH.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")


def print_summary(rows: list[dict]) -> None:
    total = len(rows)
    verified = sum(1 for r in rows if r.get("status") == "DEALER_VERIFIED_BY_VIN")
    failed_kia_fixed = [
        r for r in rows
        if "soft-chooser" in (r.get("purpose") or "") and r.get("status") == "DEALER_VERIFIED_BY_VIN"
    ]
    failed_hyundai_fixed = [
        r for r in rows
        if "multi-trim" in (r.get("purpose") or "") and r.get("status") == "DEALER_VERIFIED_BY_VIN"
    ]
    year_coverage = [
        r for r in rows
        if "2017" in (r.get("purpose") or "") or "2018" in (r.get("purpose") or "")
    ]
    year_verified = sum(1 for r in year_coverage if r.get("status") == "DEALER_VERIFIED_BY_VIN")

    print()
    print("==================== FOCUSED VALIDATION ====================")
    print(f"Overall            : {verified}/{total} verified ({verified/total*100:.0f}%)")
    print()
    print("Bug-fix validation :")
    print(f"  Kia soft-chooser     : {len(failed_kia_fixed)}/2 verified")
    print(f"  Hyundai multi-trim   : {len(failed_hyundai_fixed)}/1 verified")
    print()
    print("Year coverage 2017–2018:")
    print(f"  {year_verified}/{len(year_coverage)} verified")
    for r in year_coverage:
        status = "OK " if r.get("status") == "DEALER_VERIFIED_BY_VIN" else "NO "
        print(f"    [{status}] {r['vin']} | {r.get('year')} {r.get('make')} {r.get('model')}")


async def main() -> None:
    print(f"Focused validation: {len(VINS)} VINs through ScrapFly (free tier)")
    print(f"Started: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")

    results: list[dict] = []
    batches = [VINS[i : i + BATCH_SIZE] for i in range(0, len(VINS), BATCH_SIZE)]
    t_start = time.monotonic()

    for batch_n, batch in enumerate(batches, 1):
        print(f"--- Batch {batch_n}/{len(batches)} ---")
        offset = (batch_n - 1) * BATCH_SIZE
        batch_results = await asyncio.gather(
            *[run_one(offset + i, vin, purpose) for i, (vin, purpose) in enumerate(batch)],
            return_exceptions=False,
        )
        for r in batch_results:
            print(format_row(r))
        results.extend(batch_results)

    save(results)
    elapsed = int(time.monotonic() - t_start)
    print(f"\nFinished in {elapsed}s. Results: {CSV_PATH}")
    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
