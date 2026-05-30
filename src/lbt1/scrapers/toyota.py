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

    Status 2026-05-29: PARTIAL coverage. Exhaustive probe across
        - electrical--keyless-entry-components
        - electrical--anti-theft-system
        - electrical--anti-theft-components
        - electrical--ignition-lock
        - electrical--ignition-system
        - electrical--electrical-components
        - body--lock-cylinder-set (410 — doesn't exist on this dealer)
        - body--lock-and-hardware (only exterior door handles)
        - ignition--switches-solenoids-and-actuators
        - ignition--control-modules
    confirms that Revolution Parts does NOT carry standalone Toyota
    smart key fobs (89070-*, 89904-*). They appear to restrict these at
    the catalog level because Toyota smart keys require dealer
    programming (similar to many Lexus/luxury parts).

    Per AKS + NorthCoast Keyless guides, the canonical Toyota fob source
    is `toyotapartsdeal.com` — but it's a JS-rendered SPA. Reverse-
    engineering its AJAX VIN endpoint is queued as the next AM autopilot
    task (similar to how we found SimplePart's /wm.aspx/CreateVinLinks).

    For now this driver:
      - Resolves VIN to vehicle URL successfully (year segment fix applies)
      - Sweeps the same key-relevant categories as Hyundai/Kia
      - Will catch any future Toyota fob listings if/when Revolution Parts
        starts carrying them
      - Returns NOT_DEALER_VERIFIED_BY_VIN honestly when no fobs present
    """

    base_url = "https://toyota.oempartsonline.com/"

    # Standard 3 sweeps (same as Hyundai/Kia inherited). Even though
    # Revolution Parts doesn't carry Toyota fobs today, we keep the sweep
    # to catch any future listings + to validate the pipeline structurally.
