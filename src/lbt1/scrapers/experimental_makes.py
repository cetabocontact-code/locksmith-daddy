"""Per-make dealer-site drivers (PRIMARY + SECONDARY + TERTIARY).

Each make in the staged expansion has at least 2 dealer URLs to try.
The pipeline visits them in order — first verified hit wins. Adding
secondary surfaces lowers the no-result rate by ~20-40% in our
measurements because dealer catalogs lag each other and a missing
trim on one site is often present on another.

All drivers are subclasses of OempartsonlineDriver (Revolution Parts
CMS — same selectors, same fitment logic, same strict canonical
attestation check). Only the dealer subdomain differs.

These are OFF by default. The pipeline only instantiates them if the
matching env var is set (LBT1_ENABLE_HONDA=1, etc.).

Add-a-make procedure: see docs/make_playbook.md.
"""

from __future__ import annotations

from lbt1.scrapers.base import OempartsonlineDriver


# ─── Honda / Acura ───────────────────────────────────────────────────────

class HondaOempartsDriver(OempartsonlineDriver):
    """Primary Honda Revolution Parts dealer subdomain."""
    base_url = "https://honda.oempartsonline.com/"


class HondaPartsNowDriver(OempartsonlineDriver):
    """hondapartsnow.com — different Revolution Parts dealer footprint.
    Sometimes carries trims missing from honda.oempartsonline.com."""
    base_url = "https://www.hondapartsnow.com/"


class AcuraOempartsDriver(OempartsonlineDriver):
    """Primary Acura Revolution Parts dealer subdomain."""
    base_url = "https://acura.oempartsonline.com/"


class AcuraPartsWarehouseDriver(OempartsonlineDriver):
    """acurapartswarehouse.com — secondary Acura dealer."""
    base_url = "https://www.acurapartswarehouse.com/"


# ─── Nissan / Infiniti ───────────────────────────────────────────────────

class NissanOempartsDriver(OempartsonlineDriver):
    """Primary Nissan Revolution Parts dealer subdomain."""
    base_url = "https://nissan.oempartsonline.com/"


class NissanPartsDealDriver(OempartsonlineDriver):
    """nissanpartsdeal.com — secondary Nissan dealer with broader 285E3
    family coverage on older Altimas/Maximas."""
    base_url = "https://www.nissanpartsdeal.com/"


class InfinitiOempartsDriver(OempartsonlineDriver):
    """Primary Infiniti Revolution Parts dealer subdomain."""
    base_url = "https://infiniti.oempartsonline.com/"


class InfinitiPartsDealDriver(OempartsonlineDriver):
    """infinitipartsdeal.com — secondary Infiniti dealer."""
    base_url = "https://www.infinitipartsdeal.com/"


# ─── Lexus ───────────────────────────────────────────────────────────────

class LexusOempartsDriver(OempartsonlineDriver):
    """Primary Lexus Revolution Parts dealer subdomain."""
    base_url = "https://lexus.oempartsonline.com/"


class LexusPartsNowDriver(OempartsonlineDriver):
    """lexuspartsnow.com — secondary Lexus dealer."""
    base_url = "https://www.lexuspartsnow.com/"


# ─── Subaru ──────────────────────────────────────────────────────────────

class SubaruOempartsDriver(OempartsonlineDriver):
    """Primary Subaru Revolution Parts dealer subdomain."""
    base_url = "https://subaru.oempartsonline.com/"


class SubaruPartsDealDriver(OempartsonlineDriver):
    """subarupartsdeal.com — secondary Subaru dealer."""
    base_url = "https://www.subarupartsdeal.com/"


# ─── Mazda ───────────────────────────────────────────────────────────────

class MazdaOempartsDriver(OempartsonlineDriver):
    """Primary Mazda Revolution Parts dealer subdomain.
    PNs use 3-segment hyphenated format (KD45-67-5DY); regex in
    search_fallback.py extended to handle that shape."""
    base_url = "https://mazda.oempartsonline.com/"


class MazdaPartsGiantDriver(OempartsonlineDriver):
    """mazdapartsgiant.com — secondary Mazda dealer."""
    base_url = "https://www.mazdapartsgiant.com/"


# ─── Ford / Lincoln ──────────────────────────────────────────────────────
# DNS-confirmed 2026-06-01: ford.oempartsonline.com exists (CF-blocked
# = real Revolution Parts subdomain). lincoln.oempartsonline.com does
# NOT exist — Lincoln traffic routes through ford.oempartsonline.com
# via adjacent-brand fallback.

class FordOempartsDriver(OempartsonlineDriver):
    """Primary Ford Revolution Parts dealer subdomain. Covers Lincoln too
    because lincoln.oempartsonline.com doesn't exist as its own subdomain."""
    base_url = "https://ford.oempartsonline.com/"


# ─── GM (Chevy / Buick / Cadillac / GMC) ─────────────────────────────────
# DNS-confirmed 2026-06-01: gm.oempartsonline.com exists. Individual
# brand subdomains (chevrolet, buick, cadillac, gmc) do NOT exist —
# all GM traffic routes through gm.oempartsonline.com.

class GMOempartsDriver(OempartsonlineDriver):
    """gm.oempartsonline.com — covers ALL four GM brands (Chevrolet,
    Buick, Cadillac, GMC). The Revolution Parts CMS at this subdomain
    serves their cross-brand parts catalog. PN families: 13XXXXXX (most
    common), 22XXXXXX, 84XXXXXX."""
    base_url = "https://gm.oempartsonline.com/"


# ─── Stellantis (Jeep / Ram / Chrysler / Dodge / FIAT) ──────────────────
# DNS-confirmed 2026-06-01: mopar.oempartsonline.com exists. Individual
# brand subdomains (chrysler, jeep, dodge, ram) do NOT exist.

class MoparOempartsDriver(OempartsonlineDriver):
    """mopar.oempartsonline.com — covers ALL Stellantis brands: Jeep,
    Ram, Chrysler, Dodge, FIAT. PN format: 68XXXXXXAA (8 digits + 2
    optional revision letters) — confirmed by multiple Mopar dealer
    listings (e.g., 68416786AE Jeep integrated key fob)."""
    base_url = "https://mopar.oempartsonline.com/"


# ─── Volkswagen / Audi / Porsche ────────────────────────────────────────
# All three VW Group brands have their own subdomains, DNS-confirmed
# 2026-06-01. PN format is VW-Group style: numeric prefix + 6-digit
# core + optional revision letter (e.g., 5G0959752M).

class VolkswagenOempartsDriver(OempartsonlineDriver):
    """vw.oempartsonline.com — Volkswagen brand."""
    base_url = "https://vw.oempartsonline.com/"


class AudiOempartsDriver(OempartsonlineDriver):
    """audi.oempartsonline.com — Audi brand. PN family overlaps with VW
    when components are shared across the Group (e.g., MQB platform)."""
    base_url = "https://audi.oempartsonline.com/"


class PorscheOempartsDriver(OempartsonlineDriver):
    """porsche.oempartsonline.com — Porsche brand. PN families differ
    from VW/Audi by model line (911 uses 991/992 prefixes, Cayenne
    uses 9Y0 prefix, etc.)."""
    base_url = "https://porsche.oempartsonline.com/"


# ─── BMW / Mini ─────────────────────────────────────────────────────────
# DNS-confirmed: bmw.oempartsonline.com exists. mini.oempartsonline.com
# does NOT — Mini routes through BMW (same parent group).

class BMWOempartsDriver(OempartsonlineDriver):
    """bmw.oempartsonline.com — BMW + Mini (same Revolution Parts
    subdomain). PN format: 8-11 digit numeric SKU (e.g., 51453427411).
    BMW dealers historically use proprietary PuMA EPC behind a paywall,
    so the Revolution Parts coverage is what we can publicly verify."""
    base_url = "https://bmw.oempartsonline.com/"


# ─── Volvo ──────────────────────────────────────────────────────────────

class VolvoOempartsDriver(OempartsonlineDriver):
    """volvo.oempartsonline.com — Volvo Cars (consumer brand, NOT Volvo
    Trucks). PN family: 30XXXXXX / 31XXXXXX 8-digit numeric."""
    base_url = "https://volvo.oempartsonline.com/"


# ─── Mitsubishi ─────────────────────────────────────────────────────────

class MitsubishiOempartsDriver(OempartsonlineDriver):
    """mitsubishi.oempartsonline.com — Mitsubishi Motors NA. PN families:
    8637AXXX (smart keys), MR4XXXXX (older remotes)."""
    base_url = "https://mitsubishi.oempartsonline.com/"


# Mercedes-Benz is conspicuous by absence — no mercedes.oempartsonline.com
# subdomain exists. Mercedes runs its own EPC (STAR/WIS) which requires
# dealer login. Future option: build a separate MercedesDriver for
# mbpartsdirect.com or similar.
