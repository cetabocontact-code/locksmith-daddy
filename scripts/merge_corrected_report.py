"""Merge the c=5 original report with the c=2 retest. For VINs where the
c=2 retest succeeded, replace the c=5 row with the c=2 row. This produces
the corrected report with throttle artifacts removed.
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC1 = ROOT / "data" / "2024_2025_report.csv"
SRC2 = ROOT / "data" / "failed_vins_retest_report.csv"
OUT  = ROOT / "data" / "2024_2025_report_corrected.csv"

retest_by_vin: dict[str, dict] = {}
with SRC2.open(encoding="utf-8") as f:
    for r in csv.DictReader(f):
        retest_by_vin[r["vin"]] = r

with SRC1.open(encoding="utf-8") as f, OUT.open("w", newline="", encoding="utf-8") as out:
    rdr = csv.DictReader(f)
    fields = rdr.fieldnames
    w = csv.DictWriter(out, fieldnames=fields)
    w.writeheader()
    replaced = 0
    for r in rdr:
        retest = retest_by_vin.get(r["vin"])
        # Use retest data only if it succeeded where original failed
        if (retest
            and r["status"] != "DEALER_VERIFIED_BY_VIN"
            and retest["status"] == "DEALER_VERIFIED_BY_VIN"):
            w.writerow(retest)
            replaced += 1
        else:
            w.writerow(r)

print(f"Replaced {replaced} throttle-victim rows with clean retest data.")
print(f"Wrote {OUT}")
