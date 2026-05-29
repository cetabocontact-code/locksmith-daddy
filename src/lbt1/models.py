"""Pydantic models for the full lookup pipeline.

These types are the contract between the four layers (NHTSA decode, local cache,
live dealer scrape, confidence engine) and any consumer (CLI, API, frontend).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class KeyType(str, Enum):
    """Classification of the OEM key part, derived from the part-name label
    on the dealer page. Maps to the seven label strings observed in the CSV
    training data."""

    SMART_KEY = "smart_key"             # "fob smart key", "smart key"
    TRANSMITTER = "transmitter"         # "transmitter", "transmitter/tranciever"
    KEYLESS_ENTRY_TX = "keyless_entry"  # "keyless entry transmitter"
    REMOTE_CONTROL = "remote_control"   # "remote control"
    KEYLESS_LOCK_PAD = "lock_pad"       # "keyless lock pad"
    UNKNOWN = "unknown"


PART_NAME_TO_KEY_TYPE: dict[str, KeyType] = {
    "fob smart key": KeyType.SMART_KEY,
    "smart key": KeyType.SMART_KEY,
    "transmitter": KeyType.TRANSMITTER,
    "transmitter/tranciever": KeyType.TRANSMITTER,
    "keyless entry transmitter": KeyType.KEYLESS_ENTRY_TX,
    "remote control": KeyType.REMOTE_CONTROL,
    "keyless lock pad": KeyType.KEYLESS_LOCK_PAD,
}


DealerVerificationStatus = Literal["DEALER_VERIFIED_BY_VIN", "NOT_DEALER_VERIFIED_BY_VIN"]
ConfidenceLabel = Literal["HIGH", "MEDIUM", "LOW"]
StepStatus = Literal["info", "success", "warning", "error"]


class VehicleProfile(BaseModel):
    """Vehicle data decoded from the VIN.

    Carries everything NHTSA returns so downstream matchers (e.g. the dealer
    trim chooser) can disambiguate on any field — not just trim. Critical for
    VINs where NHTSA returns multi-valued trims like "SEL, Value Edition &
    Limited"; the engine + transmission + body still narrow to one URL.
    """

    vin: str
    year: int | None = None
    make: str | None = None
    model: str | None = None
    trim: str | None = None
    series: str | None = None
    series2: str | None = None
    body_class: str | None = None

    # Engine
    engine_model: str | None = None
    engine_manufacturer: str | None = None
    engine_cylinders: int | None = None
    engine_hp: int | None = None
    engine_configuration: str | None = None
    displacement_l: float | None = None
    displacement_cc: float | None = None
    fuel_type: str | None = None
    fuel_injection_type: str | None = None
    valve_train_design: str | None = None

    # Drivetrain
    drive_type: str | None = None
    transmission_style: str | None = None
    transmission_speeds: int | None = None

    # Body / occupancy
    doors: int | None = None
    seats: int | None = None
    seat_rows: int | None = None
    vehicle_type: str | None = None
    ncsa_body_type: str | None = None
    gvwr: str | None = None
    wheel_base_short: float | None = None

    # Manufacturing
    plant_country: str | None = None
    plant_state: str | None = None
    plant_city: str | None = None
    manufacturer: str | None = None
    base_price: str | None = None

    # Diagnostics
    nhtsa_error_code: str | None = None
    nhtsa_error_text: str | None = None
    nhtsa_additional_error_text: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_clean_decode(self) -> bool:
        return self.nhtsa_error_code == "0"

    @property
    def display(self) -> str:
        parts = [str(p) for p in (self.year, self.make, self.model, self.trim) if p]
        return " ".join(parts) if parts else self.vin

    def trim_candidates(self) -> list[str]:
        """If NHTSA returned a multi-valued trim like 'SEL, Value Edition &
        Limited', split into individual trim names. Includes series too."""
        out: list[str] = []
        for source in (self.trim, self.series, self.series2):
            if not source:
                continue
            # Normalize separators (comma, ampersand, slash)
            for piece in source.replace("&", ",").replace("/", ",").split(","):
                piece = piece.strip()
                if piece and piece.lower() not in {p.lower() for p in out}:
                    out.append(piece)
        return out

    def engine_slug_variants(self) -> list[str]:
        """Possible engine slugs to match against dealer data-engine attrs.
        Dealer convention: 2.5L-L4-Gas → '2-5l-l4-gas'."""
        variants: list[str] = []
        if self.displacement_l is None or self.engine_cylinders is None:
            return variants
        disp = f"{self.displacement_l:g}l".replace(".", "-")
        cyl = f"l{self.engine_cylinders}"  # L4, L6, V8 etc.
        fuel = (self.fuel_type or "gas").lower().split()[0]  # 'Gasoline' → 'gasoline'
        # Two common slug shapes:
        variants.append(f"{disp}-{cyl}-{fuel[:3]}")          # "2-5l-l4-gas"
        variants.append(f"{disp}-{cyl}-{fuel}")              # "2-5l-l4-gasoline"
        # V-config (V6/V8) sometimes appears as v6 instead of l6
        if self.engine_cylinders in (6, 8, 10, 12):
            v_cyl = f"v{self.engine_cylinders}"
            variants.append(f"{disp}-{v_cyl}-{fuel[:3]}")
        return variants


class OemPart(BaseModel):
    """A single OEM key/transmitter/fob part with all metadata needed by a locksmith."""

    oem_part_number: str
    part_name: str | None = None
    key_type: KeyType = KeyType.UNKNOWN
    button_count: int | None = None
    button_names: list[str] = Field(default_factory=list)
    fcc_id: str | None = None
    frequency: str | None = None
    chip: str | None = None
    source_url: str | None = None
    category_path: str | None = None  # e.g. "Electrical > Keyless Entry Components"
    fitment_evidence: str | None = None
    dealer_verified: bool = False
    notes: str | None = None


class ResearchStep(BaseModel):
    """One observable step in the research process. Streamed live to the UI."""

    timestamp: datetime
    step: str
    status: StepStatus = "info"
    detail: str | None = None


class LookupResult(BaseModel):
    """Final structured output of a VIN lookup. Matches the spec's JSON schema."""

    vin: str
    vehicle_profile: VehicleProfile
    dealer_verification_status: DealerVerificationStatus
    primary_result: OemPart | None = None
    replacement_part_numbers: list[str] = Field(default_factory=list)
    superseded_part_numbers: list[str] = Field(default_factory=list)
    alternative_matches: list[OemPart] = Field(default_factory=list)
    confidence_score: float = 0.0
    confidence_label: ConfidenceLabel = "LOW"
    research_steps: list[ResearchStep] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_screenshots: list[str] = Field(default_factory=list)
