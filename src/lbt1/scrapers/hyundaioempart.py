"""hyundaioempart.com driver — secondary Hyundai dealer (fallback source).

Confirmed live 2026-05-28:
  - Same Revolution Parts CMS as hyundai.oempartsonline.com
  - Same input selectors, URL patterns, soft-chooser behavior
  - Same `.marketplace-info-col` / `.product-partnum` / `.product-title` HTML
  - Different dealer = different catalog completeness

Used as a fallback in pipeline.py when the primary Hyundai source returns
zero key PNs — useful for newer trims (2026 model year) whose data hasn't
landed in Revolution Parts yet but exists in this dealer's catalog.
"""

from __future__ import annotations

from lbt1.scrapers.base import OempartsonlineDriver


class HyundaiOemPartDriver(OempartsonlineDriver):
    """Secondary Hyundai catalog at hyundaioempart.com.

    Inherits everything from OempartsonlineDriver because the CMS is identical
    to oempartsonline.com (same dealer software vendor: Revolution Parts).
    Only the base_url changes.
    """

    base_url = "https://www.hyundaioempart.com/"
