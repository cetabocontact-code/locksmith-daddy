"""Autopilot AM investigation: reverse-engineer toyotapartsdeal.com's
VIN-search AJAX endpoint without paying for JS rendering.

Playbook (same one that found SimplePart's /wm.aspx/CreateVinLinks):
  1. Fetch the homepage HTML (cheap).
  2. List all custom <script src> URLs (skip 3rd-party CDNs).
  3. Fetch each JS bundle (cheap — plain GET).
  4. Grep for AJAX endpoint patterns: POST URLs, /api/, /sd/, .ashx, .ajax,
     fetch(), $.post, axios, etc.
  5. Print the candidate endpoints so we can build a TyotaPartsDealDriver.

Cost target: ~$0.10 (1 homepage + 3-5 JS bundle fetches at standard rate).
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

HOMEPAGE = "https://www.toyotapartsdeal.com/"

# Patterns that indicate AJAX endpoints / VIN search backends
ENDPOINT_PATTERNS = [
    r'["\'](/[\w\-./%]+\.(?:ashx|aspx|json|ajax|php)(?:/[\w]+)?)["\']',
    r'["\'](/api/[\w\-./%]+)["\']',
    r'["\'](/[\w\-./%]*(?:vin|search|vehicle|partial|catalog)[\w\-./%]*)["\']',
    r'url\s*:\s*["\']([^"\']+)["\']',
    r'fetch\s*\(\s*["\']([^"\']+)["\']',
    r'\$\.(?:get|post|ajax)\s*\(\s*["\']([^"\']+)["\']',
    r'axios\.(?:get|post)\s*\(\s*["\']([^"\']+)["\']',
]


async def main() -> None:
    backend = get_backend()
    try:
        # Step 1: homepage
        print("=" * 90)
        print(f"FETCH {HOMEPAGE}")
        r = await backend.fetch(HOMEPAGE)
        print(f"  status={r.status}  len={len(r.html or '')}")
        if not r.ok:
            print(f"  fetch failed: {r.error}")
            return

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.html, "lxml")

        # Step 2: list custom JS bundles
        third_party = (
            "google", "jquery.min", "bootstrap", "fontawesome", "cdn.jsdelivr",
            "cloudflare", "yandex", "googletagmanager", "facebook", "linkedin",
            "tiktok", "pinterest", "fbcdn", "doubleclick", "googleads",
            "ipayp", "polyfill", "/cdn-cgi/", "gtm.js", "analytics",
        )
        scripts = []
        for s in soup.find_all("script", src=True):
            src = s["src"]
            if not src:
                continue
            if any(t in src.lower() for t in third_party):
                continue
            # Make absolute
            if src.startswith("/"):
                src = "https://www.toyotapartsdeal.com" + src
            elif src.startswith("//"):
                src = "https:" + src
            scripts.append(src)

        print(f"\n  Custom <script src> URLs: {len(scripts)}")
        for src in scripts[:20]:
            print(f"    {src[:120]}")

        # Step 3+4: fetch each + grep for endpoints
        print("\n" + "=" * 90)
        print("ENDPOINT DISCOVERY in JS bundles")
        print("=" * 90)
        all_endpoints: set[str] = set()
        for src in scripts[:6]:  # cap to control cost
            print(f"\n— {src}")
            rj = await backend.fetch(src)
            if not rj.ok:
                print(f"    fetch failed: status={rj.status}")
                continue
            body = rj.html or ""
            print(f"    length: {len(body)}")
            local_endpoints = set()
            for pat in ENDPOINT_PATTERNS:
                for m in re.finditer(pat, body, re.IGNORECASE):
                    candidate = m.group(1) if m.groups() else m.group(0)
                    # Only interested in same-host paths
                    if (candidate.startswith("/")
                        and not candidate.startswith("//")
                        and len(candidate) < 120
                        and not candidate.endswith((".png", ".jpg", ".gif", ".svg", ".css", ".woff", ".woff2"))):
                        local_endpoints.add(candidate)
            print(f"    candidate endpoints: {len(local_endpoints)}")
            all_endpoints.update(local_endpoints)

        # Step 5: filter to most-likely-VIN-related
        print("\n" + "=" * 90)
        print("PRIORITY VIN/SEARCH/CATALOG ENDPOINTS")
        print("=" * 90)
        keys = ("vin", "search", "vehicle", "catalog", "partial", "ajax",
                "fitment", "lookup", "api")
        priority = sorted(e for e in all_endpoints if any(k in e.lower() for k in keys))
        for ep in priority:
            print(f"  {ep}")

        print(f"\nAll endpoints ({len(all_endpoints)}):")
        for ep in sorted(all_endpoints):
            print(f"  {ep}")

        # Also look at inline scripts on the homepage for "vin" mentions
        print("\n" + "=" * 90)
        print("INLINE SCRIPTS containing 'vin' (case-insensitive)")
        print("=" * 90)
        for i, s in enumerate(soup.find_all("script")):
            body = s.string or ""
            if body and "vin" in body.lower():
                preview = body.strip()[:1200].replace("\n", "\n      ")
                print(f"\n  --- inline script[{i}] ---")
                print(f"      {preview}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
