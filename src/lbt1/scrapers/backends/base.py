"""Common contract every scraping backend implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class FetchResult:
    """Result of fetching a single URL.

    Attributes:
        status:    HTTP status of the final response (200 = OK, 403/503 =
                   anti-bot, 0 = transport error).
        final_url: URL after redirects. For oempartsonline.com, /search?VIN
                   redirects to /v-{year}-make-model-..., and the driver reads
                   this to construct category URLs.
        html:      Rendered HTML (post-JS for browser-capable backends).
        error:     Backend-side error message, if any. None means the fetch
                   succeeded at the network layer (the page may still be a
                   Cloudflare challenge — status will reflect that).
    """

    status: int
    final_url: str
    html: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True iff network-layer succeeded AND HTTP status is 2xx/3xx."""
        return self.error is None and 200 <= self.status < 400


class ScrapeBackend(ABC):
    """Implement fetch() to plug a new backend (Browserbase, custom proxy, etc.)."""

    name: str = "unknown"

    @abstractmethod
    async def fetch(self, url: str) -> FetchResult:
        """Fetch a single URL. Must return a FetchResult, never raise."""
        ...

    async def fetch_json_post(
        self,
        url: str,
        *,
        json_body: dict,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        """POST a JSON body to `url` and return the response.

        Used by the SimplepartDriver to call ASMX endpoints like
        /wm.aspx/CreateVinLinks that require POST + JSON + ASMX headers.
        Default raises NotImplementedError — backends must override to
        support POST. Drivers that need POST should check that the
        backend supports it before calling.
        """
        raise NotImplementedError(
            f"Backend {self.name!r} does not support POST. "
            "Use a backend that supports POST (e.g. ScrapFly)."
        )

    async def close(self) -> None:
        """Free any underlying resources (HTTP clients, browsers, etc.)."""
        return None
