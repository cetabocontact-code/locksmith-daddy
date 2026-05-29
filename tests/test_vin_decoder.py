"""NHTSA VPIC decoder tests — hits the live VPIC API.

VPIC is free and unmetered, so these tests run against the real service. If
NHTSA is down or network is unavailable, the tests will fail with a clear
HTTP error rather than silently passing.
"""

from __future__ import annotations

import pytest

from lbt1.vin import decoder

# Three representative VINs from the training set covering different model years.
SAMPLE_VINS = [
    ("5XYK6CDF8TG390982", "Sportage"),       # 2026 (CSV row 5)
    ("5XYP5DHC5NG256061", "Telluride"),      # 2022 (CSV row 9)
    ("KNDPB3AC9G7856028", "Sportage"),       # 2016 (CSV row 103)
]


class TestDecoder:
    @pytest.mark.parametrize("vin,expected_model", SAMPLE_VINS)
    async def test_decodes_known_vins(self, vin: str, expected_model: str) -> None:
        profile = await decoder.decode(vin)
        assert profile.vin == vin
        assert profile.make and profile.make.lower() == "kia"
        assert profile.model and expected_model.lower() in profile.model.lower()
        assert profile.year is not None
        assert profile.is_clean_decode

    async def test_raw_field_preserved(self) -> None:
        profile = await decoder.decode("5XYK6CDF8TG390982")
        assert profile.raw, "raw VPIC response should be retained for evidence"
        assert profile.raw.get("Make", "").lower() == "kia"

    async def test_decode_returns_engine_and_drive(self) -> None:
        # The 2026 Sportage in the CSV decodes to GDI THETA III + 4WD.
        profile = await decoder.decode("5XYK6CDF8TG390982")
        assert profile.engine_model and "theta" in profile.engine_model.lower()
        assert profile.drive_type and "4wd" in profile.drive_type.lower()
