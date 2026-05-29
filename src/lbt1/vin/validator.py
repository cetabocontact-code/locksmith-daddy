"""VIN format validation per ISO 3779.

A valid VIN is exactly 17 characters, contains no I, O, or Q (visually confusable
with 1 and 0), and has a check digit at position 9 that satisfies the mod-11
weighted-sum algorithm.

Note: pre-1981 VINs predate the standard and may be 11-17 chars. This validator
rejects those — for a 1980s-era vehicle the locksmith should be informed the VIN
can't be decoded and use the year/make/model path instead.
"""

from __future__ import annotations

VIN_LENGTH = 17
DISALLOWED_LETTERS = set("IOQ")

_TRANSLITERATION: dict[str, int] = {
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
}

_WEIGHTS: tuple[int, ...] = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


class VinValidationError(ValueError):
    """Raised when a VIN fails format or checksum validation."""


def normalize(vin: str) -> str:
    """Strip whitespace and uppercase. Does NOT validate."""
    return vin.strip().upper().replace(" ", "")


def validate(vin: str, *, check_checksum: bool = True) -> str:
    """Validate a VIN and return the normalized form.

    Raises VinValidationError if invalid.

    Pass check_checksum=False to skip the ISO 3779 check digit verification
    (some manufacturers — notably pre-2010 Asian-market VINs — don't always
    follow the spec correctly).
    """
    normalized = normalize(vin)

    if len(normalized) != VIN_LENGTH:
        raise VinValidationError(
            f"VIN must be exactly {VIN_LENGTH} characters; got {len(normalized)}"
        )

    if not normalized.isalnum():
        raise VinValidationError("VIN must contain only letters and digits")

    bad = DISALLOWED_LETTERS & set(normalized)
    if bad:
        raise VinValidationError(
            f"VIN contains disallowed letters {sorted(bad)} "
            "(I, O, Q are not used to avoid visual confusion with 1, 0)"
        )

    if check_checksum and not _checksum_ok(normalized):
        raise VinValidationError(
            f"VIN check digit (position 9) failed ISO 3779 checksum: {normalized}"
        )

    return normalized


def _checksum_ok(vin: str) -> bool:
    """ISO 3779 / NHTSA check digit verification.

    Sum of (char_value × position_weight) for positions 1-17, mod 11.
    Position 9 holds the check digit itself; X represents 10.
    """
    total = sum(_TRANSLITERATION[c] * w for c, w in zip(vin, _WEIGHTS, strict=True))
    remainder = total % 11
    expected = "X" if remainder == 10 else str(remainder)
    return vin[8] == expected


def is_valid(vin: str, *, check_checksum: bool = True) -> bool:
    """Boolean wrapper around validate()."""
    try:
        validate(vin, check_checksum=check_checksum)
        return True
    except VinValidationError:
        return False
