"""Dedupe the new 133-VIN Toyota 2017-2026 set against what's already in our
test reports, then write the not-yet-tested subset to a new CSV."""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEW_FILE = Path("C:/Users/rawes/Documents/Codex/2026-05-29/make-me-a-list-with-30/toyota_nhtsa_profiles_2017_2026.csv")

# Sources of "already tested" Toyota VINs
ALREADY_TESTED_FILES = [
    ROOT / "data" / "cargurus_toyota_report.csv",
    ROOT / "data" / "toyota_2026_gap_retest_report.csv",
    ROOT / "data" / "adhoc_test_report.csv",
]


def collect_already_tested() -> set[str]:
    tested: set[str] = set()
    for p in ALREADY_TESTED_FILES:
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                vin = (row.get("vin") or row.get("VIN") or "").strip().upper()
                if vin and len(vin) == 17:
                    tested.add(vin)
    return tested


def main() -> None:
    tested = collect_already_tested()
    print(f"Already-tested Toyota VINs in our reports: {len(tested)}")

    new_vins: list[tuple[str, str]] = []
    with NEW_FILE.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            vin = (row.get("VIN") or "").strip().upper()
            if not vin or len(vin) != 17:
                continue
            year = row.get("ListedYear", "") or row.get("NHTSA_ModelYear", "")
            model = row.get("ListedModel", "") or row.get("Model", "")
            label = f"{year} Toyota {model}".strip()
            new_vins.append((vin, label))

    print(f"VINs in new file: {len(new_vins)}")

    untested = [(v, l) for v, l in new_vins if v not in tested]
    skipped = [(v, l) for v, l in new_vins if v in tested]
    print(f"Skipping (already tested): {len(skipped)}")
    print(f"To test (new): {len(untested)}")

    out_path = ROOT / "data" / "cargurus_toyota_2017_2026_new.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["vin", "label"])
        for vin, label in untested:
            w.writerow([vin, label])
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
