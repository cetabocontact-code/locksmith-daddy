"""JS-rendered probe across the *partsdeal/*partsnow family to:
  1. Capture the Site header value (or equivalent multi-tenant identifier)
  2. Extract `__INITIAL_STATE__` / siteInfo from rendered DOM
  3. Capture any XHR requests fired during page load
  4. Confirm/deny same backend across Toyota / Hyundai / Kia / Honda / Subaru

Uses ScrapFly's render_js + auto_scroll. Cost ~5 credits/session +
1 credit/30s + page weight. Estimate ~30-50 credits per site.

Sites to probe (one each — sample of the family):
  - toyotapartsdeal.com  (the target)
  - hyundaipartsdeal.com (Hyundai bonus source)
  - kiapartsnow.com      (Kia bonus source)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Pull ScrapFly key from .env
env_path = Path(__file__).resolve().parents[1] / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("SCRAPFLY_KEY="):
            os.environ["SCRAPFLY_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

API_KEY = os.environ["SCRAPFLY_KEY"]
SCRAPFLY_URL = "https://api.scrapfly.io/scrape"

SITES = [
    "https://www.toyotapartsdeal.com/",
    "https://www.hyundaipartsdeal.com/",
    "https://www.kiapartsnow.com/",
]


async def probe(client: httpx.AsyncClient, site_url: str) -> dict:
    params = {
        "key": API_KEY,
        "url": site_url,
        "country": "us",
        "asp": "true",
        "render_js": "true",
        # Wait for the page's React/Vue to fully hydrate before snapshot
        "wait_for_selector": "input[placeholder*='VIN']",
        # Some platforms set their multi-tenant config in cookies
        "cookies_jar": "true",
    }
    print(f"\nProbe {site_url}")
    try:
        r = await client.get(SCRAPFLY_URL, params=params, timeout=180)
    except Exception as exc:
        print(f"  EXCEPTION: {type(exc).__name__}: {exc}")
        return {"site": site_url, "ok": False, "exc": str(exc)}
    try:
        env = r.json()
    except Exception:
        print(f"  HTTP {r.status_code}  body[:300]={r.text[:300]}")
        return {"site": site_url, "ok": False, "http": r.status_code}

    result = env.get("result") or {}
    status = result.get("status_code", 0)
    content = result.get("content", "") or ""
    print(f"  upstream status: {status}  content len: {len(content)}")

    # Extract cookies the page set (most likely SiteId carrier)
    cookies = result.get("cookies") or []
    print(f"  cookies: {len(cookies)}")
    for c in cookies[:10]:
        name = c.get("name", "")
        value = c.get("value", "")
        # Don't dump giant session blobs; show first 80 chars
        print(f"    {name}={value[:80]}")

    # Look for embedded __INITIAL_STATE__ or siteInfo in the rendered HTML
    findings = {}
    for pat_name, pat in [
        ("__INITIAL_STATE__", r"window\.__INITIAL_STATE__\s*=\s*([{\[][^\n]+?)<\/script>"),
        ("__NUXT__",          r"window\.__NUXT__\s*=\s*([{\[][^\n]+?)<\/script>"),
        ("__APP_DATA__",      r"__APP_DATA__\s*=\s*([{\[][^\n]+?)<\/script>"),
        ("siteInfo",          r"['\"]siteInfo['\"]\s*:\s*(\{[^}]{0,500}\})"),
        ("Site-Id-meta",      r'<meta\s+[^>]*name=["\']site[_-]?id["\'][^>]*>'),
    ]:
        m = re.search(pat, content, re.IGNORECASE | re.DOTALL)
        if m:
            snip = m.group(1) if m.groups() else m.group(0)
            findings[pat_name] = snip[:500]
            print(f"  FOUND {pat_name}: {snip[:200]}")

    return {
        "site": site_url, "ok": status == 200, "status": status,
        "cookies": cookies, "findings": findings,
        "content_len": len(content),
    }


async def main() -> None:
    async with httpx.AsyncClient() as client:
        # Sequential — JS rendering is expensive, no parallel
        results = []
        for s in SITES:
            results.append(await probe(client, s))

    # Save raw findings for offline analysis
    out = Path(__file__).resolve().parents[1] / "data" / "runs" / "partsdeal_family_findings.json"
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {out}")

    # Comparison summary — do all three share the same Site cookie name?
    print("\n" + "=" * 90)
    print("CROSS-SITE COOKIE OVERLAP (multi-tenant hints)")
    print("=" * 90)
    cookie_names_per_site = []
    for r in results:
        names = {c.get("name") for c in r.get("cookies", [])}
        cookie_names_per_site.append((r["site"], names))
    if cookie_names_per_site:
        common = set.intersection(*(c for _, c in cookie_names_per_site)) if all(c for _, c in cookie_names_per_site) else set()
        print(f"  Cookies common across ALL probed sites: {common}")
        for s, names in cookie_names_per_site:
            print(f"  {s}: {names}")


if __name__ == "__main__":
    asyncio.run(main())
