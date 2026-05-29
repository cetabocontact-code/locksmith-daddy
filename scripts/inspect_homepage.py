"""One-off: dump all visible input fields on the Kia homepage so we can pick
the right selector for the VIN search box."""

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
        await page.goto("https://kia.oempartsonline.com/", wait_until="domcontentloaded")

        # Dump every input on the page with key attributes + visibility.
        inputs = await page.evaluate(
            """
            () => Array.from(document.querySelectorAll('input')).map(el => ({
              id: el.id,
              name: el.name,
              type: el.type,
              placeholder: el.placeholder,
              title: el.title,
              ariaLabel: el.getAttribute('aria-label'),
              visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
              parentClass: el.parentElement ? el.parentElement.className : '',
            }))
            """
        )

        print(f"Found {len(inputs)} input elements on kia.oempartsonline.com home:\n")
        for i, inp in enumerate(inputs):
            marker = "VISIBLE" if inp["visible"] else "hidden "
            vin_hint = ""
            for field in ("placeholder", "title", "ariaLabel", "name", "id"):
                if "vin" in str(inp.get(field, "")).lower():
                    vin_hint = f"  <-- mentions 'vin' in {field}"
                    break
            print(
                f"[{i:2}] {marker} | name={inp['name']!r} id={inp['id']!r} "
                f"type={inp['type']!r}\n"
                f"     placeholder={inp['placeholder']!r}\n"
                f"     title={inp['title']!r}\n"
                f"     aria-label={inp['ariaLabel']!r}\n"
                f"     parent.class={inp['parentClass']!r}{vin_hint}\n"
            )

        # Also dump form action URLs — useful for understanding submission targets.
        forms = await page.evaluate(
            """
            () => Array.from(document.querySelectorAll('form')).map(f => ({
              action: f.action, method: f.method, id: f.id, className: f.className,
              inputs: Array.from(f.querySelectorAll('input')).map(i => i.name).filter(Boolean),
            }))
            """
        )
        print(f"\nFound {len(forms)} forms:\n")
        for i, form in enumerate(forms):
            print(f"[{i}] {form['method'].upper()} {form['action']}")
            print(f"    id={form['id']!r} class={form['className']!r}")
            print(f"    inputs={form['inputs']}\n")

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
