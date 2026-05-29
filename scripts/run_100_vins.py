"""Run 100-VIN free-tier validation: 4-concurrent on Apify, fall back to
ScrapFly for any failures.

Input: data/v1_run/hyundai_kia_100_vins.csv (year,make,model,vin,source_url)
Output:
  - data/v1_run/results_100.csv  — flat summary
  - data/v1_run/results_100.jsonl — full LookupResult per VIN
  - data/v1_run/run_100.log     — progress log
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lbt1 import config, pipeline  # noqa: E402
from lbt1.scrapers.backends import get_backend  # noqa: E402

CSV_IN = Path(__file__).resolve().parents[1] / "data" / "v1_run" / "hyundai_kia_100_vins.csv"
OUT_DIR = CSV_IN.parent
CSV_OUT = OUT_DIR / "results_100.csv"
JSONL_OUT = OUT_DIR / "results_100.jsonl"

BATCH_SIZE = 4  # Apify free tier safety
APIFY_TIMEOUT_S = 240.0
SCRAPFLY_TIMEOUT_S = 180.0


def load_vins() -> list[dict]:
    rows = []
    with CSV_IN.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            vin = (r.get("vin") or "").strip()
            if not vin:
                continue
            rows.append({
                "vin": vin,
                "year": r.get("year"),
                "make": r.get("make"),
                "model": r.get("model"),
            })
    return rows


async def lookup_with_backend(vin: str, backend_name: str, timeout: float) -> dict:
    """Run lookup with a specific backend (overrides env)."""
    os.environ["LBT1_SCRAPE_BACKEND"] = backend_name
    # Bust the cached driver type so factory re-selects on next pipeline call.
    config.SCRAPE_BACKEND = backend_name

    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(pipeline.lookup(vin), timeout=timeout)
    except asyncio.TimeoutError:
        return {"vin": vin, "status": "TIMEOUT", "backend": backend_name,
                "duration_s": int(time.monotonic() - t0)}
    except Exception as exc:  # noqa: BLE001
        return {"vin": vin, "status": "ERROR", "backend": backend_name,
                "error": str(exc)[:200],
                "duration_s": int(time.monotonic() - t0)}

    p = result.vehicle_profile
    primary = result.primary_result
    alts = [a.oem_part_number for a in result.alternative_matches]
    return {
        "vin": vin, "backend": backend_name,
        "year": p.year, "make": p.make, "model": p.model, "trim": p.trim,
        "status": result.dealer_verification_status,
        "primary_pn": primary.oem_part_number if primary else None,
        "primary_name": primary.part_name if primary else None,
        "alternates": ", ".join(alts),
        "duration_s": int(time.monotonic() - t0),
        "confidence_label": result.confidence_label,
        "_full": result.model_dump(mode="json"),
    }


def fmt(r: dict, i: int) -> str:
    tag = "VER" if r.get("status") == "DEALER_VERIFIED_BY_VIN" else "NV "
    backend = (r.get("backend") or "?")[:3].upper()
    vehicle = " ".join(
        str(x) for x in (r.get("year"), r.get("make"), r.get("model"), r.get("trim") or "") if x
    )
    primary = r.get("primary_pn") or "(none)"
    name = (r.get("primary_name") or "")[:22]
    alts = (r.get("alternates") or "—")[:40]
    return (
        f"[{i+1:3}] {tag} ({backend}) {r['vin']:18s} | {vehicle[:30]:30s} | "
        f"PN={primary:14s} ({name:22s}) alts={alts:40s} | "
        f"{r.get('duration_s',0):>3}s"
    )


async def main() -> None:
    vins = load_vins()
    print(f"Loaded {len(vins)} VINs from {CSV_IN}", flush=True)
    print(f"Started: {datetime.now(timezone.utc).isoformat(timespec='seconds')}", flush=True)
    print(f"Pass 1: Apify, concurrency {BATCH_SIZE}\n", flush=True)
    t_start = time.monotonic()

    # ────── Pass 1: Apify, all 100 ──────────────────────────────────────
    results: dict[str, dict] = {}  # vin → result
    batches = [vins[i : i + BATCH_SIZE] for i in range(0, len(vins), BATCH_SIZE)]

    for batch_n, batch in enumerate(batches, 1):
        print(f"--- Apify batch {batch_n}/{len(batches)} ---", flush=True)
        offset = (batch_n - 1) * BATCH_SIZE
        batch_results = await asyncio.gather(
            *[lookup_with_backend(row["vin"], "apify", APIFY_TIMEOUT_S) for row in batch]
        )
        for r in batch_results:
            results[r["vin"]] = r
            print(fmt(r, offset + batch_results.index(r)), flush=True)

    pass1_elapsed = int(time.monotonic() - t_start)
    pass1_verified = sum(1 for r in results.values() if r.get("status") == "DEALER_VERIFIED_BY_VIN")
    print(f"\nPass 1 done in {pass1_elapsed}s. Apify verified: {pass1_verified}/{len(vins)}", flush=True)

    # ────── Pass 2: ScrapFly for the failures (budget-limited) ──────────
    failures = [v for v in vins if results[v["vin"]].get("status") != "DEALER_VERIFIED_BY_VIN"]
    # ScrapFly free tier has ~423 credits ≈ ~20 fetches ≈ 5 VINs max. Be safe.
    SCRAPFLY_BUDGET = 5
    retry_list = failures[:SCRAPFLY_BUDGET]
    skip_count = max(0, len(failures) - SCRAPFLY_BUDGET)
    if retry_list:
        print(f"\nPass 2: ScrapFly retry, {len(retry_list)} VINs "
              f"(skipping {skip_count} more due to credit limit)\n", flush=True)
        retry_batches = [retry_list[i : i + BATCH_SIZE]
                         for i in range(0, len(retry_list), BATCH_SIZE)]
        for batch_n, batch in enumerate(retry_batches, 1):
            print(f"--- ScrapFly retry batch {batch_n}/{len(retry_batches)} ---", flush=True)
            batch_results = await asyncio.gather(
                *[lookup_with_backend(row["vin"], "scrapfly", SCRAPFLY_TIMEOUT_S) for row in batch]
            )
            for r in batch_results:
                # ScrapFly wins if it succeeds, otherwise keep Apify's record.
                if r.get("status") == "DEALER_VERIFIED_BY_VIN":
                    results[r["vin"]] = r
                else:
                    # Merge: keep best info available
                    r["_was_apify_failure"] = True
                    results[r["vin"]] = r
                print(fmt(r, list(results.keys()).index(r["vin"])), flush=True)

    # ────── Save outputs ────────────────────────────────────────────────
    all_results = [results[v["vin"]] for v in vins]
    with JSONL_OUT.open("w", encoding="utf-8") as f:
        for r in all_results:
            f.write(json.dumps(r, default=str) + "\n")

    fields = ["vin", "backend", "year", "make", "model", "trim", "status",
              "primary_pn", "primary_name", "alternates", "duration_s",
              "confidence_label"]
    with CSV_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in all_results:
            w.writerow({k: r.get(k) for k in fields})

    # ────── Summary ─────────────────────────────────────────────────────
    elapsed = int(time.monotonic() - t_start)
    verified = sum(1 for r in all_results if r.get("status") == "DEALER_VERIFIED_BY_VIN")

    by_make: Counter = Counter()
    by_make_total: Counter = Counter()
    by_year: Counter = Counter()
    by_year_total: Counter = Counter()
    for r in all_results:
        make = (r.get("make") or "?").title()
        year = str(r.get("year") or "?")
        by_make_total[make] += 1
        by_year_total[year] += 1
        if r.get("status") == "DEALER_VERIFIED_BY_VIN":
            by_make[make] += 1
            by_year[year] += 1

    print(f"\n==================== 100-VIN SUMMARY ====================", flush=True)
    print(f"Total VINs       : {len(vins)}", flush=True)
    print(f"Verified         : {verified} ({verified/len(vins)*100:.0f}%)", flush=True)
    print(f"Total time       : {elapsed}s", flush=True)
    print(f"\nBy make:", flush=True)
    for make in sorted(by_make_total.keys()):
        v, t = by_make[make], by_make_total[make]
        print(f"  {make:10s}  {v}/{t} ({v/t*100:.0f}%)", flush=True)
    print(f"\nBy year:", flush=True)
    for year in sorted(by_year_total.keys()):
        v, t = by_year[year], by_year_total[year]
        print(f"  {year}  {v}/{t} ({v/t*100:.0f}%)", flush=True)
    print(f"\nResults saved to: {CSV_OUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
