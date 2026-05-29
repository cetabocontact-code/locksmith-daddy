"""Seed the SQLite database with VIN lookups that returned a verified result
in our most recent batch run. These power the v0.1 Beta — when a locksmith
enters one of these VINs, the app serves the cached dealer-verified result
without hitting the live scraper.

Cache rows are tagged with a synthetic system user (email locksmithbrain@local)
and `expires_at` is set 100 years out so they never get auto-purged.

Run:
    python scripts/seed_cache.py [path/to/results.jsonl]
Default path: data/v1_run/results.jsonl
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lbt1 import auth, db  # noqa: E402

SYSTEM_EMAIL = "system@locksmithbrain.local"
SYSTEM_NAME = "Locksmith Brain (cached)"


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parents[1] / "data" / "v1_run" / "results.jsonl"
    )
    if not src.exists():
        print(f"No results file found at {src}", file=sys.stderr)
        sys.exit(1)

    db.init_db()
    user_id = _ensure_system_user()

    print(f"Seeding from {src} into {db.config.DB_PATH}")
    seeded = 0
    skipped = 0
    with src.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            full = row.get("_full")
            if not full:
                continue
            if full.get("dealer_verification_status") != "DEALER_VERIFIED_BY_VIN":
                skipped += 1
                continue
            primary = full.get("primary_result") or {}
            if not primary.get("oem_part_number"):
                skipped += 1
                continue

            # Force expires_at far future so the system row never auto-purges.
            try:
                _insert_cache_row(user_id, row["vin"], full)
                seeded += 1
            except Exception as exc:  # noqa: BLE001
                print(f"  SKIP {row.get('vin')}: {exc}", file=sys.stderr)
                skipped += 1

    print(f"Seeded {seeded} verified VINs. Skipped {skipped}.")


def _ensure_system_user() -> int:
    """Create or fetch the synthetic 'system' user that owns cache rows."""
    row = db.get_user_by_email(SYSTEM_EMAIL)
    if row is not None:
        return int(row["id"])
    return db.create_user(
        email=SYSTEM_EMAIL,
        password_hash=auth.hash_password("system-cache-unreachable-random-pwd"),
        full_name=SYSTEM_NAME,
        phone="000-000-0000",
        state_lic="SYSTEM",
        locksmith_lic=None,
        newsletter_opt_in=False,
    )


def _insert_cache_row(user_id: int, vin: str, full: dict) -> None:
    """Insert into lookups with a far-future expires_at so it's permanent."""
    import sqlite3
    far_future = (datetime.now(timezone.utc) + timedelta(days=36500)).isoformat(
        timespec="seconds"
    )
    primary = full.get("primary_result") or {}
    with db.get_db() as conn:
        try:
            conn.execute(
                """
                INSERT INTO lookups(
                    user_id, vin, created_at, duration_seconds,
                    dealer_verification_status, primary_pn,
                    confidence_score, confidence_label,
                    result_json, expires_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, vin, db.utcnow_iso(), 0,
                    full.get("dealer_verification_status", "DEALER_VERIFIED_BY_VIN"),
                    primary.get("oem_part_number"),
                    float(full.get("confidence_score", 0.9)),
                    full.get("confidence_label", "HIGH"),
                    json.dumps(full, default=str),
                    far_future,
                ),
            )
        except sqlite3.IntegrityError:
            # Duplicate VIN for this user — ignore.
            pass


if __name__ == "__main__":
    main()
