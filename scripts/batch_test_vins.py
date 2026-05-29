"""Run a batch of VINs through the lookup pipeline and write a comparison
report. Designed for the 50-VIN validation step before going live.

Usage:
    # CSV with header "VIN" and optionally "expected_pns" (comma-separated)
    python scripts/batch_test_vins.py data/test_vins_50.csv [output.csv]

The report columns:
    vin, year, make, model, trim, status, primary_pn, all_pns,
    expected_pns, matched, duration_s, error

`matched` is:
    "all"      — every expected PN appears in returned PNs
    "partial"  — some expected PNs appear
    "none"     — no expected PNs found
    "unknown"  — no expected_pns in input CSV
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
import time
from pathlib import Path

# Make sure lbt1 is importable when this script is run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lbt1 import pipeline  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input_csv", type=Path)
    p.add_argument(
        "output_csv",
        type=Path,
        nargs="?",
        default=None,
        help="Defaults to <input>_report.csv next to the input file.",
    )
    p.add_argument(
        "--limit", type=int, default=0, help="Stop after N VINs (0 = all)."
    )
    p.add_argument(
        "--verbose", action="store_true", help="Log each pipeline call's research steps."
    )
    return p.parse_args()


def load_input(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = []
        for r in reader:
            vin = (r.get("VIN") or r.get("vin") or "").strip()
            if not vin:
                continue
            expected = (
                r.get("expected_pns")
                or r.get("Expected PNs")
                or r.get("expected_pn")
                or ""
            )
            # Also accept "PN 1", "PN 2", ... columns (mirrors the training CSV format).
            for i in range(1, 10):
                key = f"PN {i}"
                if key in r and r[key].strip():
                    expected = (expected + "," + r[key]).strip(",")
            rows.append({"vin": vin, "expected_pns": expected})
        return rows


async def run() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    rows = load_input(args.input_csv)
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        print(f"No VINs found in {args.input_csv}", file=sys.stderr)
        sys.exit(1)

    output = args.output_csv or args.input_csv.with_name(
        args.input_csv.stem + "_report.csv"
    )
    fieldnames = [
        "vin", "year", "make", "model", "trim",
        "status", "primary_pn", "all_pns",
        "expected_pns", "matched", "duration_s", "error",
    ]

    print(f"Running {len(rows)} VIN(s). Writing report to: {output}")
    start_batch = time.monotonic()
    summary = {"all": 0, "partial": 0, "none": 0, "unknown": 0, "error": 0}

    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for i, row in enumerate(rows, 1):
            vin = row["vin"]
            expected_pns_raw = row.get("expected_pns", "")
            expected_set = _normalize_pn_set(expected_pns_raw)

            print(f"[{i}/{len(rows)}] {vin}", flush=True)
            t0 = time.monotonic()
            try:
                result = await pipeline.lookup(vin)
            except Exception as exc:  # noqa: BLE001
                duration = int(round(time.monotonic() - t0))
                writer.writerow({
                    "vin": vin,
                    "year": "", "make": "", "model": "", "trim": "",
                    "status": "ERROR",
                    "primary_pn": "",
                    "all_pns": "",
                    "expected_pns": expected_pns_raw,
                    "matched": "error",
                    "duration_s": duration,
                    "error": str(exc),
                })
                summary["error"] += 1
                continue

            duration = int(round(time.monotonic() - t0))
            profile = result.vehicle_profile
            primary = result.primary_result
            all_pns_list = []
            if primary:
                all_pns_list.append(primary.oem_part_number)
            for a in result.alternative_matches:
                all_pns_list.append(a.oem_part_number)
            all_pns_normalized = _normalize_pn_set(",".join(all_pns_list))

            if not expected_set:
                matched = "unknown"
            elif expected_set.issubset(all_pns_normalized):
                matched = "all"
            elif expected_set & all_pns_normalized:
                matched = "partial"
            else:
                matched = "none"
            summary[matched] += 1

            writer.writerow({
                "vin": vin,
                "year": profile.year or "",
                "make": profile.make or "",
                "model": profile.model or "",
                "trim": profile.trim or "",
                "status": result.dealer_verification_status,
                "primary_pn": primary.oem_part_number if primary else "",
                "all_pns": ", ".join(all_pns_list),
                "expected_pns": expected_pns_raw,
                "matched": matched,
                "duration_s": duration,
                "error": "; ".join(result.warnings) if result.warnings else "",
            })
            f.flush()

    elapsed = int(time.monotonic() - start_batch)
    print()
    print(f"Done in {elapsed}s. Report: {output}")
    print(f"  All expected PNs matched : {summary['all']}")
    print(f"  Partial match            : {summary['partial']}")
    print(f"  No match                 : {summary['none']}")
    print(f"  Errors                   : {summary['error']}")
    print(f"  No expected PNs to check : {summary['unknown']}")


def _normalize_pn_set(text: str) -> set[str]:
    """Normalize a comma/space-separated list of PNs into a comparable set.
    Strips whitespace, uppercases, removes dashes/spaces from internal PN
    formatting so '95440-P1AB0' and '95440 P1AB0' compare equal."""
    out: set[str] = set()
    for raw in (text or "").replace(";", ",").split(","):
        cleaned = raw.strip().upper()
        cleaned = cleaned.replace(" ", "").replace("-", "")
        if cleaned:
            out.add(cleaned)
    return out


if __name__ == "__main__":
    asyncio.run(run())
