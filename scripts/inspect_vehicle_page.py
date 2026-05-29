"""Inspect the page reached after VIN search — find the catalog navigation
structure so the scraper can sweep categories."""

from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/127.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        # Direct search URL — bypasses the homepage form to keep inspection focused.
        vin = "5XYK6CDF8TG390982"
        url = f"https://kia.oempartsonline.com/search?search_str={vin}"
        print(f"Navigating to {url}\n")
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=30_000)

        # Strip popups.
        await page.evaluate(
            """() => document.querySelectorAll('#cm-popup-overlay, #cm-popup-iframe').forEach(el => el.remove())"""
        )

        print(f"Current URL after VIN search: {page.url}\n")
        print(f"Page title: {await page.title()}\n")

        # Pull every link that mentions any of our category keywords.
        keywords = [
            "electrical",
            "keyless",
            "anti-theft",
            "anti theft",
            "transmitter",
            "smart key",
            "fob",
            "remote",
        ]
        links = await page.evaluate(
            """
            (kw) => Array.from(document.querySelectorAll('a')).map(a => ({
              text: (a.innerText || '').trim(),
              href: a.href,
              visible: !!(a.offsetWidth || a.offsetHeight || a.getClientRects().length),
            })).filter(l => l.text && kw.some(k => l.text.toLowerCase().includes(k)))
            """,
            keywords,
        )

        print(f"Found {len(links)} relevant links:\n")
        for i, link in enumerate(links[:40]):
            marker = "V" if link["visible"] else "h"
            print(f"[{i:2}] [{marker}] {link['text'][:60]!r:<62} -> {link['href']}")

        # Also dump major nav structures.
        navs = await page.evaluate(
            """
            () => {
              const dump = (root, depth=0) => {
                const items = [];
                root.querySelectorAll(':scope > li, :scope > div, :scope > a').forEach(el => {
                  const text = (el.innerText || '').split('\\n')[0].trim();
                  if (text && text.length < 80) items.push('  '.repeat(depth) + text);
                });
                return items;
              };
              const out = {};
              ['nav', '.catalog', '.categories', '.section-tree', '#category-tree', '.tree-view', 'aside'].forEach(sel => {
                const el = document.querySelector(sel);
                if (el) out[sel] = dump(el);
              });
              return out;
            }
            """
        )
        print("\nMajor nav structures:\n")
        for sel, items in navs.items():
            print(f"  {sel}:")
            for item in items[:20]:
                print(f"    - {item}")
            print()

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
