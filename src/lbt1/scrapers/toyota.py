"""Toyota Revolution Parts driver — toyota.oempartsonline.com.

Confirmed live 2026-05-29 same Revolution Parts CMS as Hyundai/Kia/Genesis:
  - `.marketplace-info-col` cards
  - /search?search_str={VIN} → /v-{year}-toyota-{model}--{trim}--{engine}
  - Same disambiguation pattern + ghost-link issue

Toyota model trims tend to be simpler than Hyundai/Kia (e.g. "LE", "SE",
"XLE", "Limited") so the existing trim scorer + year-segment filter
should work without changes.

OEM PN families for Toyota keys:
  - 89070-* = TRANSMITTER (key fob smart key)
  - 89904-* = FOB ASSY (newer smart keys)
  - 89742-* = REMOTE CONTROL TRANSMITTER (older flip keys)
  - 69515-* = KEY BLANK (uncut mechanical blank)
"""

from __future__ import annotations

from lbt1.scrapers.base import OempartsonlineDriver


class ToyotaOempartsDriver(OempartsonlineDriver):
    """Toyota dealer at toyota.oempartsonline.com (Revolution Parts CMS).

    Probe 2026-05-29 found that on 2024 Camry SE, the electrical/keyless-
    entry-components category contains only receivers/antennas/modules —
    the actual key fob (89904-*, 89070-*) is filed under different
    categories. So we sweep a broader set than the Hyundai/Kia drivers:
    """

    base_url = "https://toyota.oempartsonline.com/"

    # Expanded category sweep for Toyota (where key fobs actually live):
    category_paths: tuple[tuple[str, str], ...] = (
        ("electrical", "keyless-entry-components"),   # receivers/antennas
        ("electrical", "anti-theft-system"),
        ("electrical", "electrical-components"),
        # Toyota-specific homes for key fobs (probe-confirmed needed):
        ("body", "locks-and-hardware"),
        ("body", "body-hardware"),
        ("body", "keyless-entry-system"),
        ("accessories", "anti-theft"),
        ("accessories", "key-and-cylinder"),
    )
