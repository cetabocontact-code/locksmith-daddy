"""Kia oempartsonline.com driver."""

from __future__ import annotations

from lbt1.scrapers.base import OempartsonlineDriver


class KiaOempartsDriver(OempartsonlineDriver):
    """Drives kia.oempartsonline.com.

    Most of the navigation is shared with Hyundai (same Revolution Parts CMS).
    Make-specific overrides go here when the actual live DOM diverges from
    the base assumptions.
    """

    base_url = "https://kia.oempartsonline.com/"
