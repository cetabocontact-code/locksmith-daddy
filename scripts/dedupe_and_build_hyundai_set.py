"""Dedupe the new 77-VIN Hyundai set against what's already in our test
reports (cargurus_hyundai_report.csv + 2024_2025_report_corrected.csv +
tonight_vins.csv) and write the not-yet-tested subset to a new CSV."""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEW_FILE = Path("C:/Users/rawes/Documents/Codex/2026-05-29/make-me-a-list-with-30/hyundai_nhtsa_profiles_2019_2026.csv")

# Sources of "already tested" VINs
ALREADY_TESTED_FILES = [
    ROOT / "data" / "cargurus_hyundai_report.csv",
    ROOT / "data" / "2024_2025_report_corrected.csv",
    ROOT / "data" / "tonight_vins.csv",
    ROOT / "data" / "tonight_vins_report.csv",
    ROOT / "data" / "cargurus_validation_vins.csv",
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
    print(f"Already tested VINs in our reports: {len(tested)}")

    # Read new file (CSV with multi-column quoted values)
    new_vins: list[tuple[str, str]] = []  # (vin, label)
    with NEW_FILE.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            vin = (row.get("VIN") or "").strip().upper()
            if not vin or len(vin) != 17:
                continue
            year = row.get("ListedYear", "") or row.get("NHTSA_ModelYear", "")
            model = row.get("ListedModel", "") or row.get("Model", "")
            label = f"{year} Hyundai {model}".strip()
            new_vins.append((vin, label))

    print(f"VINs in new file: {len(new_vins)}")

    untested = [(v, l) for v, l in new_vins if v not in tested]
    skipped = [(v, l) for v, l in new_vins if v in tested]
    print(f"Skipping (already tested): {len(skipped)}")
    print(f"To test (new): {len(untested)}")

    out_path = ROOT / "data" / "cargurus_hyundai_2019_2024_new.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["vin", "label"])
        for vin, label in untested:
            w.writerow([vin, label])
    print(f"Wrote {out_path}")

    # Show the skipped list for transparency
    if skipped:
        print("\nSkipped VINs (already tested):")
        for vin, label in skipped:
            print(f"  {vin}  {label}")


if __name__ == "__main__":
    main()
