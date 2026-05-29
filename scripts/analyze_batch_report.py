"""Analyze a batch_test_vins.py report CSV and produce a coverage breakdown
+ failure-mode analysis + optimization recommendations.

Usage:
    python scripts/analyze_batch_report.py data/2024_2025_report.csv
"""

from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main(report_path: Path) -> None:
    rows = list(csv.DictReader(report_path.open(encoding="utf-8")))
    total = len(rows)
    if total == 0:
        print("Empty report.")
        return

    print("=" * 78)
    print(f"BATCH COVERAGE REPORT — {report_path.name}")
    print(f"Total VINs tested: {total}")
    print("=" * 78)

    # ── Overall status ───────────────────────────────────────────────
    status_counts = Counter(r["status"] for r in rows)
    verified = status_counts.get("DEALER_VERIFIED_BY_VIN", 0)
    not_verified = status_counts.get("NOT_DEALER_VERIFIED_BY_VIN", 0)
    error = status_counts.get("ERROR", 0)
    coverage_pct = (verified / total * 100) if total else 0.0
    print(f"\n  DEALER_VERIFIED_BY_VIN     : {verified:3d}  ({coverage_pct:.1f}%)")
    print(f"  NOT_DEALER_VERIFIED_BY_VIN : {not_verified:3d}")
    print(f"  ERROR                      : {error:3d}")

    # ── By year ──────────────────────────────────────────────────────
    print("\n── Coverage by model year ─────────────────────────────────────")
    by_year = defaultdict(lambda: {"verified": 0, "not_verified": 0, "error": 0})
    for r in rows:
        key = (r.get("year") or "?")
        if r["status"] == "DEALER_VERIFIED_BY_VIN":
            by_year[key]["verified"] += 1
        elif r["status"] == "ERROR":
            by_year[key]["error"] += 1
        else:
            by_year[key]["not_verified"] += 1
    for year in sorted(by_year.keys()):
        d = by_year[year]
        tot = d["verified"] + d["not_verified"] + d["error"]
        pct = (d["verified"] / tot * 100) if tot else 0
        print(f"  {year}: {d['verified']:3d}/{tot:3d} verified ({pct:5.1f}%)  "
              f"not_verified={d['not_verified']:3d}  err={d['error']:2d}")

    # ── By make ──────────────────────────────────────────────────────
    print("\n── Coverage by make ───────────────────────────────────────────")
    by_make = defaultdict(lambda: {"verified": 0, "not_verified": 0, "error": 0})
    for r in rows:
        key = (r.get("make") or "?").upper()
        if r["status"] == "DEALER_VERIFIED_BY_VIN":
            by_make[key]["verified"] += 1
        elif r["status"] == "ERROR":
            by_make[key]["error"] += 1
        else:
            by_make[key]["not_verified"] += 1
    for make, d in sorted(by_make.items()):
        tot = d["verified"] + d["not_verified"] + d["error"]
        pct = (d["verified"] / tot * 100) if tot else 0
        print(f"  {make:15s} {d['verified']:3d}/{tot:3d}  ({pct:5.1f}%)  "
              f"not_verified={d['not_verified']:3d}  err={d['error']:2d}")

    # ── By year + make ───────────────────────────────────────────────
    print("\n── Coverage by year × make ────────────────────────────────────")
    by_ym = defaultdict(lambda: {"verified": 0, "not_verified": 0, "error": 0})
    for r in rows:
        key = ((r.get("year") or "?"), (r.get("make") or "?").upper())
        if r["status"] == "DEALER_VERIFIED_BY_VIN":
            by_ym[key]["verified"] += 1
        elif r["status"] == "ERROR":
            by_ym[key]["error"] += 1
        else:
            by_ym[key]["not_verified"] += 1
    for (year, make), d in sorted(by_ym.items()):
        tot = d["verified"] + d["not_verified"] + d["error"]
        pct = (d["verified"] / tot * 100) if tot else 0
        print(f"  {year} {make:10s} {d['verified']:3d}/{tot:3d}  ({pct:5.1f}%)")

    # ── By model ─────────────────────────────────────────────────────
    print("\n── Coverage by model (top 15 by sample size) ─────────────────")
    by_model = defaultdict(lambda: {"verified": 0, "total": 0})
    for r in rows:
        key = f"{(r.get('make') or '?').upper()[:6]} {r.get('model') or '?'}"
        by_model[key]["total"] += 1
        if r["status"] == "DEALER_VERIFIED_BY_VIN":
            by_model[key]["verified"] += 1
    for model, d in sorted(by_model.items(), key=lambda kv: -kv[1]["total"])[:15]:
        pct = (d["verified"] / d["total"] * 100) if d["total"] else 0
        print(f"  {model[:30]:30s}  {d['verified']:3d}/{d['total']:3d}  ({pct:5.1f}%)")

    # ── Failure-mode breakdown (parsed from error/warnings column) ───
    print("\n── Failure-mode breakdown ─────────────────────────────────────")
    failure_buckets = Counter()
    for r in rows:
        if r["status"] == "DEALER_VERIFIED_BY_VIN":
            continue
        err = (r.get("error") or "").lower()
        if r["status"] == "ERROR":
            failure_buckets["EXCEPTION"] += 1
        elif "vin format invalid" in err or "checksum" in err:
            failure_buckets["VIN invalid (checksum)"] += 1
        elif "nhtsa" in err:
            failure_buckets["NHTSA decode failed"] += 1
        elif "no dealer-site scraper" in err:
            failure_buckets["Make not supported"] += 1
        elif "catalog has no record" in err:
            failure_buckets["Catalog gap (all dealers empty)"] += 1
        elif err:
            failure_buckets[f"Other: {err[:60]}"] += 1
        else:
            failure_buckets["Catalog gap (silent — no key parts harvested)"] += 1
    for bucket, n in failure_buckets.most_common():
        print(f"  [{n:3d}] {bucket}")

    # ── Per-PN-prefix breakdown of verified results ──────────────────
    print("\n── PN prefix breakdown (verified results) ────────────────────")
    pn_prefixes = Counter()
    for r in rows:
        if r["status"] != "DEALER_VERIFIED_BY_VIN":
            continue
        primary = (r.get("primary_pn") or "").upper()
        if not primary:
            continue
        # Extract leading 5-digit family
        prefix = primary[:5]
        pn_prefixes[prefix] += 1
    for pre, n in pn_prefixes.most_common():
        meaning = {
            "95440": "FOB-SMART KEY (push-button start)",
            "95430": "TRANSMITTER ASSY (remote fob)",
            "95431": "TRANSMITTER variant",
            "95441": "TRANSPONDER (chip in key)",
            "81905": "KEY & CYLINDER SET-LOCK",
            "81970": "KEY SUB SET-DOOR",
            "81996": "KEY-BLANKING (uncut blank)",
        }.get(pre, "")
        print(f"  {pre}-* : {n:3d}  {meaning}")

    # ── Duration distribution ─────────────────────────────────────────
    durations = [int(r.get("duration_s") or 0) for r in rows if r.get("duration_s")]
    if durations:
        durations.sort()
        n = len(durations)
        print(f"\n── Per-VIN duration (seconds) ─────────────────────────────────")
        print(f"  count={n}  min={durations[0]}  p50={durations[n//2]}  "
              f"p90={durations[int(n*0.9)]}  max={durations[-1]}  total={sum(durations)}s")

    # ── Recommendations ──────────────────────────────────────────────
    print("\n── Optimization recommendations ───────────────────────────────")
    if coverage_pct < 60:
        print(f"  [CRITICAL] Coverage {coverage_pct:.1f}% — investigate why >40% "
              f"of legitimate VINs fail. Top failure: "
              f"{next(iter(failure_buckets.most_common(1)), ('?', 0))[0]}")
    elif coverage_pct < 80:
        print(f"  [WARN] Coverage {coverage_pct:.1f}% — room for improvement.")
    else:
        print(f"  [OK] Coverage {coverage_pct:.1f}%.")

    # By-year gaps
    for year in sorted(by_year.keys()):
        d = by_year[year]
        tot = d["verified"] + d["not_verified"] + d["error"]
        pct = (d["verified"] / tot * 100) if tot else 0
        if pct < 50:
            print(f"  [GAP] {year} only {pct:.0f}% verified — likely catalog "
                  f"hasn't been populated for that year. Adding more dealers "
                  f"on the same platform won't help; need cross-platform sources.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: analyze_batch_report.py <report.csv>")
        sys.exit(1)
    main(Path(sys.argv[1]))
