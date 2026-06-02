"""Probe which makes have a Revolution Parts subdomain on
oempartsonline.com. Free — pure DNS resolution + a tiny HEAD probe.
No ScrapFly cost. Tells us which new makes we can wire as one-line
driver subclasses vs. which need a full new-CMS driver.

Run: python scripts/probe_revolution_parts_subdomains.py
"""

from __future__ import annotations

import socket
import asyncio
import httpx
import ssl


CANDIDATES = [
    # Already confirmed working
    "hyundai.oempartsonline.com",  # ✅ control
    "toyota.oempartsonline.com",   # ✅ control
    # Big-3 Detroit (39% of US market)
    "ford.oempartsonline.com",
    "lincoln.oempartsonline.com",
    "chevrolet.oempartsonline.com",
    "chevy.oempartsonline.com",
    "buick.oempartsonline.com",
    "cadillac.oempartsonline.com",
    "gmc.oempartsonline.com",
    "gm.oempartsonline.com",
    # Stellantis (Mopar already confirmed)
    "mopar.oempartsonline.com",    # ✅ confirmed earlier
    "chrysler.oempartsonline.com",
    "jeep.oempartsonline.com",
    "dodge.oempartsonline.com",
    "ram.oempartsonline.com",
    # European
    "vw.oempartsonline.com",
    "volkswagen.oempartsonline.com",
    "audi.oempartsonline.com",
    "porsche.oempartsonline.com",
    "bmw.oempartsonline.com",
    "mini.oempartsonline.com",
    "mercedes.oempartsonline.com",
    "mercedesbenz.oempartsonline.com",
    "volvo.oempartsonline.com",
    "saab.oempartsonline.com",
    # Smaller
    "mitsubishi.oempartsonline.com",
    "smart.oempartsonline.com",
]


def dns_resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, 443)
        return True
    except socket.gaierror:
        return False


async def http_probe(host: str, timeout: float = 4.0) -> tuple[int, str]:
    """Tiny HEAD probe — does the server respond? 403 means it exists
    but Cloudflare blocks unauthenticated bots (still confirms domain).
    NXDOMAIN at DNS level is the only definitive 'doesn't exist'."""
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            verify=False,
            follow_redirects=False,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0"
                ),
            },
        ) as client:
            r = await client.head(f"https://{host}/")
            return r.status_code, "ok"
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return -1, "connect-fail"
    except ssl.SSLCertVerificationError:
        return -2, "ssl-cert-issue"
    except Exception as exc:  # noqa: BLE001
        return -3, f"{type(exc).__name__}: {exc}"


async def main():
    print(f"{'Subdomain':<42}  {'DNS':<5}  HTTP   Note")
    print("=" * 78)
    for host in CANDIDATES:
        dns_ok = dns_resolves(host)
        if not dns_ok:
            print(f"{host:<42}  {'NX':<5}  —      ❌ no such domain")
            continue
        status, note = await http_probe(host)
        if status > 0:
            mark = "✅" if status < 400 else (
                "✅ (CF-blocked, exists)" if status in (403, 429, 503) else f"⚠ {status}"
            )
            print(f"{host:<42}  {'ok':<5}  {status:<5}  {mark}")
        else:
            print(f"{host:<42}  {'ok':<5}  —      ⚠ {note}")


if __name__ == "__main__":
    asyncio.run(main())
