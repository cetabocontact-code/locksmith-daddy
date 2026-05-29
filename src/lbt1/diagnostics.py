"""Diagnostic capture for autopilot analysis.

When a lookup is run with diagnostic capture enabled, we write a JSONL
record to data/diagnostics/{YYYY-MM-DD}.jsonl with:
  - vin, timestamp, duration_s
  - vehicle profile (NHTSA decode summary)
  - per-dealer attempt (URL resolved, categories swept, status codes,
    raw_html_path on failure)
  - final result status + PNs

The autopilot's morning investigation reads these JSONL files to identify
failure patterns without re-fetching from ScrapFly — saves credits and is
the foundation of the "diagnostic-heavy, ScrapFly-light" approach per
user 2026-05-29.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lbt1 import config


DIAGNOSTIC_DIR = Path(config.DATA_DIR) / "diagnostics"
HTML_SNAPSHOT_DIR = DIAGNOSTIC_DIR / "html_snapshots"


def _ensure_dirs() -> None:
    DIAGNOSTIC_DIR.mkdir(parents=True, exist_ok=True)
    HTML_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def snapshot_html(html: str, tag: str) -> str | None:
    """Save HTML gzipped to disk. Returns relative path. Used on failures
    so we can re-parse offline. Filename: {tag}_{hash[:10]}.html.gz to
    dedupe identical responses.
    """
    if not html:
        return None
    _ensure_dirs()
    h = hashlib.sha1(html.encode("utf-8", errors="ignore")).hexdigest()[:10]
    safe_tag = "".join(c if c.isalnum() or c in "-_" else "_" for c in tag)[:50]
    fname = f"{safe_tag}_{h}.html.gz"
    fpath = HTML_SNAPSHOT_DIR / fname
    if not fpath.exists():
        try:
            with gzip.open(fpath, "wb") as f:
                f.write(html.encode("utf-8", errors="ignore"))
        except OSError:
            return None
    return str(fpath.relative_to(Path(config.DATA_DIR)))


def record(entry: dict[str, Any]) -> None:
    """Append one VIN lookup's diagnostic data to today's JSONL file.

    Best-effort: never raises. The lookup pipeline runs even if diagnostic
    writes fail (e.g., disk full).
    """
    try:
        _ensure_dirs()
        entry.setdefault("ts", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out = DIAGNOSTIC_DIR / f"{date_tag}.jsonl"
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:  # noqa: BLE001
        pass


def diagnostics_enabled() -> bool:
    """Enabled when LBT1_DIAGNOSTICS=1 (autopilot/batch tests set this).
    Off by default for live user lookups (no extra disk I/O)."""
    return os.environ.get("LBT1_DIAGNOSTICS", "").strip() == "1"
