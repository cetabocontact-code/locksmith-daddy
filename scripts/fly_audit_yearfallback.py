"""Run inside the Fly machine via `fly ssh console -C 'python /tmp/audit.py'`.

Checks the production lookups table for any results that came back during the
~19-minute window when year-fallback was live (v2 deploy → v3 revert). Reports
whether any real-user lookups returned a year-fallback PN.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path("/data/lbt1.db")


def main() -> None:
    if not DB_PATH.exists():
        print(f"NO DB at {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Schema snapshot
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )]
    print(f"Tables: {tables}\n")

    if "lookups" not in tables:
        print("No lookups table; nothing to audit.")
        return

    cols = [r["name"] for r in conn.execute("PRAGMA table_info(lookups)")]
    print(f"lookups columns: {cols}\n")

    total = conn.execute("SELECT COUNT(*) FROM lookups").fetchone()[0]
    print(f"Total lookup rows: {total}")

    recent = conn.execute(
        "SELECT * FROM lookups ORDER BY rowid DESC LIMIT 30"
    ).fetchall()
    print(f"\n=== Last 30 lookups (newest first) ===")
    for r in recent:
        row = dict(r)
        vin = row.get("vin", "?")
        status = row.get("dealer_verification_status", "?")
        ts = row.get("created_at") or row.get("ts") or row.get("timestamp")
        result_blob = row.get("result_json") or row.get("result") or ""
        # Probe for year-fallback markers
        is_yf = (
            "Year-fallback" in result_blob
            or "year-fallback" in result_blob
            or "prior model year" in result_blob.lower()
        )
        marker = "  <<< YEAR-FALLBACK" if is_yf else ""
        print(f"  ts={ts}  vin={vin}  status={status}{marker}")

    # Targeted hunt for year-fallback markers anywhere in result blob
    if "result_json" in cols or "result" in cols:
        col = "result_json" if "result_json" in cols else "result"
        rows = conn.execute(
            f"SELECT vin, dealer_verification_status, created_at, "
            f"substr({col}, 1, 200) AS snippet FROM lookups "
            f"WHERE {col} LIKE '%year-fallback%' "
            f"   OR {col} LIKE '%Year-fallback%' "
            f"   OR {col} LIKE '%prior model year%' "
            f"ORDER BY rowid DESC"
        ).fetchall()
        print(f"\n=== Year-fallback marker hits: {len(rows)} ===")
        for r in rows:
            print(f"  {dict(r)}")
    else:
        print(f"\n(No result_json/result column — can't grep for year-fallback markers)")


if __name__ == "__main__":
    main()
