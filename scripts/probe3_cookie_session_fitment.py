"""Probe #3 — cookie-aware session test against Mike Calvert + other dealers.

Hypothesis to confirm or refute:
  When you (a) GET /search?search_str={VIN} to set the dealer's session
  garage cookie, then (b) GET /oem-parts/{slug}-{pn} with the SAME cookie
  jar, the dealer's CMS renders a VIN-aware fitment widget that reliably
  says "fits" or "does not fit".

If true → build VinAwareFitmentDriver using this protocol.
If false → 2026 catalog data truly hasn't been published yet at any reachable URL.

Test matrix:
  A. KNOWN-GOOD: Crown Signia VIN + Crown Signia PN (8990H-30260) — expect FITS
  B. KNOWN-BAD : Crown Signia VIN + Sienna PN     (8990H-08021) — expect NOT-FIT
  C. CONTROL  : visit product page WITHOUT setting garage — expect no widget

Tested against 4 Toyota dealers:
  D1. parts.mikecalverttoyota.com   (user-confirmed this works manually)
  D2. parts.longotoyota.com         (different Texas dealer)
  D3. parts.olathetoyota.com        (Kansas dealer)
  D4. toyota.oempartsonline.com     (central oempartsonline.com — control)

Goal: identify which dealer(s) have BOTH (i) more recent fitment data
than central and (ii) a reliable session-aware widget we can parse.
"""

from __future__ import annotations

import asyncio
import re
from typing import List, Tuple

import httpx
from bs4 import BeautifulSoup


# Test cases per dealer:  (label, search_vin, product_slug)
# product_slug must match the dealer's URL convention.
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

# Real-browser headers — anti-bot will be more forgiving with these
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


def parse_fitment(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    out = {
        "title": (soup.title.string or "").strip()[:200] if soup.title else "",
        "fits_class": False,
        "does_not_fit_class": False,
        "fitment_widget_text": None,
        "active_vehicle": None,
        "static_fits_phrase": None,
    }
    # Look for the explicit widget div
    for div in soup.select("div[class*='product-fitment']"):
        cls = " ".join(div.get("class") or [])
        if "does-not-fit" in cls.lower():
            out["does_not_fit_class"] = True
        if "does-fit" in cls.lower() or "fits-confirmed" in cls.lower():
            out["fits_class"] = True
        txt = div.get_text(" ", strip=True)
        if txt and not out["fitment_widget_text"] and len(txt) < 300:
            out["fitment_widget_text"] = txt[:200]

    # The "active vehicle" — what the widget thinks the user is shopping for
    for sel in [".fitment-confirmation-component-ajax-wrapper",
                ".click-here-fitment-action.vehicle-info",
                ".product-fitment.vehicle-info"]:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(" ", strip=True)
            # Try to extract the YYYY Make Model phrase
            m = re.search(r"(\d{4})\s+(\w+)\s+([\w\s]+?)(?:Change|This part)", txt)
            if m:
                out["active_vehicle"] = f"{m.group(1)} {m.group(2)} {m.group(3).strip()}"
                break
            elif txt and len(txt) < 200:
                out["active_vehicle"] = txt[:150]
                break

    # Static "perfectly fit your YYYY Make Model" phrase (page title context)
    text = soup.get_text(" ", strip=True)
    m = re.search(r"perfectly fit your (\d{4}(?:[\-–—]\d{4})?\s+\w+\s+[\w\s]+?)vehicle",
                  text, re.IGNORECASE)
    if m:
        out["static_fits_phrase"] = m.group(1).strip()
    return out


async def test_dealer_case(
    client: httpx.AsyncClient, dealer: str, vin: str, product_slug: str,
    case_label: str,
) -> dict:
    base = f"https://{dealer}"
    # Step 1: search VIN to set garage cookie
    search_url = f"{base}/search?search_str={vin}"
    try:
        r1 = await client.get(search_url, follow_redirects=True, timeout=30.0)
    except Exception as e:
        return {"case": case_label, "step1_err": str(e)[:120]}

    # Step 2: visit product page in same session
    product_url = f"{base}/oem-parts/{product_slug}"
    try:
        r2 = await client.get(product_url, follow_redirects=True, timeout=30.0)
    except Exception as e:
        return {"case": case_label, "step2_err": str(e)[:120]}

    sig = parse_fitment(r2.text)
    return {
        "case": case_label,
        "dealer": dealer,
        "step1_status": r1.status_code,
        "step1_final": str(r1.url)[:120],
        "step2_status": r2.status_code,
        "step2_final": str(r2.url)[:120],
        "title": sig["title"],
        "fitment_widget": sig["fitment_widget_text"],
        "active_vehicle": sig["active_vehicle"],
        "does_not_fit_class": sig["does_not_fit_class"],
        "fits_class": sig["fits_class"],
        "static_fits_phrase": sig["static_fits_phrase"],
        "cookies_set": [c.name for c in client.cookies.jar][:8],
    }


async def main() -> None:
    cases_per_dealer: List[Tuple[str, str, str]] = [
        ("A KNOWN-GOOD  Crown Signia VIN + Crown Signia PN", CROWN_SIGNIA_VIN, CROWN_PN_SLUG),
        ("B KNOWN-BAD   Crown Signia VIN + Sienna PN     ", CROWN_SIGNIA_VIN, SIENNA_PN_SLUG),
        ("C SANITY     Sienna VIN + Sienna PN           ", SIENNA_VIN, SIENNA_PN_SLUG),
    ]

    for dealer in DEALERS:
        print("\n" + "=" * 130)
        print(f"DEALER: {dealer}")
        print("=" * 130)
        for label, vin, slug in cases_per_dealer:
            # Fresh client per case — clean cookie jar
            async with httpx.AsyncClient(headers=HEADERS, http2=False) as client:
                result = await test_dealer_case(client, dealer, vin, slug, label)
            print(f"\n  {result['case']}")
            for k, v in result.items():
                if k == "case":
                    continue
                if v is None or v == "" or v == []:
                    continue
                print(f"    {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
