"""Probe Canadian and Mexican Hyundai/Kia parts catalogs to see if any of
them carry 2026 Elantra electrical/keyless catalog data that the US
Revolution Parts feed lacks.

Targets to probe:
  - Canada:  parts.hyundaicanada.com, hyundaicanada.com, parts.kia.ca,
             kia.ca, hyundaipartscanada.com
  - Mexico:  hyundai.com.mx, kia.com.mx, partes-hyundai.com.mx, refacciones
  - Official: parts.hyundaiusa.com, parts.kia.com (US OEM direct — more
              authoritative than Revolution Parts third-party dealers)

For each: check if the site exists, what catalog shape it uses, and
whether searching for our test VIN or the 2026 Elantra lands somewhere
with key/electrical data.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["LBT1_SCRAPE_BACKEND"] = "scrapfly"

from lbt1.scrapers.backends import get_backend  # noqa: E402

TEST_VIN = "KMHLM4DG3TU122912"

# Tier 1: Official manufacturer parts catalogs (the most authoritative source).
OFFICIAL_PARTS_HOMES = [
    "https://parts.hyundaiusa.com/",
    "https://parts.kia.com/",
    "https://parts.genesis.com/",
]

# Tier 2: Canadian regional dealers / official sites
CANADA_SITES = [
    "https://parts.hyundaicanada.com/",
    "https://www.hyundaicanada.com/en/owning/owners-corner/buy-parts",
    "https://parts.kia.ca/",
    "https://www.kia.ca/en/find-parts",
    "https://www.hyundaipartscanada.com/",
    "https://www.hyundaioemparts.ca/",
    "https://www.kiapartsdirect.ca/",
]

# Tier 3: Mexican catalogs
MEXICO_SITES = [
    "https://www.hyundai.com.mx/",
    "https://www.kia.com.mx/",
    "https://refacciones.hyundai.com.mx/",
    "https://refacciones.kia.com.mx/",
]

# Tier 4: Other Revolution Parts dealers for Hyundai (these all share the
# same upstream feed, so unlikely to help — but worth confirming).
OTHER_REVOLUTION_DEALERS = [
    "https://www.hyundaipartsdeal.com/",
    "https://www.hyundaipartsnow.com/",
    "https://www.hyundaiparts.com/",
    "https://www.hmaparts.com/",  # Hyundai Motor America
]


async def probe(backend, url: str) -> None:
    print(f"\n{'='*100}")
    print(f"{url}")
    try:
        r = await asyncio.wait_for(backend.fetch(url), timeout=45)
    except asyncio.TimeoutError:
        print("  TIMEOUT")
        return
    except Exception as exc:  # noqa: BLE001
        print(f"  EXCEPTION: {type(exc).__name__}: {exc}")
        return
    print(f"  status={r.status}  final={r.final_url}  htmllen={len(r.html or '')}")
    if r.error:
        print(f"  error: {r.error[:200]}")
        return

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.html or "", "lxml")
    title = (soup.title.string or "").strip() if soup.title else ""
    print(f"  title: {title[:160]}")

    # Hunt for clues about parts catalog shape:
    # - VIN search input
    # - link to "find your vehicle"
    # - hint of part-card markup
    html_lc = (r.html or "").lower()

    # 1. VIN search input?
    inputs = soup.find_all("input")
    vin_inputs = [
        i for i in inputs
        if "vin" in " ".join(
            (i.get(k, "") or "") for k in ("name", "id", "placeholder", "title")
        ).lower()
    ]
    print(f"  VIN-related inputs: {len(vin_inputs)}")
    for i in vin_inputs[:3]:
        attrs = {k: v for k, v in i.attrs.items() if isinstance(v, str)}
        print(f"    {attrs}")

    # 2. Any sign of part catalog / model picker?
    for tag in ("parts", "catalog", "vehicle", "search by vin", "find part",
                "encuentra", "buscar", "refacciones", "modelo", "modèle"):
        if tag in html_lc:
            idx = html_lc.find(tag)
            print(f"  [{tag!r} hint @ {idx}]: …{html_lc[max(0,idx-40):idx+80]}…")
            break

    # 3. If this looks like a Revolution Parts site, it'll have the same
    #    .marketplace-info-col / product-partnum selectors. We can confirm
    #    by spot-checking inline JS for 'oempartsonline' or 'revolutionparts'.
    for marker in ("revolutionparts", "marketplace-info-col", "product-partnum"):
        if marker in html_lc:
            print(f"  IS RevolutionParts CMS (marker={marker!r})")
            break


async def main() -> None:
    backend = get_backend()
    try:
        # Officials first — highest priority
        print("####################")
        print("# TIER 1: Official manufacturer parts catalogs")
        print("####################")
        for url in OFFICIAL_PARTS_HOMES:
            await probe(backend, url)

        print("\n####################")
        print("# TIER 2: Canada")
        print("####################")
        for url in CANADA_SITES:
            await probe(backend, url)

        print("\n####################")
        print("# TIER 3: Mexico")
        print("####################")
        for url in MEXICO_SITES:
            await probe(backend, url)

        print("\n####################")
        print("# TIER 4: Other US Revolution Parts dealers")
        print("####################")
        for url in OTHER_REVOLUTION_DEALERS:
            await probe(backend, url)
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
