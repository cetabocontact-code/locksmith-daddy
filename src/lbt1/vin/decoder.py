"""NHTSA VPIC decoder — Layer 1 of the lookup pipeline.

Hits the public VPIC API to decode a VIN into a VehicleProfile. No API key
required. The endpoint is documented at
https://vpic.nhtsa.dot.gov/api/Home/Index/LanguageVersion/en.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from lbt1.models import VehicleProfile
from lbt1.vin import validator

NHTSA_BASE = "https://vpic.nhtsa.dot.gov/api/vehicles"
DEFAULT_TIMEOUT = 15.0


class NhtsaDecodeError(Exception):
    """Raised when VPIC returns an error or the response shape is unexpected."""


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    reraise=True,
)
async def _fetch(vin: str, client: httpx.AsyncClient) -> dict[str, Any]:
    """Single VPIC call with retries on transient HTTP errors."""
    url = f"{NHTSA_BASE}/DecodeVinValuesExtended/{vin}"
    response = await client.get(url, params={"format": "json"}, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    data = response.json()

    results = data.get("Results")
    if not isinstance(results, list) or not results:
        raise NhtsaDecodeError(f"VPIC returned no Results for {vin}: {data}")

    return results[0]


async def decode(vin: str, *, client: httpx.AsyncClient | None = None) -> VehicleProfile:
    """Decode a VIN and return a populated VehicleProfile.

    Validates the VIN format first (rejects bad length / disallowed chars /
    bad checksum). If validation passes but VPIC returns ErrorCode != 0, the
    resulting profile is returned with the error captured — the caller decides
    whether to proceed or surface a warning.
    """
    normalized = validator.validate(vin)

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient()

    try:
        raw = await _fetch(normalized, client)
    finally:
        if own_client:
            await client.aclose()

    return _map_to_profile(normalized, raw)


def decode_sync(vin: str) -> VehicleProfile:
    """Synchronous wrapper for CLI / scripting use. Spins up its own loop."""
    return asyncio.run(decode(vin))


def _map_to_profile(vin: str, raw: dict[str, Any]) -> VehicleProfile:
    """Map the VPIC field names to our internal VehicleProfile.

    Empty/null/whitespace VPIC values become None.
    """

    def s(key: str) -> str | None:
        v = raw.get(key)
        if v is None:
            return None
        text = str(v).strip()
        return text or None

    def i(key: str) -> int | None:
        v = s(key)
        if v is None:
            return None
        try:
            return int(v)
        except ValueError:
            return None

    def f(key: str) -> float | None:
        v = s(key)
        if v is None:
            return None
        try:
            return float(v)
        except ValueError:
            return None

    return VehicleProfile(
        vin=vin,
        year=i("ModelYear"),
        make=s("Make"),
        model=s("Model"),
        trim=s("Trim"),
        series=s("Series"),
        series2=s("Series2"),
        body_class=s("BodyClass"),
        # Engine — pulled fuller for chooser-page disambiguation
        engine_model=s("EngineModel"),
        engine_manufacturer=s("EngineManufacturer"),
        engine_cylinders=i("EngineCylinders"),
        engine_hp=i("EngineHP"),
        engine_configuration=s("EngineConfiguration"),
        displacement_l=f("DisplacementL"),
        displacement_cc=f("DisplacementCC"),
        fuel_type=s("FuelTypePrimary"),
        fuel_injection_type=s("FuelInjectionType"),
        valve_train_design=s("ValveTrainDesign"),
        # Drivetrain
        drive_type=s("DriveType"),
        transmission_style=s("TransmissionStyle"),
        transmission_speeds=i("TransmissionSpeeds"),
        # Body / occupancy
        doors=i("Doors"),
        seats=i("Seats"),
        seat_rows=i("SeatRows"),
        vehicle_type=s("VehicleType"),
        ncsa_body_type=s("NCSABodyType"),
        gvwr=s("GVWR"),
        wheel_base_short=f("WheelBaseShort"),
        # Manufacturing
        plant_country=s("PlantCountry"),
        plant_state=s("PlantState"),
        plant_city=s("PlantCity"),
        manufacturer=s("Manufacturer"),
        base_price=s("BasePrice"),
        # Diagnostics
        nhtsa_error_code=s("ErrorCode"),
        nhtsa_error_text=s("ErrorText"),
        nhtsa_additional_error_text=s("AdditionalErrorText"),
        raw=raw,
    )
