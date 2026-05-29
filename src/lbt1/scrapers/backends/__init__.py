"""Pluggable scraping backends.

Each backend implements the same `ScrapeBackend.fetch()` interface so the
rest of the code (OempartsonlineDriver) doesn't care whether it's getting
HTML from a local Chromium, ScrapingAnt's API, or Bright Data Web Unlocker.
"""

from lbt1.scrapers.backends.base import FetchResult, ScrapeBackend
from lbt1.scrapers.backends.factory import get_backend

__all__ = ["FetchResult", "ScrapeBackend", "get_backend"]
