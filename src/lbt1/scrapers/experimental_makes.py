"""Revolution-Parts subdomain drivers for makes we haven't yet validated
on live customer traffic. Each is a one-line subclass of the proven
OempartsonlineDriver base — same selectors, same fitment logic, same
strict canonical attestation check. Only the dealer subdomain differs.

These are OFF by default. The pipeline only instantiates them if the
matching env var is set (LBT1_ENABLE_HONDA=1, etc.). That keeps live
customer lookups safe while letting an operator (or the founder, via
flyctl secrets) flip a make on for staged testing without a code
deploy.

Add-a-make procedure: see docs/make_playbook.md.
"""

from __future__ import annotations

from lbt1.scrapers.base import OempartsonlineDriver


class HondaOempartsDriver(OempartsonlineDriver):
    """honda.oempartsonline.com — Revolution Parts CMS, identical
    structure to Hyundai/Kia/Toyota dealer pages."""
    base_url = "https://honda.oempartsonline.com/"


class AcuraOempartsDriver(OempartsonlineDriver):
    """acura.oempartsonline.com — Honda's luxury brand, shares the
    same PN family (35118 / 72147) and CMS as Honda."""
    base_url = "https://acura.oempartsonline.com/"


class NissanOempartsDriver(OempartsonlineDriver):
    """nissan.oempartsonline.com — Revolution Parts CMS. Nissan smart
    keys live under the 285E3-XXXXX PN family."""
    base_url = "https://nissan.oempartsonline.com/"


class InfinitiOempartsDriver(OempartsonlineDriver):
    """infiniti.oempartsonline.com — Nissan's luxury brand, same 285E3
    PN family. Adjacent fallback to Nissan dealer subdomain."""
    base_url = "https://infiniti.oempartsonline.com/"


class LexusOempartsDriver(OempartsonlineDriver):
    """lexus.oempartsonline.com — Toyota luxury brand, shares the 8990H
    / 89070 / 89904 smart-key families."""
    base_url = "https://lexus.oempartsonline.com/"


class SubaruOempartsDriver(OempartsonlineDriver):
    """subaru.oempartsonline.com — Revolution Parts CMS. Subaru smart
    keys live under 57497AXXXXX family."""
    base_url = "https://subaru.oempartsonline.com/"


class MazdaOempartsDriver(OempartsonlineDriver):
    """mazda.oempartsonline.com — Revolution Parts CMS. Mazda PNs use
    3-segment hyphenated format (KD45-67-5DY style); regex in
    search_fallback.py extended to handle that."""
    base_url = "https://mazda.oempartsonline.com/"


# Future additions (Ford, GM, Stellantis, VW, Mitsubishi) require either
# probing whether these subdomains exist OR adding drivers for the
# manufacturer-direct catalogs (fordparts.com, gmpartsgiant.com,
# moparpartsgiant.com). Tracked in docs/make_playbook.md.
