"""Build data/tonight_vins.csv — 30 VINs for the evening autopilot test.

Source strategy: use VINs we already confirmed work (from prior verified
batches) PLUS a few intentionally-failing ones to track regression. This
removes the synthetic-VIN noise that hurt yesterday's "60% coverage" read.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

VERIFIED_REAL_VINS = [
    # From CarGurus baseline (proven real, all returned PNs):
    ("5XYK6CDF8TG390982", "2026 Kia Sportage X-Line"),
    ("5XYP5DHC5NG256061", "2022 Kia Telluride SX"),
    ("5XYPHDA52JG374761", "2018 Kia Sorento EX"),
    ("5XYPG4A37GG083523", "2016 Kia Sorento LX"),
    ("KNDJ23AU3R7233490", "2024 Kia Soul LX"),
    ("5NPD84LFXHH074817", "2017 Hyundai Elantra"),
    # From corrected 100-VIN batch (verified post-c=2 retest):
    ("5NMJB3AEXR4663672", "2024 Hyundai Tucson SEL"),
    ("KNDJ33AU9S0357758", "2025 Kia Soul EX"),
    ("KNDJ33AU7SH761238", "2025 Kia Soul EX"),
    ("KNDJ33AU2RY773971", "2024 Kia Soul EX"),
    ("5NMP24GL7RL398351", "2024 Hyundai Santa Fe SEL"),
    ("5XYK33AFXS8003306", "2025 Kia Sportage EX"),
    ("5XYK33AF7SP053232", "2025 Kia Sportage EX"),
    ("5XYK6CDFXSH536579", "2025 Kia Sportage X-LINE"),
    ("KMHLM4DG8R9341814", "2024 Hyundai Elantra SEL"),
    ("KMHL14JA3RJ254507", "2024 Hyundai Sonata SEL"),
    ("KMHLM4DG0R8098716", "2024 Hyundai Elantra SEL"),
    ("KMHLS4DG6R5629506", "2024 Hyundai Elantra SEL w/ Convenience"),
    ("KNDJ33AU4R0797638", "2024 Kia Soul EX"),
    ("5XYK6CDFXR7898637", "2024 Kia Sportage X-LINE"),
    ("5XYK6CDF0R1357762", "2024 Kia Sportage X-LINE"),
    ("KMHLS4DG8SM199473", "2025 Hyundai Elantra SEL Convenience"),
    ("5XYRH4LF3R1003525", "2024 Kia Sorento EX"),
    ("5NMJB3AE6RG506056", "2024 Hyundai Tucson SEL"),
    # A few that previously failed — regression-check post Bug #1 fix:
    ("KM8R5DHC3SU081016", "2025 Hyundai Palisade Limited"),
    ("5NMP34GL7SN375837", "2025 Hyundai Santa Fe XRT"),
    ("KMTG54TE9SJ003881", "2025 Genesis G70 Sport"),
    ("KNDC34LD0RP458006", "2024 Kia EV6 Light/Wind"),
    # Holdout from the verified-known set (sanity baseline):
    ("KNDPUCDF1T7441411", "2026 Kia model"),
    ("KMHLM4DG9RU789816", "2024 Hyundai Elantra"),
]


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "data" / "tonight_vins.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["vin", "label"])
        for vin, label in VERIFIED_REAL_VINS:
            w.writerow([vin, label])
    print(f"Wrote {out} with {len(VERIFIED_REAL_VINS)} VINs")


if __name__ == "__main__":
    main()
