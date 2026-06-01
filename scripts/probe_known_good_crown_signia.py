"""Probe #2 — find the POSITIVE fitment marker pattern.

Known ground truth (manually verified by user on parts.mikecalverttoyota.com):
  VIN JTDACAAJ9T3040217 (2026 Toyota Crown Signia Limited Hybrid)
  PN  8990H-30260
  Dealer site said: "fits your car"

This probe tests the dealer's VIN-aware fitment surface in 6 combinations:

  TRUE positives (right PN, right VIN — expect "fits"):
    1. toyota.oempartsonline.com   /oem-parts/...8990H-30260?vin=<Crown Signia VIN>
    2. parts.mikecalverttoyota.com /oem-parts/...8990H-30260?vin=<Crown Signia VIN>
    3. toyota.oempartsonline.com   /v-2026-toyota-crown-signia?vin=<VIN> then search 8990H-30260

  TRUE negatives (wrong PN, right VIN — expect "does not fit"):
    4. toyota.oempartsonline.com   /oem-parts/...8990H-08021?vin=<Crown Signia VIN>   (Sienna PN, Crown Signia VIN)

  TRUE negative (right PN, wrong VIN — expect "does not fit"):
    5. toyota.oempartsonline.com   /oem-parts/...8990H-30260?vin=<Sienna VIN>          (Crown Signia PN, Sienna VIN)

  CONTROL (no VIN — should show generic fitment table):
    6. toyota.oempartsonline.com   /oem-parts/...8990H-30260   (no ?vin=)

Goal: identify exactly what HTML markers distinguish positive vs negative
attestation. Once we have that pattern, we know what VinAwareFitmentDriver
needs to parse for.
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bs4 import BeautifulSoup

from lbt1.scrapers.backends import get_backend


CASES = [
    # Label, URL
    ("1. POS: toyota.oempartsonline + Crown Signia VIN + Crown Signia PN",
     "https://toyota.oempartsonline.com/oem-parts/toyota-transmitter-sub-assembly-electrical-key-8990h30260?vin=JTDACAAJ9T3040217"),
    ("2. POS: parts.mikecalverttoyota + Crown Signia VIN + Crown Signia PN",
     "https://parts.mikecalverttoyota.com/oem-parts/toyota-transmitter-sub-assembly-electrical-key-8990h30260?vin=JTDACAAJ9T3040217"),
    ("3. POS-vehicle-page: toyota.oempartsonline /v-2026-toyota-crown-signia + VIN",
     "https://toyota.oempartsonline.com/v-2026-toyota-crown-signia?vin=JTDACAAJ9T3040217"),
    ("4. NEG (wrong PN): Crown Signia VIN + Sienna PN 8990H-08021",
     "https://toyota.oempartsonline.com/oem-parts/toyota-transmitter-sub-assembly-electrical-key-8990h08021?vin=JTDACAAJ9T3040217"),
    ("5. NEG (wrong VIN): Sienna VIN + Crown Signia PN 8990H-30260",
     "https://toyota.oempartsonline.com/oem-parts/toyota-transmitter-sub-assembly-electrical-key-8990h30260?vin=5TDZRKEC8TS306831"),
    ("6. CTRL: no VIN, Crown Signia PN only",
     "https://toyota.oempartsonline.com/oem-parts/toyota-transmitter-sub-assembly-electrical-key-8990h30260"),
]


def extract_fitment_signals(html: str) -> dict:
    """Pull every potential 'fits/does-not-fit' indicator from the HTML."""
    soup = BeautifulSoup(html, "lxml")
    out: dict = {
        "title": "",
        "h1": "",
        "fitment_classes": [],   # elements with class containing 'fitment' or 'vehicle'
        "fits_phrases": [],       # "fits your vehicle" / "does not fit" copy
        "vehicle_context": "",    # currently-selected vehicle if displayed
    }
    if soup.title:
        out["title"] = (soup.title.string or "").strip()[:200]
    h1 = soup.find("h1")
    if h1:
        out["h1"] = h1.get_text(" ", strip=True)[:200]

    # Hunt for fitment elements
    for sel in [
        "[class*='fitment']",
        "[class*='vehicle']",
        "[class*='confirmed']",
        "[class*='fit']",
        "[data-fits]",
        ".alert",
        ".badge",
    ]:
        for el in soup.select(sel):
            cls = " ".join(el.get("class") or [])
            txt = el.get_text(" ", strip=True)
            if txt and 5 < len(txt) < 300:
                out["fitment_classes"].append(f"<{el.name} class='{cls[:60]}'>: {txt[:160]}")

    # Hunt for natural-language fit copy in body text
    text = soup.get_text(" ", strip=True)
    for pat in [
        r"this part (does )?(not )?fit[s]?\s+your\s+vehicle",
        r"confirmed\s+(?:fit|for\s+your)",
        r"fits\s+this\s+vehicle",
        r"compatible\s+with\s+your\s+vehicle",
        r"will\s+fit\s+your\s+\d{4}",
        r"perfectly\s+fit\s+your\s+\d{4}\s+[a-z]+\s+[a-z]+",
        r"verify\s+fitment",
        r"select\s+(?:a\s+)?vehicle",
    ]:
        for m in re.finditer(pat, text, re.IGNORECASE):
            ctx_s = max(0, m.start() - 60)
            ctx_e = min(len(text), m.end() + 120)
            out["fits_phrases"].append(text[ctx_s:ctx_e].strip()[:200])

    # Hunt for the "Currently shopping for: <year> <make> <model>" panel
    for sel in [".vehicle-context", ".my-vehicle", ".garage", "[class*='current-vehicle']"]:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(" ", strip=True)
            if txt:
                out["vehicle_context"] = txt[:200]
                break

    # Dedup
    out["fitment_classes"] = list(dict.fromkeys(out["fitment_classes"]))[:8]
    out["fits_phrases"] = list(dict.fromkeys(out["fits_phrases"]))[:6]
    return out


async def main():
    backend = get_backend()
    for label, url in CASES:
        print("=" * 130)
        print(label)
        print(f"  URL: {url}")
        r = await backend.fetch(url)
        print(f"  status={r.status} ok={r.ok}")
        if not r.ok:
            print(f"  ERROR: {r.error}")
            continue
        sig = extract_fitment_signals(r.html)
        print(f"  TITLE: {sig['title']}")
        print(f"  H1   : {sig['h1']}")
        if sig["vehicle_context"]:
            print(f"  VEHICLE CONTEXT: {sig['vehicle_context']}")
        if sig["fitment_classes"]:
            print(f"  FITMENT ELEMENTS ({len(sig['fitment_classes'])}):")
            for f in sig["fitment_classes"][:5]:
                print(f"    • {f}")
        if sig["fits_phrases"]:
            print(f"  FIT PHRASES ({len(sig['fits_phrases'])}):")
            for p in sig["fits_phrases"][:5]:
                print(f"    • {p}")
    print("=" * 130)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
