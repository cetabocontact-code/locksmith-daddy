"""Standalone CLI for testing the pipeline before the FastAPI backend lands.

Examples:
    python -m lbt1.cli decode 5XYK6CDF8TG390982
    python -m lbt1.cli lookup 5XYK6CDF8TG390982 --headed
    python -m lbt1.cli validate 5XYK6CDF8TG390982
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table

from lbt1 import pipeline
from lbt1.models import LookupResult
from lbt1.vin import decoder, validator

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


@app.command()
def validate(vin: str, no_checksum: bool = typer.Option(False, "--no-checksum")) -> None:
    """Check that a VIN is well-formed (length, chars, ISO 3779 check digit)."""
    try:
        clean = validator.validate(vin, check_checksum=not no_checksum)
    except validator.VinValidationError as exc:
        console.print(f"[red]Invalid:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]OK:[/green] {clean}")


@app.command()
def decode(vin: str) -> None:
    """Run NHTSA VPIC decode only — fast, no scraping."""
    try:
        profile = decoder.decode_sync(vin)
    except validator.VinValidationError as exc:
        console.print(f"[red]Invalid VIN:[/red] {exc}")
        raise typer.Exit(1)
    except decoder.NhtsaDecodeError as exc:
        console.print(f"[red]NHTSA error:[/red] {exc}")
        raise typer.Exit(2)

    table = Table(title=f"NHTSA decode for {profile.vin}", show_header=False)
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    for field in (
        "year", "make", "model", "trim", "series", "series2",
        "body_class", "engine_model", "displacement_l", "fuel_type",
        "drive_type", "doors", "vehicle_type", "plant_country", "plant_state",
        "nhtsa_error_code", "nhtsa_error_text",
    ):
        value = getattr(profile, field)
        if value is not None:
            table.add_row(field, str(value))
    console.print(table)


@app.command()
def lookup(
    vin: str,
    headed: bool = typer.Option(False, "--headed", help="Show the browser window."),
    screenshot_dir: Path = typer.Option(
        Path("data/runs"),
        "--screenshots",
        help="Where to write evidence screenshots.",
    ),
    json_out: bool = typer.Option(False, "--json", help="Print result as JSON only."),
) -> None:
    """Full pipeline: NHTSA decode + Playwright Kia dealer-site scrape.

    Returns either a DEALER_VERIFIED_BY_VIN or NOT_DEALER_VERIFIED_BY_VIN result.
    """
    asyncio.run(_run_lookup(vin, headed=headed, screenshot_dir=screenshot_dir, json_out=json_out))


async def _run_lookup(vin: str, *, headed: bool, screenshot_dir: Path, json_out: bool) -> None:
    """Go through pipeline.lookup() — same code path the API/webapp use.
    Dispatches the correct make-specific driver (Kia vs Hyundai vs Genesis)."""
    profile = await decoder.decode(vin)
    if not json_out:
        console.print(Panel(f"[bold]{profile.display}[/bold]\nVIN: {profile.vin}", title="Decoded"))

    result = await pipeline.lookup(
        vin,
        step_callback=_render_step if not json_out else None,
    )

    if json_out:
        print(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
    else:
        _render_result(result)


def _render_step(step) -> None:
    color = {"info": "white", "success": "green", "warning": "yellow", "error": "red"}.get(
        step.status, "white"
    )
    detail = f"  [{color}]{step.detail}[/{color}]" if step.detail else ""
    console.print(f"[{color}]·[/{color}] {step.step}{detail}")


def _render_result(result: LookupResult) -> None:
    status_color = "green" if result.dealer_verification_status == "DEALER_VERIFIED_BY_VIN" else "yellow"
    console.print()
    console.print(
        Panel(
            f"Status: [{status_color}]{result.dealer_verification_status}[/{status_color}]\n"
            f"Confidence: {result.confidence_label} ({result.confidence_score:.2f})",
            title="Result",
        )
    )

    if result.primary_result:
        table = Table(title="Primary OEM part", show_header=True)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        p = result.primary_result
        for k in ("oem_part_number", "part_name", "key_type", "source_url", "category_path"):
            v = getattr(p, k)
            if v is not None:
                table.add_row(k, str(v))
        console.print(table)

    if result.alternative_matches:
        alts = Table(title=f"Alternative matches ({len(result.alternative_matches)})")
        alts.add_column("PN")
        alts.add_column("Name")
        alts.add_column("Category")
        for a in result.alternative_matches:
            alts.add_row(a.oem_part_number, a.part_name or "", a.category_path or "")
        console.print(alts)


def main() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    app()


if __name__ == "__main__":
    main()
