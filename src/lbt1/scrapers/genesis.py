"""Genesis oempartsonline.com driver."""

from __future__ import annotations

from lbt1.scrapers.base import OempartsonlineDriver


class GenesisOempartsDriver(OempartsonlineDriver):
    """Drives genesis.oempartsonline.com.

    Genesis is Hyundai's luxury brand; the parts catalog lives at its own
    subdomain but uses the same Revolution Parts CMS as Hyundai/Kia, so the
    same selector + category-sweep logic applies.
    """

    base_url = "https://genesis.oempartsonline.com/"
