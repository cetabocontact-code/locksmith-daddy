"""Probe #3c — retry Olathe Toyota Case A multiple times to capture the
"this part fits your vehicle" widget appearance.

Olathe Toyota proved (Probe #3b) that the cookie-aware protocol works:
  - GET /search?VIN sets the 2026 Crown Signia as active vehicle
  - GET /oem-parts/{pn} reads that vehicle and shows fit/not-fit widget
  - For 8990H-08021 (Sienna PN) + 2026 Crown Signia VIN, widget said:
    "This part does not fit your vehicle" (does-not-fit-v2 class)

What we don't have: a TRUE POSITIVE — same VIN + correct PN.
We need to retry the protocol with 8990H-30260 (Crown Signia PN) until
step1 succeeds, then capture the positive widget pattern.

Retries up to 5 times with delay between attempts.
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid

import httpx
from bs4 import BeautifulSoup


SCRAPFLY_API = "https://api.scrapfly.io/scrape"
SCRAPFLY_KEY = os.environ.get("SCRAPFLY_KEY") or os.environ.get("LBT1_SCRAPFLY_KEY")

DEALER = "parts.olathetoyota.com"
VIN = "JTDACAAJ9T3040217"   # 2026 Crown Signia
SLUG = "toyota-transmitter-sub-assembly-electrical-key-8990h30260"


async def scrapfly_get(client: httpx.AsyncClient, url: str, session_id: str):
    params = {
        "key": SCRAPFLY_KEY, "url": url,
        "asp": "true", "render_js": "true",
        "country": "us", "session": session_id,
    }
    r = await client.get(SCRAPFLY_API, params=params, timeout=120.0)
    if r.status_code != 200:
        return None, r.status_code
    data = r.json()
    return data.get("result", {}), data.get("result", {}).get("status_code", 0)


async def main():
    if not SCRAPFLY_KEY:
        print("ERROR: SCRAPFLY_KEY not set")
        return

    for attempt in range(1, 6):
        session_id = f"lbt1-olathe-pos-{uuid.uuid4().hex[:12]}"
        print(f"\n=== Attempt {attempt}/5  session={session_id} ===")
        async with httpx.AsyncClient() as client:
            # Step 1: search VIN
            r1, code1 = await scrapfly_get(
                client, f"https://{DEALER}/search?search_str={VIN}", session_id,
            )
            inner_status1 = r1.get("status_code", 0) if r1 else 0
            print(f"step1: scrapfly={code1} inner={inner_status1}")
            if r1:
                print(f"       final: {r1.get('url', '')[:120]}")
            if inner_status1 != 200:
                if attempt < 5:
                    await asyncio.sleep(8)
                continue

            # Step 2: product page (same session)
            r2, code2 = await scrapfly_get(
                client, f"https://{DEALER}/oem-parts/{SLUG}", session_id,
            )
            inner_status2 = r2.get("status_code", 0) if r2 else 0
            print(f"step2: scrapfly={code2} inner={inner_status2}")
            if r2:
                print(f"       final: {r2.get('url', '')[:120]}")
                html = r2.get("content", "")
                soup = BeautifulSoup(html, "lxml")
                title = (soup.title.string or "").strip() if soup.title else ""
                print(f"       TITLE: {title[:160]}")

                # Look for fitment indicators
                for div in soup.select("div[class*='product-fitment'], div[class*='fitment-confirmation']"):
                    cls = " ".join(div.get("class") or [])
                    txt = div.get_text(" ", strip=True)
                    if txt and len(txt) < 300:
                        print(f"       FITMENT: <div class='{cls[:80]}'>: {txt[:200]}")

                # Active vehicle phrase
                text = soup.get_text(" ", strip=True)
                m = re.search(
                    r"(\d{4})\s+(Toyota|Hyundai|Kia|Genesis)\s+([\w\s]+?)\s+Change",
                    text,
                )
                if m:
                    print(f"       active_vehicle: {m.group(1)} {m.group(2)} {m.group(3).strip()}")

                # Search for "fits your vehicle" or similar positive markers
                for pat in [
                    r"this part fits? (?:your)?\s*vehicle",
                    r"perfect fit for your vehicle",
                    r"fits this vehicle",
                    r"confirmed fit",
                    r"does[\s\-]?not[\s\-]?fit",
                ]:
                    for m in re.finditer(pat, text, re.IGNORECASE):
                        s_start = max(0, m.start() - 40)
                        s_end = min(len(text), m.end() + 80)
                        print(f"       MARKER ({pat}): ...{text[s_start:s_end]}...")
                        break

                # Save full HTML for offline inspection on the FIRST success
                with open("data/runs/olathe_positive_capture.html", "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"       Saved HTML to data/runs/olathe_positive_capture.html")
                return  # got a successful capture, exit
        if attempt < 5:
            await asyncio.sleep(8)

    print("\nAll 5 attempts failed to capture positive case.")


if __name__ == "__main__":
    asyncio.run(main())
