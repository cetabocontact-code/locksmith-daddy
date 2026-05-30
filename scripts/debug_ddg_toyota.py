import asyncio, httpx, re
from urllib.parse import quote_plus, unquote
from bs4 import BeautifulSoup

QUERIES = [
    'site:toyota.oempartsonline.com "89070" 2024 Camry',
    'site:toyota.oempartsonline.com "89070" Camry',
    'site:toyota.oempartsonline.com 89070 Camry',
    'site:toyota.oempartsonline.com 89070 transmitter',
]


async def main() -> None:
    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                 "AppleWebKit/537.36 (KHTML, like Gecko) "
                                 "Chrome/120.0.0.0 Safari/537.36",
                  "Accept-Language": "en-US,en;q=0.9"},
        timeout=30,
    ) as c:
        for q in QUERIES:
            print("=" * 90)
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(q)}"
            print(f"Q: {q}")
            r = await c.get(url)
            print(f"  status={r.status_code}  len={len(r.text)}")
            soup = BeautifulSoup(r.text, "lxml")
            results = soup.select(".result")
            print(f"  .result elements: {len(results)}")
            # Maybe DDG uses different CSS now
            for sel in (".web-result", "[data-testid='result']", "h2.result__title",
                        ".results_links_deep", ".result__url"):
                els = soup.select(sel)
                if els:
                    print(f"  alt selector {sel!r}: {len(els)}")
            for res in results[:3]:
                a = res.select_one(".result__a") or res.find("a")
                if not a:
                    continue
                href = a.get("href", "")
                m = re.search(r"uddg=([^&]+)", href)
                if m:
                    href = unquote(m.group(1))
                text = a.get_text(" ", strip=True)
                print(f"    {text[:90]}")
                print(f"    {href[:130]}")


asyncio.run(main())
