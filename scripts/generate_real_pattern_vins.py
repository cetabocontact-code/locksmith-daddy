"""Better approach: take REAL known-good Hyundai/Kia VINs as templates,
vary only positions 11-17 (plant + serial) while keeping positions 1-10
(WMI + VDS + year code). NHTSA decodes these reliably because positions
1-8 encode the make/model/trim/engine, which IS what NHTSA's VPIC DB
indexes against.

Templates pulled from public production VIN ranges + CarGurus listings
research + prior tests. Years 2024 (year code 'R') and 2025 (year code 'S').
"""

from __future__ import annotations

import asyncio
import csv
import random
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lbt1.vin import decoder  # noqa: E402


_VIN_TRANS = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
    "8": 8, "9": 9,
}
_VIN_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


def compute_check_digit(vin17: str) -> str:
    s = 0
    for i, ch in enumerate(vin17.upper()):
        if ch not in _VIN_TRANS:
            return ""
        s += _VIN_TRANS[ch] * _VIN_WEIGHTS[i]
    r = s % 11
    return "X" if r == 10 else str(r)


def fix_check(vin17: str) -> str:
    """Substitute position 9 with the correct check digit."""
    placeholder = vin17[:8] + "0" + vin17[9:]
    cd = compute_check_digit(placeholder)
    return vin17[:8] + cd + vin17[9:] if cd else ""


# Templates: real-world Hyundai/Kia VIN prefixes (positions 1-8) we know
# decode cleanly via NHTSA. Position 9 (check digit), position 10 (year),
# position 11 (plant), and 12-17 (serial) will be varied.
#
# Each template is (prefix_8chars, description). The first 8 chars encode
# the make/plant/model/body/restraint/engine — keeping these constant
# guarantees NHTSA can decode the resulting VIN.
TEMPLATES = [
    # ─── Hyundai US plant (Montgomery, AL) ──────────────────────────────
    ("5NPE34AF", "Hyundai Sonata SE 2.4L"),       # 2017 Sonata pattern
    ("5NPEH4J2", "Hyundai Sonata Limited"),
    ("5NPEL4JA", "Hyundai Sonata SEL"),
    ("5NPEG4JA", "Hyundai Sonata"),
    ("5NMS33AD", "Hyundai Santa Fe"),
    ("5NMS24AJ", "Hyundai Santa Fe Sport"),
    ("5NMJB3AE", "Hyundai Santa Cruz"),
    ("5NMJC3AE", "Hyundai Santa Cruz"),
    ("5NPLM4AJ", "Hyundai Elantra Limited"),
    ("5NPLL4AG", "Hyundai Elantra SEL"),
    ("5NPDH4AE", "Hyundai Elantra"),
    ("5NPD84LF", "Hyundai Elantra Limited"),  # known good in prior tests
    ("5NMP24GL", "Hyundai Tucson"),
    ("5NMP34GL", "Hyundai Tucson"),

    # ─── Hyundai Korea ──────────────────────────────────────────────────
    ("KMHL14JA", "Hyundai Korea"),
    ("KMHL24JJ", "Hyundai Sonata Korea"),
    ("KMHLS4DG", "Hyundai Elantra SEL Sport"),  # the 2026 case
    ("KMHLM4DG", "Hyundai Elantra SEL Sport"),  # the user's case
    ("KMHC85LH", "Hyundai Ioniq Hybrid"),
    ("KMHC75LJ", "Hyundai Ioniq"),
    ("KM8K6CA5", "Hyundai Kona"),
    ("KM8K33AG", "Hyundai Kona"),
    ("KM8R5DHC", "Hyundai Santa Fe"),
    ("KM8R3DHC", "Hyundai Santa Fe"),
    ("KM8J3CA4", "Hyundai Tucson"),
    ("KM8JB3A2", "Hyundai Tucson"),
    ("KMHE34LJ", "Hyundai Sonata Hybrid"),
    ("KMHE24LJ", "Hyundai Sonata Hybrid"),

    # ─── Kia US plant (West Point, GA) ──────────────────────────────────
    ("5XYK6CDF", "Kia Sportage X-Line"),         # 2026 baseline
    ("5XYK33AF", "Kia Sportage LX"),
    ("5XYP5DHC", "Kia Telluride SX"),            # 2022 baseline
    ("5XYP3DHC", "Kia Telluride LX"),
    ("5XYP1DHC", "Kia Telluride EX"),
    ("5XYRH4LF", "Kia Sorento"),
    ("5XYPHDA5", "Kia Sorento EX"),              # 2018 baseline
    ("5XYPG4A3", "Kia Sorento LX"),              # 2016 baseline
    ("5XYRG4LC", "Kia Sorento"),
    ("5XYE34LF", "Kia Sportage"),

    # ─── Kia Korea ──────────────────────────────────────────────────────
    ("KNDJ23AU", "Kia Soul LX"),                 # 2024 baseline
    ("KNDJ33AU", "Kia Soul EX"),
    ("KNAB1612", "Kia Rio"),
    ("KNAE45LD", "Kia Cadenza"),
    ("KNDPMCAC", "Kia Sportage"),
    ("KNDPNCAC", "Kia Sportage"),
    ("KNDC34LD", "Kia Forte"),
    ("KNAG24KE", "Kia Forte LX"),
    ("KNDMC5C1", "Kia Sedona"),
    ("KNDPU3AC", "Kia Sportage Hybrid"),
    ("KNDPUCDF", "Kia Sportage"),                # 2026 production prior test

    # ─── Genesis ────────────────────────────────────────────────────────
    ("KMTG54TE", "Genesis G70"),                 # 2020 baseline
    ("KMTG34LE", "Genesis G70"),
    ("KMTH64TE", "Genesis G80"),
]

YEAR_CODES = {2024: "R", 2025: "S"}
VALID_ALPHA = "ABCDEFGHJKLMNPRSTUVWXYZ"
VALID_DIGITS = "0123456789"


def random_serial() -> str:
    """6-character serial, typically digits but some have letters."""
    if random.random() < 0.9:
        return "".join(random.choice(VALID_DIGITS) for _ in range(6))
    return "".join(random.choice(VALID_ALPHA + VALID_DIGITS) for _ in range(6))


def random_plant() -> str:
    return random.choice(VALID_ALPHA + VALID_DIGITS)


def generate_from_template(prefix8: str, year: int) -> str:
    """Build a VIN from a known prefix + year + random plant/serial."""
    year_code = YEAR_CODES[year]
    # Position 9 placeholder, position 10 = year_code, 11 = plant, 12-17 = serial
    candidate = prefix8 + "0" + year_code + random_plant() + random_serial()
    return fix_check(candidate)


async def filter_via_nhtsa(candidates: list[str], target: int) -> list[dict]:
    """Keep any VIN where NHTSA returns USEFUL data — year + make + model.

    NHTSA error codes:
      0       → clean decode
      2,14    → "VIN corrected" + partial info — still has year/make/model/engine
                (these are templated VINs where serial doesn't match a known
                production unit, but the manufacturer pattern decodes fine)
      4,14    → multi-match, partial info — also usable
      1,6     → check digit / incomplete — REJECT
      8 alone → no data at all — REJECT

    The dealer sites' VIN search will accept ANY 17-char VIN with the right
    WMI/VDS and resolve to the year/make/model chooser. That's what matters
    for OUR testing — we're stressing the dealer-side fitment logic, not
    NHTSA's database completeness.
    """
    out: list[dict] = []
    seen: set[str] = set()
    bad_count = 0
    for vin in candidates:
        if vin in seen:
            continue
        seen.add(vin)
        if len(out) >= target:
            break
        try:
            profile = await decoder.decode(vin)
        except Exception as exc:  # noqa: BLE001
            bad_count += 1
            continue
        err = (profile.nhtsa_error_code or "").strip()
        # Reject: check-digit failures, incomplete VINs, completely unknown
        if err == "1" or err == "6" or err == "8":
            bad_count += 1
            if bad_count % 25 == 0:
                print(f"  [skip {bad_count}] {vin}: NHTSA err {err!r}")
            continue
        # Require year, make, model populated
        if not profile.year or not profile.model:
            bad_count += 1
            continue
        if (profile.make or "").upper() not in ("HYUNDAI", "KIA", "GENESIS"):
            bad_count += 1
            continue
        out.append({
            "vin": vin,
            "year": profile.year,
            "make": profile.make,
            "model": profile.model,
            "trim": profile.trim or "",
            "body_class": profile.body_class or "",
        })
        if len(out) % 10 == 0:
            print(f"  [#{len(out):3d}] {vin}  →  {profile.year} {profile.make} {profile.model} {profile.trim or ''}")
    return out


async def main() -> None:
    random.seed(20260529)
    TARGET = 100

    candidates: list[str] = []
    # 8 candidates per (template, year) = 50 templates * 2 years * 8 = 800
    per_combo = 8
    for prefix in TEMPLATES:
        # Templates is a list of tuples (prefix, desc); extract prefix
        prefix8 = prefix[0] if isinstance(prefix, tuple) else prefix
        for year in YEAR_CODES.keys():
            for _ in range(per_combo):
                v = generate_from_template(prefix8, year)
                if v:
                    candidates.append(v)
    random.shuffle(candidates)
    print(f"Generated {len(candidates)} candidates from {len(TEMPLATES)} real-VIN templates.")
    print(f"Filtering via NHTSA (target={TARGET}, year=2024 'R' or 2025 'S')...")

    rows = await filter_via_nhtsa(candidates, TARGET)
    print(f"\nKept {len(rows)} clean-decoding VINs.")

    out_path = Path(__file__).resolve().parents[1] / "data" / "2024_2025_vins.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["vin", "year", "make", "model", "trim", "body_class"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
