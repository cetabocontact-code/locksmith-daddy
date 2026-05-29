"""Dump the structure of a single category page so we can pick correct
selectors for part cards, part numbers, and part names."""

from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

CATEGORY = (
    "https://kia.oempartsonline.com/v-2026-kia-sportage--x-line--2-5l-l4-gas/"
    "electrical--keyless-entry-components"
)


async def main() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/127.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()
        await page.goto(CATEGORY, wait_until="domcontentloaded")
        print(f"URL: {page.url}")
        print(f"Title: {await page.title()}\n")

        # Find anything that looks like a part listing — element with text
        # that includes a Kia-style part number pattern (e.g. 95440-P1AB0).
        results = await page.evaluate(
            """
            () => {
              const partNumRx = /\\b9\\d{4}-?[A-Z0-9]{4,6}\\b/;
              const out = [];
              document.querySelectorAll('*').forEach(el => {
                if (el.children.length > 0) return;  // leaves only
                const txt = (el.textContent || '').trim();
                if (txt.length > 100) return;
                if (!partNumRx.test(txt)) return;
                // Walk up to a meaningful container
                let container = el;
                for (let i = 0; i < 6; i++) {
                  if (!container.parentElement) break;
                  if (container.parentElement.matches('article, li, .product, .part, [class*=\"product\"], [class*=\"part\"]')) {
                    container = container.parentElement;
                    break;
                  }
                  container = container.parentElement;
                }
                out.push({
                  pn_text: txt,
                  pn_tag: el.tagName,
                  pn_class: el.className || '',
                  container_tag: container.tagName,
                  container_class: container.className || '',
                  container_id: container.id || '',
                  container_text_first_200: (container.textContent || '').slice(0, 200).replace(/\\s+/g, ' '),
                });
              });
              return out.slice(0, 30);
            }
            """
        )
        # Now grab the outerHTML of the row containing the first product-partnum.
        sample = await page.evaluate(
            """
            () => {
              const pn = document.querySelector('.product-partnum');
              if (!pn) return null;
              // Walk up until we hit something that contains both the PN and a name-like sibling.
              let node = pn;
              for (let i = 0; i < 8; i++) {
                node = node.parentElement;
                if (!node) break;
                const text = (node.textContent || '').toLowerCase();
                if (text.includes('smart key') || text.includes('transmitter') || text.includes('fob') || text.includes('keyless')) {
                  return {
                    depth: i + 1,
                    tag: node.tagName,
                    class: node.className,
                    id: node.id,
                    outer_html_first_2000: node.outerHTML.slice(0, 2000),
                  };
                }
              }
              return { depth: -1, note: 'no key-named ancestor found' };
            }
            """
        )
        print("Sample product-card outer HTML (walked up from .product-partnum):\n")
        print(sample)

        await ctx.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
