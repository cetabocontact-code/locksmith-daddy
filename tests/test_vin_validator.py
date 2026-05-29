"""VIN validator unit tests."""

from __future__ import annotations

import pytest

from lbt1.vin.validator import VinValidationError, is_valid, normalize, validate


class TestNormalize:
    def test_strips_whitespace_and_uppercases(self) -> None:
        assert normalize("  5xyk6cdf8tg390982  ") == "5XYK6CDF8TG390982"

    def test_removes_inner_spaces(self) -> None:
        assert normalize("5XYK 6CDF 8TG3 90982") == "5XYK6CDF8TG390982"


class TestValidate:
    def test_known_good_kia_vin_passes(self) -> None:
        # From the training CSV — this is a real 2026 Kia Sportage.
        assert validate("5XYK6CDF8TG390982") == "5XYK6CDF8TG390982"

    def test_wrong_length(self) -> None:
        with pytest.raises(VinValidationError, match="17 characters"):
            validate("5XYK6CDF8TG39098")  # 16 chars

    def test_contains_letter_i(self) -> None:
        # Replace position 17 with I to keep length right but trigger disallowed-letter rule.
        with pytest.raises(VinValidationError, match="disallowed letters"):
            validate("5XYK6CDF8TG39098I")

    def test_contains_letter_o(self) -> None:
        with pytest.raises(VinValidationError, match="disallowed letters"):
            validate("5XYK6CDF8TG39098O")

    def test_contains_letter_q(self) -> None:
        with pytest.raises(VinValidationError, match="disallowed letters"):
            validate("5XYK6CDF8TG39098Q")

    def test_non_alphanumeric(self) -> None:
        with pytest.raises(VinValidationError):
            validate("5XYK6CDF8TG39098!")

    def test_bad_checksum_rejected(self) -> None:
        # Mutate position 9 (the check digit) to a wrong value.
        with pytest.raises(VinValidationError, match="checksum"):
            validate("5XYK6CDF0TG390982")  # changed '8' → '0' at position 9

    def test_skip_checksum_allows_bad_check_digit(self) -> None:
        # Same mutation, but with check_checksum=False.
        validate("5XYK6CDF0TG390982", check_checksum=False)


class TestAllTrainingVinsValid:
    """All 23 training VINs come from real vehicles and must pass validation."""

    def test_all_training_vins_pass(self, training_vins: list[str]) -> None:
        failures: list[tuple[str, str]] = []
        for vin in training_vins:
            try:
                validate(vin)
            except VinValidationError as exc:
                failures.append((vin, str(exc)))
        assert not failures, f"Training VINs failed validation: {failures}"


class TestIsValid:
    def test_returns_true_for_good(self) -> None:
        assert is_valid("5XYK6CDF8TG390982") is True

    def test_returns_false_for_bad(self) -> None:
        assert is_valid("BAD-VIN") is False
