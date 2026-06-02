"""Post-audit analyzer: takes a batch_test_vins_parallel.py report CSV,
tallies verification rate per make / year / model, and prints a
markdown-ready summary.

Run:
  python scripts/analyze_audit_report.py data/multi_make_audit_2026-06-02_report.csv
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path


def main(path: str) -> None:
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    total = len(rows)
    verified = sum(1 for r in rows if r["status"] == "DEALER_VERIFIED_BY_VIN")
    print(f"# Audit report: {Path(path).name}")
    print()
    print(f"**Total VINs:** {total}")
    print(f"**Verified:** {verified} / {total} ({100*verified/total:.1f}%)")
    print()

    # By make
    print("## By make")
    print()
    print("| Make | Verified | Total | Rate |")
    print("|---|---|---|---|")
    by_make: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [verified, total]
    for r in rows:
        make = (r.get("make") or "").upper().strip()
        by_make[make][1] += 1
        if r["status"] == "DEALER_VERIFIED_BY_VIN":
            by_make[make][0] += 1
    for m in sorted(by_make, key=lambda x: -by_make[x][1]):
        v, t = by_make[m]
        pct = 100 * v / t if t else 0
        print(f"| {m} | {v} | {t} | {pct:.1f}% |")
    print()

    # By make+year
    print("## By make + year")
    print()
    print("| Make | Year | Verified / Total | Rate |")
    print("|---|---|---|---|")
    by_my: dict[tuple, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        make = (r.get("make") or "").upper().strip()
        year = (r.get("year") or "").strip()
        by_my[(make, year)][1] += 1
        if r["status"] == "DEALER_VERIFIED_BY_VIN":
            by_my[(make, year)][0] += 1
    for k in sorted(by_my):
        v, t = by_my[k]
        pct = 100 * v / t if t else 0
        print(f"| {k[0]} | {k[1]} | {v}/{t} | {pct:.1f}% |")
    print()

    # Failures grouped by make
    print("## Failures (NOT_DEALER_VERIFIED_BY_VIN)")
    print()
    failures: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["status"] != "DEALER_VERIFIED_BY_VIN":
            failures[(r.get("make") or "").upper().strip()].append(r)
    for make in sorted(failures):
        items = failures[make]
        print(f"### {make} ({len(items)} failures)")
        print()
        for r in items:
            print(f"  - `{r['vin']}` — {r['year']} {r['model']} {r.get('trim') or ''} · {r['duration_s']}s")
        print()

    # Summary by primary PN family (where verified)
    print("## PN families captured")
    print()
    family_count: dict[str, int] = defaultdict(int)
    for r in rows:
        if r["status"] == "DEALER_VERIFIED_BY_VIN" and r.get("primary_pn"):
            pn = r["primary_pn"]
            # Extract prefix — characters before first dash or first 5 chars
            prefix = pn.split("-")[0] if "-" in pn else pn[:5]
            family_count[prefix] += 1
    for prefix in sorted(family_count, key=lambda x: -family_count[x]):
        print(f"  - `{prefix}*` × {family_count[prefix]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: analyze_audit_report.py <report.csv>")
        sys.exit(1)
    main(sys.argv[1])
