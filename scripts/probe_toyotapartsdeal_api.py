"""Probe toyotapartsdeal.com's discovered API endpoints with a test VIN.
The most-likely VIN candidate is /api/url/vehicle-redirect.

Also probe a couple of JS bundles we didn't reach in the first pass —
maybe a /api/vin/* endpoint hides in pages-BaseHome.js or extraLink.js.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

VIN = "4T1G11AK6R0123456"  # valid checksum 2024 Camry SE
BASE = "https://www.toyotapartsdeal.com"

# Try GETs on the most likely candidates (with VIN as query param)
GET_PROBES = [
    f"{BASE}/api/url/vehicle-redirect?vin={VIN}",
    f"{BASE}/api/url/vehicle-redirect?VIN={VIN}",
    f"{BASE}/api/url/no-vehicle-redirect?vin={VIN}",
    f"{BASE}/api/vehicle/make-list",  # sanity check
    # Maybe a vin-specific endpoint exists we didn't find
    f"{BASE}/api/vehicle/by-vin?vin={VIN}",
    f"{BASE}/api/vin/{VIN}",
    f"{BASE}/api/vin?vin={VIN}",
    f"{BASE}/api/vehicle/vin/{VIN}",
]

# Additional JS bundles we didn't probe in the first pass
JS_PROBES = [
    f"{BASE}/js/pages-BaseHome.js?v=2026052803",
    f"{BASE}/js/extraLink.js?v=2026052803",
    f"{BASE}/fwb_client/05091757_index.js",
]


async def main() -> None:
    backend = get_backend()
    try:
        # === GET probes
        print("=" * 90)
        print("GET PROBES")
        print("=" * 90)
        for url in GET_PROBES:
            print(f"\n— {url}")
            r = await backend.fetch(url)
            print(f"    status={r.status}  final={r.final_url}  len={len(r.html or '')}")
            if not r.ok:
                continue
            body = (r.html or "").strip()
            # Try parse as JSON
            try:
                data = json.loads(body)
                print(f"    JSON keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
                # Print first 600 chars of the JSON
                print(f"    body: {json.dumps(data)[:600]}")
            except Exception:
                # Not JSON — show first 300 chars
                print(f"    body[:300]: {body[:300]!r}")

        # === JS bundle probes (look for additional endpoints + form actions)
        print("\n" + "=" * 90)
        print("MORE JS BUNDLES")
        print("=" * 90)
        for url in JS_PROBES:
            print(f"\n— {url}")
            r = await backend.fetch(url)
            print(f"    status={r.status}  len={len(r.html or '')}")
            if not r.ok:
                continue
            body = r.html or ""
            endpoints = set()
            for pat in [
                r'["\'](/api/[\w\-./]+)["\']',
                r'["\'](/vin/[\w\-./]+)["\']',
                r'["\'](/[\w\-./%]*vin[\w\-./%]*)["\']',
                r'["\'](/[\w\-./%]+\.(?:ashx|aspx|ajax|json))["\']',
            ]:
                for m in re.finditer(pat, body, re.IGNORECASE):
                    candidate = m.group(1) if m.groups() else m.group(0)
                    if len(candidate) < 100:
                        endpoints.add(candidate)
            print(f"    endpoints found: {len(endpoints)}")
            for ep in sorted(endpoints)[:25]:
                print(f"      {ep}")

            # Also look for 'vin' mentions in context
            for m in re.finditer(r"[\w'\"`]{1,40}vin[\w'\"`]{1,40}", body, re.IGNORECASE):
                snip = m.group(0)
                if len(snip) > 6:
                    print(f"      vin-context: {snip!r}")
                    break  # one example is enough
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
