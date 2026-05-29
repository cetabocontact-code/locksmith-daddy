"""parts.hyundaiusa.com and parts.genesis.com return 422 from ScrapFly's ASP
endpoint. Try direct httpx with a real browser user-agent to see if they're
accessible without anti-bot bypass — if so, we can wire them with a plain
httpx-based backend instead of ScrapFly.
"""

from __future__ import annotations

import asyncio
import httpx


SITES = [
    "https://parts.hyundaiusa.com/",
    "https://parts.genesis.com/",
    "https://parts.kia.ca/",
    "https://refacciones.hyundai.com.mx/",
    "https://refacciones.kia.com.mx/",
]


async def probe(client: httpx.AsyncClient, url: str) -> None:
    print("=" * 80)
    print(url)
    try:
        r = await client.get(url, timeout=30, follow_redirects=True)
    except Exception as exc:
        print(f"  EXCEPTION: {type(exc).__name__}: {str(exc)[:120]}")
        return
    print(f"  status={r.status_code}  final={r.url}")
    print(f"  content-type: {r.headers.get('content-type', '')}")
    body = r.text or ""
    print(f"  body len: {len(body)}")
    if body:
        # First 200 chars or HTML title
        from bs4 import BeautifulSoup
        try:
            soup = BeautifulSoup(body, "lxml")
            title = (soup.title.string or "").strip() if soup.title else ""
            print(f"  title: {title[:120]}")
        except Exception:
            print(f"  body start: {body[:200]!r}")


async def main() -> None:
    # Real browser headers
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                  "image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    async with httpx.AsyncClient(headers=headers) as client:
        for url in SITES:
            await probe(client, url)


if __name__ == "__main__":
    asyncio.run(main())
