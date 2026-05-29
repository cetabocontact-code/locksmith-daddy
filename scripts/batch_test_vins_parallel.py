"""Parallel version of batch_test_vins.py. Runs VINs concurrently with a
configurable worker pool. Each VIN still goes through the full pipeline
(no short-circuiting), but multiple VINs are in-flight at once so we
saturate ScrapFly's request budget instead of waiting sequentially.

Usage:
    python scripts/batch_test_vins_parallel.py data/2024_2025_vins.csv \
        data/2024_2025_report.csv --concurrency 10
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lbt1 import pipeline  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input_csv", type=Path)
    p.add_argument("output_csv", type=Path, nargs="?", default=None)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--concurrency", "-c", type=int, default=10,
                   help="Max concurrent VIN lookups (default 10).")
    return p.parse_args()


def load_input(path: Path) -> list[dict[str, str]]:
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            vin = (r.get("VIN") or r.get("vin") or "").strip()
            if not vin:
                continue
            expected = (r.get("expected_pns") or r.get("Expected PNs")
                        or r.get("expected_pn") or "")
            for i in range(1, 10):
                key = f"PN {i}"
                if key in r and r[key].strip():
                    expected = (expected + "," + r[key]).strip(",")
            rows.append({"vin": vin, "expected_pns": expected})
    return rows


def normalize_pn_set(text: str) -> set[str]:
    out = set()
    for raw in (text or "").replace(";", ",").split(","):
        c = raw.strip().upper().replace(" ", "").replace("-", "")
        if c:
            out.add(c)
    return out


async def lookup_one(
    row: dict[str, str], idx: int, total: int, sem: asyncio.Semaphore
) -> dict[str, object]:
    vin = row["vin"]
    expected_raw = row.get("expected_pns", "")
    expected_set = normalize_pn_set(expected_raw)
    t0 = time.monotonic()

    async with sem:
        try:
            result = await pipeline.lookup(vin)
        except Exception as exc:  # noqa: BLE001
            duration = int(round(time.monotonic() - t0))
            print(f"  [ERR  {idx:3d}/{total}] {vin}  {duration}s  {exc}", flush=True)
            return {
                "vin": vin, "year": "", "make": "", "model": "", "trim": "",
                "status": "ERROR", "primary_pn": "", "all_pns": "",
                "expected_pns": expected_raw, "matched": "error",
                "duration_s": duration, "error": str(exc),
            }

    duration = int(round(time.monotonic() - t0))
    profile = result.vehicle_profile
    primary = result.primary_result
    all_pns = []
    if primary:
        all_pns.append(primary.oem_part_number)
    for a in result.alternative_matches:
        all_pns.append(a.oem_part_number)
    all_set = normalize_pn_set(",".join(all_pns))

    if not expected_set:
        matched = "unknown"
    elif expected_set.issubset(all_set):
        matched = "all"
    elif expected_set & all_set:
        matched = "partial"
    else:
        matched = "none"

    short_status = "✓" if result.dealer_verification_status == "DEALER_VERIFIED_BY_VIN" else "·"
    pn = primary.oem_part_number if primary else "—"
    print(f"  [{short_status} {idx:3d}/{total}] {vin}  {duration:3d}s  "
          f"{profile.year} {profile.make} {profile.model} {(profile.trim or '')[:20]:20s}  "
          f"pn={pn}", flush=True)

    return {
        "vin": vin,
        "year": profile.year or "",
        "make": profile.make or "",
        "model": profile.model or "",
        "trim": profile.trim or "",
        "status": result.dealer_verification_status,
        "primary_pn": primary.oem_part_number if primary else "",
        "all_pns": ", ".join(all_pns),
        "expected_pns": expected_raw,
        "matched": matched,
        "duration_s": duration,
        "error": "; ".join(result.warnings) if result.warnings else "",
    }


async def run() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.WARNING)

    rows = load_input(args.input_csv)
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print(f"No VINs in {args.input_csv}", file=sys.stderr)
        sys.exit(1)

    output = args.output_csv or args.input_csv.with_name(args.input_csv.stem + "_report.csv")
    fieldnames = ["vin", "year", "make", "model", "trim", "status", "primary_pn",
                  "all_pns", "expected_pns", "matched", "duration_s", "error"]

    print(f"Running {len(rows)} VIN(s) at concurrency={args.concurrency}.")
    print(f"Writing report to: {output}")
    start_batch = time.monotonic()

    sem = asyncio.Semaphore(args.concurrency)
    tasks = [
        asyncio.create_task(lookup_one(row, i + 1, len(rows), sem))
        for i, row in enumerate(rows)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=False)

    # Write in input order
    with output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in results:
            w.writerow(r)

    elapsed = int(time.monotonic() - start_batch)
    summary = {"all": 0, "partial": 0, "none": 0, "unknown": 0, "error": 0}
    for r in results:
        summary[r["matched"]] += 1
    print()
    print(f"Done in {elapsed}s ({elapsed//60}m{elapsed%60}s). Report: {output}")
    print(f"  All expected PNs matched : {summary['all']}")
    print(f"  Partial match            : {summary['partial']}")
    print(f"  No match                 : {summary['none']}")
    print(f"  Errors                   : {summary['error']}")
    print(f"  No expected PNs to check : {summary['unknown']}")
    verified = sum(1 for r in results if r["status"] == "DEALER_VERIFIED_BY_VIN")
    print(f"  DEALER_VERIFIED_BY_VIN   : {verified}/{len(results)} "
          f"({verified/len(results)*100:.1f}%)")


if __name__ == "__main__":
    asyncio.run(run())
