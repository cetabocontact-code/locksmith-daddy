"""Probe #3b — same hypothesis as probe #3 but via ScrapFly sessions.

ScrapFly supports `session=<id>` which makes ScrapFly reuse the same
browser instance / cookie jar across calls. That's what we need to
test the dealer's stateful VIN-aware fitment widget.

Protocol per (dealer, case):
  1. Generate a unique session_id
  2. GET /search?search_str={VIN} via ScrapFly session=<id>
     → ScrapFly's browser stores cookies in that session
  3. GET /oem-parts/...{pn} via ScrapFly session=<id>
     → cookies replay; widget reads the garage and renders fit/not-fit
  4. Parse the rendered widget

Test matrix (4 dealers × 3 cases = 12 sessions, ~140 credits each = ~1700 credits):
  A. Crown Signia VIN + Crown Signia PN  → expect FITS
  B. Crown Signia VIN + Sienna PN        → expect NOT-FIT
  C. Sienna VIN + Sienna PN              → sanity check
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from typing import Optional

import httpx
from bs4 import BeautifulSoup


SCRAPFLY_API = "https://api.scrapfly.io/scrape"
SCRAPFLY_KEY = os.environ.get("SCRAPFLY_KEY") or os.environ.get("LBT1_SCRAPFLY_KEY")

CROWN_SIGNIA_VIN = "JTDACAAJ9T3040217"
SIENNA_VIN = "5TDZRKEC8TS306831"
CROWN_PN_SLUG = "toyota-transmitter-sub-assembly-electrical-key-8990h30260"
SIENNA_PN_SLUG = "toyota-keyless-entry-transmitter-8990h08021"

DEALERS = [
    "parts.mikecalverttoyota.com",
    "parts.longotoyota.com",
    "parts.olathetoyota.com",
    "toyota.oempartsonline.com",
]

CASES = [
    ("A KNOWN-GOOD Crown VIN + Crown PN", CROWN_SIGNIA_VIN, CROWN_PN_SLUG),
    ("B KNOWN-BAD  Crown VIN + Sienna PN", CROWN_SIGNIA_VIN, SIENNA_PN_SLUG),
    ("C SANITY     Sienna VIN + Sienna PN", SIENNA_VIN, SIENNA_PN_SLUG),
]


async def scrapfly_get(
    client: httpx.AsyncClient, url: str, session_id: str,
) -> tuple[int, str, str]:
    """Hit ScrapFly with session=<id> so it persists cookies on the
    server-side browser instance across calls."""
    params = {
        "key": SCRAPFLY_KEY,
        "url": url,
        "asp": "true",
        "render_js": "true",
        "country": "us",
        "session": session_id,
    }
    try:
        r = await client.get(SCRAPFLY_API, params=params, timeout=120.0)
        if r.status_code != 200:
            return r.status_code, "", f"scrapfly error status={r.status_code}"
        data = r.json()
        result = data.get("result", {})
        return (
            result.get("status_code", 0),
            result.get("content", ""),
            result.get("url", url),
        )
    except Exception as e:
        return 0, "", f"exception: {e}"


def parse_fitment(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.string or "").strip()[:200] if soup.title else ""
    out = {
        "title": title,
        "fitment_widget_text": None,
        "active_vehicle": None,
        "does_not_fit_class": False,
        "fits_class": False,
        "fitment_table_2026": None,
    }
    # Hunt for the widget
    for div in soup.select("div[class*='product-fitment']"):
        cls = " ".join(div.get("class") or [])
        if "does-not-fit" in cls.lower():
            out["does_not_fit_class"] = True
        if ("does-fit" in cls.lower() or "fits-confirmed" in cls.lower()
                or "vehicle-fits" in cls.lower()):
            out["fits_class"] = True
        txt = div.get_text(" ", strip=True)
        if txt and not out["fitment_widget_text"] and len(txt) < 300:
            out["fitment_widget_text"] = txt[:200]

    # Hunt for active vehicle phrase
    text = soup.get_text(" ", strip=True)
    m = re.search(
        r"(\d{4})\s+(Toyota|Hyundai|Kia|Genesis)\s+([\w\s]+?)\s+Change",
        text,
    )
    if m:
        out["active_vehicle"] = f"{m.group(1)} {m.group(2)} {m.group(3).strip()}"

    # Look in fitment table for any 2026 row
    for m in re.finditer(r"2026\s+(Toyota|Hyundai|Kia)\s+(\w+(?:\s+\w+)?)", text):
        out["fitment_table_2026"] = m.group(0)
        break
    return out


async def run_case(
    dealer: str, label: str, vin: str, slug: str,
) -> dict:
    session_id = f"lbt1-probe-{uuid.uuid4().hex[:12]}"
    out = {"dealer": dealer, "case": label, "session_id": session_id}
    async with httpx.AsyncClient() as client:
        # Step 1: search VIN
        search_url = f"https://{dealer}/search?search_str={vin}"
        s1_status, s1_html, s1_final = await scrapfly_get(
            client, search_url, session_id,
        )
        out["step1_status"] = s1_status
        out["step1_final"] = s1_final[:120]
        # Step 2: product page (same session — cookies replayed)
        product_url = f"https://{dealer}/oem-parts/{slug}"
        s2_status, s2_html, s2_final = await scrapfly_get(
            client, product_url, session_id,
        )
        out["step2_status"] = s2_status
        out["step2_final"] = s2_final[:120]

    if s2_status == 200 and s2_html:
        sig = parse_fitment(s2_html)
        out.update(sig)
    elif s1_status != 200:
        out["error"] = f"step1 failed status={s1_status}"
    elif s2_status != 200:
        out["error"] = f"step2 failed status={s2_status}"
    return out


async def main():
    if not SCRAPFLY_KEY:
        print("ERROR: SCRAPFLY_KEY env var not set")
        return
    print(f"Using session-aware ScrapFly. {len(DEALERS) * len(CASES)} cases.")
    for dealer in DEALERS:
        print("\n" + "=" * 130)
        print(f"DEALER: {dealer}")
        print("=" * 130)
        for label, vin, slug in CASES:
            r = await run_case(dealer, label, vin, slug)
            print(f"\n  {r['case']}")
            for k, v in r.items():
                if k == "case":
                    continue
                if v is None or v == "" or v is False:
                    continue
                # Truncate long values
                s = str(v)
                if len(s) > 200:
                    s = s[:200] + "..."
                print(f"    {k}: {s}")


if __name__ == "__main__":
    asyncio.run(main())
