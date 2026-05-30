"""Autopilot dispatcher — single entry point for the daily 3-checkpoint schedule.

Called by Windows Task Scheduler at:
  - 08:00 CST  → morning session (diagnostic-heavy bug investigation)
  - 14:00 CST  → afternoon report (summarize AM, prep PM)
  - 20:00 CST  → evening test (30 real VINs through pipeline)

Each session is a separate function. The dispatcher picks based on the
hour of day (CST) — robust against tasks firing slightly off schedule.

Per-session ScrapFly cap enforced via budget.py governor:
  - Morning: 1500 credits max
  - Evening: 2500 credits max (30 VINs)
  - Afternoon: <100 (log analysis only)

Run manually for testing:
    python scripts/autopilot.py morning
    python scripts/autopilot.py afternoon
    python scripts/autopilot.py evening
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_DIAGNOSTICS"] = "1"


def _today_cst() -> datetime:
    """Return current time in CST (UTC-6) — Task Scheduler uses local time
    but we normalize to CST for log filenames + consistency."""
    return datetime.now(timezone.utc) - timedelta(hours=6)


def _dispatch_from_clock() -> str:
    """Pick a session based on the hour in CST."""
    hr = _today_cst().hour
    if 6 <= hr < 12:
        return "morning"
    if 12 <= hr < 17:
        return "afternoon"
    return "evening"


async def session_morning() -> None:
    """AM: pick top item from QUEUE.md and dispatch to the matching
    investigation script. Each known investigation maps to a script in
    scripts/autopilot_*.py. Output goes to docs/daily/{date}_morning.md."""
    from lbt1 import diagnostics  # noqa: F401
    from lbt1.budget import allow_burn

    queue_path = Path(__file__).resolve().parents[1] / "docs" / "daily" / "QUEUE.md"
    next_task = ""
    if queue_path.exists():
        for line in queue_path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("- [ ]"):
                next_task = s[5:].strip()
                break
    print(f"[autopilot:morning] next queued: {next_task}")
    if not allow_burn(estimated_credits=1500):
        print("[autopilot:morning] daily budget too low — skipping investigation")
        return

    # Map queue text -> investigation script. The matcher is keyword-based
    # so we can add new investigations without touching this dispatcher.
    lower = next_task.lower()
    investigations = [
        ("toyotapartsdeal",     "autopilot_toyotapartsdeal_ajax.py"),
        ("reverse-engineer",    "autopilot_toyotapartsdeal_ajax.py"),
        ("toyota category",     "autopilot_toyota_categories.py"),
        ("toyota driver",       "autopilot_toyota_categories.py"),
        ("genesis simplepart",  "autopilot_genesis_simplepart.py"),
        ("genesis g70",         "autopilot_genesis_simplepart.py"),
        ("ev6",                 "autopilot_kia_ev6_trim.py"),
        ("palisade",            "autopilot_palisade_2025.py"),
        ("bug #2",              "autopilot_bug2_placeholder.py"),
        ("placeholder",         "autopilot_bug2_placeholder.py"),
        ("sonata",              "autopilot_sonata_deepdive.py"),
    ]
    chosen_script: str | None = None
    for kw, script in investigations:
        if kw in lower:
            p = Path(__file__).resolve().parent / script
            if p.exists():
                chosen_script = str(p)
                break
    today = _today_cst().strftime("%Y-%m-%d")
    report = Path(__file__).resolve().parents[1] / "docs" / "daily" / f"{today}_morning.md"
    report.parent.mkdir(parents=True, exist_ok=True)

    if not chosen_script:
        report.write_text(
            f"# Morning Report — {today}\n\n"
            f"**Queue top**: {next_task}\n\n"
            "No matching investigation script found. Add a script "
            "`scripts/autopilot_<name>.py` and register a keyword in "
            "`scripts/autopilot.py:investigations` to enable auto-dispatch.\n",
            encoding="utf-8")
        print(f"[autopilot:morning] no matching investigation — wrote {report}")
        return

    # Execute the investigation as a subprocess so its stdout becomes the
    # daily report's body. Capture+save.
    import subprocess
    print(f"[autopilot:morning] running {chosen_script}")
    proc = subprocess.run(
        [sys.executable, "-u", chosen_script],
        capture_output=True, text=True, timeout=2400,
        env={**os.environ, "LBT1_DIAGNOSTICS": "1"},
    )
    body = f"# Morning Report — {today}\n\n**Investigation**: {next_task}\n\n"
    body += f"**Script**: `{Path(chosen_script).name}`  exit={proc.returncode}\n\n"
    body += "## Output\n\n```\n" + (proc.stdout or "") + "\n```\n"
    if proc.stderr:
        body += "\n## Stderr\n\n```\n" + proc.stderr + "\n```\n"
    report.write_text(body, encoding="utf-8")
    print(f"[autopilot:morning] wrote {report} ({len(body)} chars)")


def session_afternoon() -> None:
    """PM: summarize today's diagnostics + verified deltas + ScrapFly burn."""
    from lbt1.budget import current_status, log_status_snapshot
    log_status_snapshot()
    status = current_status()
    today = _today_cst().strftime("%Y-%m-%d")
    out_path = Path(__file__).resolve().parents[1] / "docs" / "daily" / f"{today}_afternoon.md"
    diag_path = Path(__file__).resolve().parents[1] / "data" / "diagnostics" / f"{today}.jsonl"
    verified_today = 0
    failed_today = 0
    if diag_path.exists():
        import json
        for line in diag_path.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
                if e.get("outcome") == "verified":
                    verified_today += 1
                else:
                    failed_today += 1
            except Exception:
                pass
    lines = [
        f"# Afternoon Report — {today}",
        "",
        f"**ScrapFly status**: {status['used']}/{status['cap']} "
        f"({status['used_pct']:.1f}% used, {status['remaining']} credits left, "
        f"resets in {status['days_to_reset']} days)",
        "",
        f"**Today's diagnostic lookups**: {verified_today + failed_today} "
        f"(verified: {verified_today}, unverified: {failed_today})",
        "",
        "## Open queue",
        "(see docs/daily/QUEUE.md)",
        "",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[autopilot:afternoon] wrote {out_path}")


async def session_evening() -> None:
    """PM: run 30 fresh VINs through pipeline + capture coverage."""
    from lbt1 import pipeline
    from lbt1.budget import allow_burn, current_status
    # Read tonight's VIN list (auto-generated from prior verified set + fresh
    # additions). For first run, use the validated subset of earlier batches.
    vin_path = Path(__file__).resolve().parents[1] / "data" / "tonight_vins.csv"
    if not vin_path.exists():
        print("[autopilot:evening] no data/tonight_vins.csv — skipping. "
              "Run scripts/build_tonight_vins.py first.")
        return

    if not allow_burn(estimated_credits=2500):
        print("[autopilot:evening] daily budget exhausted — skipping evening test.")
        return

    import csv
    rows = list(csv.DictReader(vin_path.open(encoding="utf-8")))
    print(f"[autopilot:evening] running {len(rows)} VINs through pipeline")

    sem = asyncio.Semaphore(2)  # safe concurrency for Discovery plan + retry headroom
    async def one(vin: str) -> dict:
        async with sem:
            try:
                r = await pipeline.lookup(vin)
                return {"vin": vin, "status": r.dealer_verification_status,
                        "pn": r.primary_result.oem_part_number if r.primary_result else None}
            except Exception as exc:
                return {"vin": vin, "status": "ERROR", "pn": None, "err": str(exc)}

    results = await asyncio.gather(*(one(r["vin"]) for r in rows))
    today = _today_cst().strftime("%Y-%m-%d")
    out_path = Path(__file__).resolve().parents[1] / "docs" / "daily" / f"{today}_evening_test.md"
    verified = sum(1 for r in results if r["status"] == "DEALER_VERIFIED_BY_VIN")
    pct = verified / len(results) * 100 if results else 0
    lines = [
        f"# Evening Test — {today}",
        "",
        f"**Coverage**: {verified}/{len(results)} = {pct:.1f}% verified",
        "",
        "## Detail",
        "vin | status | pn",
        "----|--------|---",
    ]
    for r in results:
        lines.append(f"{r['vin']} | {r['status']} | {r.get('pn', '—') or '—'}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[autopilot:evening] wrote {out_path}")


def main() -> None:
    if len(sys.argv) > 1:
        session = sys.argv[1]
    else:
        session = _dispatch_from_clock()
    print(f"[autopilot] dispatching session: {session}  at {_today_cst().isoformat(timespec='seconds')} CST")
    if session == "morning":
        asyncio.run(session_morning())
    elif session == "afternoon":
        session_afternoon()
    elif session == "evening":
        asyncio.run(session_evening())
    else:
        print(f"[autopilot] unknown session: {session!r}")
        sys.exit(2)


if __name__ == "__main__":
    main()
