"""Hyundai oempartsonline.com driver."""

from __future__ import annotations

from lbt1.scrapers.base import OempartsonlineDriver


class HyundaiOempartsDriver(OempartsonlineDriver):
    """Drives hyundai.oempartsonline.com.

    Same Revolution Parts CMS as kia.oempartsonline.com, so all navigation
    logic, selectors, and category paths are inherited from the base.
    """

    base_url = "https://hyundai.oempartsonline.com/"
