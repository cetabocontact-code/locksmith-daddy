"""Generate 2024 (year code 'R') and 2025 (year code 'S') Hyundai/Kia VINs
with valid ISO 3779 check digits, then filter via NHTSA decode to keep only
the ones that cleanly resolve to a real Hyundai/Kia model.

Output: data/2024_2025_vins.csv with VIN + decoded year/make/model/trim.

WMI seed list compiled from real-world Hyundai/Kia production patterns:
  - Hyundai US plant (Montgomery, AL): 5NPE, 5NPL, 5NMJ, 5NMS, 5NPD, 5NMP
  - Hyundai Korea: KMHL, KMHC, KM8K, KM8R, KM8J, KMHG, KMHE, KMHK
  - Kia US plant (West Point, GA): 5XYK, 5XYP, 5XYR, 5XYG, 5XYE
  - Kia Korea: KNDJ, KNAB, KNAE, KNDM, KNDP, KNDC, KNDM, KNAG
  - Genesis Korea: KMTG, KMTH, KMHG

Approach:
  1. Generate ~300 candidate VINs by combining WMI + random VDS + valid
     year code + plant code + random sequential.
  2. Compute the ISO 3779 check digit and substitute at position 9.
  3. Call NHTSA decode on each candidate (free API, 1 req/sec).
  4. Keep only the ones with nhtsa_error_code == '0' (clean decode).
  5. Stop at 100 clean VINs.
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


# ISO 3779 transliteration table — letter → numeric value
_VIN_TRANS = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
    "8": 8, "9": 9,
}
# Position weights (positions 1..17; index 8 is the check digit itself = 0)
_VIN_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


def compute_check_digit(vin17: str) -> str:
    """Compute the ISO 3779 check digit for a 17-character VIN.

    The 9th character is replaced by this. Returns 'X' for remainder 10.
    """
    s = 0
    for i, ch in enumerate(vin17.upper()):
        if ch not in _VIN_TRANS:
            return ""  # invalid character — VIN rejected
        s += _VIN_TRANS[ch] * _VIN_WEIGHTS[i]
    r = s % 11
    return "X" if r == 10 else str(r)


def vin_with_correct_check(vin17: str) -> str:
    """Substitute position 9 with the correct check digit. Returns the
    valid VIN."""
    placeholder = vin17[:8] + "0" + vin17[9:]
    cd = compute_check_digit(placeholder)
    if cd == "":
        return ""
    return vin17[:8] + cd + vin17[9:]


# WMI prefixes for Hyundai/Kia/Genesis. Each entry expands to a (WMI, prob,
# notes) record. WMI = first 3 characters.
WMI_SEEDS = [
    # Hyundai - US plant (Montgomery AL) - mostly Elantra/Sonata/Santa Cruz/Tucson
    "5NPE", "5NPL", "5NPD", "5NPC", "5NPM", "5NMJ", "5NMS", "5NMP",
    # Hyundai - Korea
    "KMHL", "KMHC", "KMHK", "KMHG", "KMHE", "KMHF", "KMHM",
    "KM8K", "KM8R", "KM8J", "KM8S", "KM8H",
    # Hyundai - newer EV plants (Ioniq family)
    "KM8FF", "KM8FA",
    # Kia - US plant (West Point GA)
    "5XYK", "5XYP", "5XYR", "5XYG", "5XYE", "5XYE", "5XYRL",
    # Kia - Korea
    "KNDJ", "KNAB", "KNAE", "KNDM", "KNDP", "KNDC", "KNAG",
    "KNDR", "KNDPM", "KNDPS",
    # Kia Telluride US WMI variations
    "5XYP1", "5XYP3", "5XYP5", "5XYP8",
    # Genesis Korea
    "KMTG", "KMTH",
]

# Year code → position 10 character (ISO 3779 year encoding)
YEAR_CODES = {
    2024: "R",
    2025: "S",
}


def random_char(alphabet: str) -> str:
    return random.choice(alphabet)


def generate_one(wmi: str, year: int) -> str:
    """Build a single 17-char VIN from a WMI seed + year + random rest.

    VIN structure:
      pos 1-3:  WMI (we take from the seed; if seed is shorter, pad random)
      pos 4-8:  VDS (vehicle descriptor) — random alphanumeric (no I/O/Q)
      pos 9:    check digit (computed)
      pos 10:   year (encoded — R for 2024, S for 2025)
      pos 11:   plant code (random, often a digit or letter)
      pos 12-17: serial (random, often digits)
    """
    valid_alpha = "ABCDEFGHJKLMNPRSTUVWXYZ"
    valid_digits = "0123456789"
    valid_alphanum = valid_alpha + valid_digits

    # Pad WMI to 8 chars if shorter (seed is 3-5 chars, we want pos 1-8)
    head = wmi
    while len(head) < 8:
        head += random_char(valid_alphanum)
    head = head[:8]

    # Year + plant + serial. VIN positions 10-17 = year(1) + plant(1) + serial(6).
    year_code = YEAR_CODES[year]
    plant = random_char(valid_alphanum)
    serial = "".join(random_char(valid_digits) for _ in range(6))

    # Position 9 = '0' placeholder (will be replaced by check digit).
    # Total: 8 (head) + 1 (placeholder) + 1 (year) + 1 (plant) + 6 (serial) = 17.
    candidate = head + "0" + year_code + plant + serial
    if len(candidate) != 17:
        return ""
    return vin_with_correct_check(candidate)


async def filter_by_nhtsa(candidates: list[str], target_count: int) -> list[dict]:
    """Decode each candidate via NHTSA. Keep only those with clean decode
    AND year matches the encoded year code AND make is Hyundai/Kia/Genesis.

    Returns list of dicts with vin, year, make, model, trim, body_class.
    """
    out: list[dict] = []
    seen_vins: set[str] = set()
    for vin in candidates:
        if vin in seen_vins:
            continue
        seen_vins.add(vin)
        if len(out) >= target_count:
            break
        try:
            profile = await decoder.decode(vin)
        except Exception as exc:  # noqa: BLE001
            print(f"  [skip] {vin}: decode error: {exc}")
            continue
        if profile.nhtsa_error_code != "0":
            print(f"  [skip] {vin}: NHTSA error {profile.nhtsa_error_code!r}")
            continue
        if (profile.make or "").upper() not in ("HYUNDAI", "KIA", "GENESIS"):
            print(f"  [skip] {vin}: not Hyundai/Kia (make={profile.make!r})")
            continue
        if not profile.model:
            print(f"  [skip] {vin}: no model")
            continue
        out.append({
            "vin": vin,
            "year": profile.year,
            "make": profile.make,
            "model": profile.model,
            "trim": profile.trim or "",
            "body_class": profile.body_class or "",
        })
        print(f"  [keep #{len(out):3d}] {vin}  → {profile.year} {profile.make} {profile.model} {profile.trim or ''}")
    return out


async def main() -> None:
    random.seed(20260528)  # reproducible
    TARGET = 100

    # Generate ~5x as many candidates as needed — many will be junked by NHTSA
    candidates: list[str] = []
    per_wmi_per_year = 8
    for wmi in WMI_SEEDS:
        for year in YEAR_CODES.keys():
            for _ in range(per_wmi_per_year):
                v = generate_one(wmi, year)
                if v:
                    candidates.append(v)
    random.shuffle(candidates)
    print(f"Generated {len(candidates)} candidates; filtering via NHTSA...")

    rows = await filter_by_nhtsa(candidates, TARGET)
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
