"""Pick the right scraping backend based on environment configuration.

Resolution order when LBT1_SCRAPE_BACKEND=auto:
  1. scrapingant     if SCRAPINGANT_API_KEY is set
  2. brightdata      if BRIGHTDATA_API_KEY and BRIGHTDATA_ZONE are set
  3. local           fallback (won't bypass Cloudflare)
"""

from __future__ import annotations

import logging

from lbt1 import config
from lbt1.scrapers.backends.base import ScrapeBackend

log = logging.getLogger(__name__)


def get_backend() -> ScrapeBackend:
    name = (config.SCRAPE_BACKEND or "auto").strip().lower()

    if name == "auto":
        if config.SCRAPFLY_KEY:
            name = "scrapfly"
        elif config.SCRAPERAPI_KEY:
            name = "scraperapi"
        elif config.SCRAPINGANT_API_KEY:
            name = "scrapingant"
        elif config.BRIGHTDATA_API_KEY and config.BRIGHTDATA_ZONE:
            name = "brightdata"
        else:
            name = "local"

    if name == "scrapfly":
        if not config.SCRAPFLY_KEY:
            raise RuntimeError(
                "LBT1_SCRAPE_BACKEND=scrapfly but SCRAPFLY_KEY is unset"
            )
        from lbt1.scrapers.backends.scrapfly import ScrapFlyBackend
        log.info("Using ScrapFly backend (ASP + residential proxy)")
        return ScrapFlyBackend(config.SCRAPFLY_KEY)

    if name == "apify":
        if not config.APIFY_TOKEN:
            raise RuntimeError(
                "LBT1_SCRAPE_BACKEND=apify but APIFY_TOKEN is unset"
            )
        from lbt1.scrapers.backends.apify import ApifyBackend
        log.info("Using Apify backend (puppeteer-scraper + residential proxy)")
        return ApifyBackend(config.APIFY_TOKEN)

    if name == "scraperapi":
        if not config.SCRAPERAPI_KEY:
            raise RuntimeError(
                "LBT1_SCRAPE_BACKEND=scraperapi but SCRAPERAPI_KEY is unset"
            )
        from lbt1.scrapers.backends.scraperapi import ScraperApiBackend
        log.info("Using ScraperAPI backend (premium → ultra_premium auto-escalation)")
        return ScraperApiBackend(config.SCRAPERAPI_KEY)

    if name == "scrapingant":
        if not config.SCRAPINGANT_API_KEY:
            raise RuntimeError(
                "LBT1_SCRAPE_BACKEND=scrapingant but SCRAPINGANT_API_KEY is unset"
            )
        from lbt1.scrapers.backends.scrapingant import ScrapingAntBackend
        log.info("Using ScrapingAnt backend (residential proxy + browser)")
        return ScrapingAntBackend(config.SCRAPINGANT_API_KEY)

    if name == "brightdata":
        if not (config.BRIGHTDATA_API_KEY and config.BRIGHTDATA_ZONE):
            raise RuntimeError(
                "LBT1_SCRAPE_BACKEND=brightdata but BRIGHTDATA_API_KEY or "
                "BRIGHTDATA_ZONE is unset"
            )
        from lbt1.scrapers.backends.brightdata import BrightDataWebUnlockerBackend
        log.info("Using Bright Data Web Unlocker backend")
        return BrightDataWebUnlockerBackend(
            api_key=config.BRIGHTDATA_API_KEY, zone=config.BRIGHTDATA_ZONE
        )

    from lbt1.scrapers.backends.local_playwright import LocalPlaywrightBackend
    log.info("Using local Playwright backend (Cloudflare will block protected sites)")
    return LocalPlaywrightBackend()
