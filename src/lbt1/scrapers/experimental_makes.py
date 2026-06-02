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


# Future additions (Ford, GM, Stellantis, VW, Mitsubishi) require driver
# work for non-Revolution-Parts CMSs. Tracked in docs/make_playbook.md.
