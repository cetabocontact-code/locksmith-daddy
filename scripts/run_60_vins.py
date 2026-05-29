"""Run the 60-VIN v1 validation set in batches of 2 concurrent lookups.

Writes:
  - data/v1_run/results.csv         compact summary, one row per VIN
  - data/v1_run/results.jsonl       full LookupResult per VIN, one line each
  - stdout                          progress log

Each VIN takes ~10–40 seconds, so a batch of 2 takes ~15–45s. Full run is
roughly 8–25 minutes.

The batches-of-2 cadence is deliberate: it stays under Cloudflare's
per-IP threshold for simultaneous sessions while still cutting wall-clock
time in half versus serial execution.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lbt1 import pipeline  # noqa: E402

VINS: list[str] = [
    # Hyundai / Genesis batch (30)
    "5NPD84LF1LH559355", "5NPD84LF0LH520658", "KMHD74LF9LU950788",
    "5NPD84LF8LH580655", "5NPLS4AG3MH004742", "5NPLN4AG4MH024800",
    "KM8K3CA51MU729825", "5NMJFCAE1NH068720", "5NMJE3AE2NH141225",
    "5NMJCCAE2NH064815", "KM8K33A37NU905292", "5NMJB3AE6PH190407",
    "5NMJECAE6PH207987", "KM8JF3AEXPU176759", "KMHL44J26PA298160",
    "KMHL64JA3PA319533", "5NMJBCDE3RH341346", "5NMJBCDE7RH357517",
    "5NMJBCDE5RH309000", "KMHL64JA1RA423408", "KMHL64JA5RA412315",
    "KM8KNDDF7RU254614", "KM8KM4DBXRU252503", "KMHL64JA5SA474898",
    "KMHL64JA3SA506750", "KMHL64JA2SA429014", "7YAKPDDC6SY033680",
    "KM8RJES22TU031551", "KM8RJES27TU024806", "7YAKM4DA8TY050263",
    # Kia batch (30)
    "KNDJ53AF3L7031331", "KNDJ23AUXL7735176", "KNDJ23AU0L7050944",
    "KNDJ33AU9L7065052", "KNDP6CAC7L7678621", "KNDP6CACXL7732705",
    "KNDJ63AUXM7756230", "KNDJ23AU4M7756316", "KNDEUCAA8M7176987",
    "KNDPM3AC7M7942430", "KNDEU2AA7N7315308", "KNDEU2AA3N7345700",
    "KNDEPCAA1N7281752", "KNDETCA26N7266698", "5XYK6CAFXPG116936",
    "5XYK6CAF3PG117474", "KNDPUCAFXP7132742", "5XYRH4LF9PG234715",
    "5XYP3DGC7PG356589", "KNDPU3DF6R7302965", "5XYK3CDF2RG212261",
    "KNDPU3DF5R7273698", "5XYRLDJC4RG261976", "5XYK23DF8SG317511",
    "KNDPU3DF9S7388827", "5XYK2CDF9SG309062", "5XYRKDJF7SG339444",
    "KNAG64J71T5454228", "KNAG64J70T5476513", "KNAG64J71T5466170",
]

BATCH_SIZE = 4

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "v1_run"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CSV_PATH = OUT_DIR / "results.csv"
JSONL_PATH = OUT_DIR / "results.jsonl"
LOG_PATH = OUT_DIR / "run.log"

CSV_FIELDS = [
    "i", "vin", "year", "make", "model", "trim",
    "status", "primary_pn", "primary_name", "alternates_count", "alternates",
    "duration_s", "confidence_label", "confidence_score", "warnings",
]


# Hard ceiling per VIN — no matter how many retries, give up after this.
# A normal Kia VIN takes 30–60s through ScrapingAnt; 4 category fetches × 60s
# worst-case + 2 retries each = ~360s upper bound. 240s catches any pathological
# hang without missing real long-running successes.
PER_VIN_TIMEOUT_S = 240.0


async def run_one(i: int, vin: str) -> dict:
    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(pipeline.lookup(vin), timeout=PER_VIN_TIMEOUT_S)
    except asyncio.TimeoutError:
        dur = int(round(time.monotonic() - t0))
        return {
            "i": i, "vin": vin, "duration_s": dur,
            "status": "ERROR", "error": f"timeout after {PER_VIN_TIMEOUT_S:.0f}s",
        }
    except Exception as exc:  # noqa: BLE001
        dur = int(round(time.monotonic() - t0))
        return {
            "i": i, "vin": vin, "duration_s": dur,
            "status": "ERROR", "error": str(exc),
        }

    p = result.vehicle_profile
    primary = result.primary_result
    alts = [a.oem_part_number for a in result.alternative_matches]
    dur = int(round(time.monotonic() - t0))
    return {
        "i": i,
        "vin": vin,
        "year": p.year,
        "make": p.make,
        "model": p.model,
        "trim": p.trim,
        "status": result.dealer_verification_status,
        "primary_pn": primary.oem_part_number if primary else None,
        "primary_name": primary.part_name if primary else None,
        "alternates_count": len(alts),
        "alternates": alts,
        "duration_s": dur,
        "confidence_label": result.confidence_label,
        "confidence_score": result.confidence_score,
        "warnings": result.warnings,
        "_full": result.model_dump(mode="json"),
    }


def format_row(r: dict) -> str:
    if r.get("status") == "ERROR":
        return f"[{r['i']+1:2}] {r['vin']} ERROR {r['duration_s']}s — {r.get('error','')[:120]}"
    vehicle = " ".join(str(x) for x in (r.get("year"), r.get("make"), r.get("model"), r.get("trim") or "") if x)
    primary = r.get("primary_pn") or "(none)"
    name = r.get("primary_name") or ""
    alts = ", ".join(r.get("alternates") or []) or "—"
    status_tag = "VER" if r.get("status") == "DEALER_VERIFIED_BY_VIN" else "NV "
    return (
        f"[{r['i']+1:2}] {status_tag} {r['vin']} | {vehicle:40s} | "
        f"PN={primary:14s} ({name[:30]:30s}) alts={alts[:60]:60s} | "
        f"{r['duration_s']:>2}s {r['confidence_label']}"
    )


def append_csv(rows: list[dict]) -> None:
    write_header = not CSV_PATH.exists()
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        for r in rows:
            row = {k: r.get(k) for k in CSV_FIELDS}
            if isinstance(row.get("alternates"), list):
                row["alternates"] = ", ".join(row["alternates"])
            if isinstance(row.get("warnings"), list):
                row["warnings"] = "; ".join(row["warnings"])
            writer.writerow(row)


def append_jsonl(rows: list[dict]) -> None:
    with JSONL_PATH.open("a", encoding="utf-8") as f:
        for r in rows:
            stripped = {k: v for k, v in r.items() if k != "_full"}
            stripped["_full"] = r.get("_full")
            f.write(json.dumps(stripped, default=str) + "\n")


def print_summary(rows: list[dict]) -> None:
    total = len(rows)
    verified = sum(1 for r in rows if r.get("status") == "DEALER_VERIFIED_BY_VIN")
    not_verified = sum(
        1 for r in rows if r.get("status") == "NOT_DEALER_VERIFIED_BY_VIN"
    )
    errors = sum(1 for r in rows if r.get("status") == "ERROR")
    no_primary = sum(
        1 for r in rows
        if r.get("status") == "DEALER_VERIFIED_BY_VIN" and not r.get("primary_pn")
    )

    # By make
    by_make: dict[str, dict[str, int]] = {}
    for r in rows:
        make = (r.get("make") or "(unknown)").title()
        bucket = by_make.setdefault(make, {"total": 0, "verified": 0, "errors": 0})
        bucket["total"] += 1
        if r.get("status") == "DEALER_VERIFIED_BY_VIN":
            bucket["verified"] += 1
        elif r.get("status") == "ERROR":
            bucket["errors"] += 1

    # By year band
    band_2019_plus = [r for r in rows if (r.get("year") or 0) >= 2019]
    band_2019_verified = sum(
        1 for r in band_2019_plus if r.get("status") == "DEALER_VERIFIED_BY_VIN"
    )

    durations = [r["duration_s"] for r in rows if isinstance(r.get("duration_s"), int)]
    avg_dur = sum(durations) / max(len(durations), 1)

    lines = [
        "",
        "==================== SUMMARY ====================",
        f"Total VINs       : {total}",
        f"Dealer-verified  : {verified} ({verified/total*100:.0f}%)",
        f"Not verified     : {not_verified}",
        f"Errors           : {errors}",
        f"Verified but no primary PN extracted: {no_primary}",
        f"Avg lookup       : {avg_dur:.1f}s",
        "",
        "By make:",
    ]
    for make, b in sorted(by_make.items()):
        rate = (b["verified"] / max(b["total"], 1)) * 100
        lines.append(
            f"  {make:10s}  verified {b['verified']:2d}/{b['total']:2d} ({rate:.0f}%)  errors {b['errors']}"
        )
    lines.append("")
    lines.append(
        f"2019+ (must-be-verified per requirement): "
        f"{band_2019_verified}/{len(band_2019_plus)} verified "
        f"({band_2019_verified/max(len(band_2019_plus),1)*100:.0f}%)"
    )
    lines.append(
        f"  failures in 2019+ band: "
        f"{[r['vin'] for r in band_2019_plus if r.get('status') != 'DEALER_VERIFIED_BY_VIN']}"
    )
    print("\n".join(lines))


async def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        stream=sys.stderr,
    )

    print(
        f"Starting v1 validation: {len(VINS)} VINs, batch size {BATCH_SIZE}\n"
        f"Output dir: {OUT_DIR}\n"
        f"Started:    {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n",
        flush=True,
    )

    all_rows: list[dict] = []
    batches = [VINS[i : i + BATCH_SIZE] for i in range(0, len(VINS), BATCH_SIZE)]
    t_start = time.monotonic()

    for batch_n, batch in enumerate(batches, 1):
        print(f"\n--- Batch {batch_n:2d}/{len(batches)}: {batch} ---", flush=True)
        offset = (batch_n - 1) * BATCH_SIZE
        batch_results = await asyncio.gather(
            *[run_one(offset + i, vin) for i, vin in enumerate(batch)],
            return_exceptions=False,
        )
        for r in batch_results:
            print(format_row(r), flush=True)
        all_rows.extend(batch_results)
        append_csv(batch_results)
        append_jsonl(batch_results)

    elapsed = int(time.monotonic() - t_start)
    print(f"\nBatch run finished in {elapsed}s.")
    print_summary(all_rows)


if __name__ == "__main__":
    # Clear any prior run before starting.
    for p in (CSV_PATH, JSONL_PATH, LOG_PATH):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    asyncio.run(main())
