"""Test fixtures — load the 23 training VINs from the CSV for regression."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TRAINING_CSV = DATA_DIR / "kia_vin_training.csv"


@pytest.fixture(scope="session")
def training_rows() -> list[dict[str, str]]:
    """Parse the training CSV. Each row has VIN + expected PNs (PN 1..PN 6)."""
    rows = []
    with TRAINING_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # The CSV column header is "VIN " or "VIN" depending on row — normalize.
            vin = (row.get("VIN") or "").strip()
            if not vin:
                continue
            rows.append(
                {
                    "vin": vin,
                    "expected_pns": [
                        (row.get(f"PN {i}") or "").strip()
                        for i in range(1, 7)
                        if (row.get(f"PN {i}") or "").strip()
                    ],
                }
            )
    return rows


@pytest.fixture(scope="session")
def training_vins(training_rows: list[dict[str, str]]) -> list[str]:
    """Just the VIN strings — for parametrize."""
    return [r["vin"] for r in training_rows]
