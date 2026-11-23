"""Render JavaScript lunch pages in a real browser and click the weekday / lunch tabs,
so the AI reader sees menus that a plain fetch cannot.
Usage: render_tabs.py <web_pages.json> <comma-separated week dates> [max_sites]
Updates web_pages.json in place: the rendered text is added as the first page of each site it helped."""
import asyncio, datetime, json, re, sys

WD_FI = ["maanantai", "tiistai", "keskiviikko", "torstai", "perjantai"]
WD_SHORT = ["ma", "ti", "ke", "to", "pe"]
WD_EN = ["monday", "tuesday", "wednesday", "thursday", "friday"]
LUNCH = re.compile(r"(?i)\blounas|\blunch|ruokalista|päivän|viikon")
DISH = re.compile(r"(?i)kastike|keitto|pihvi|broiler|kana|lohi|kala|riisi|peruna|pasta|salaatti|curry|tofu|wok|nuudeli|soup|chicken|salmon|beef|\(?\b(L|G|M|VL|VEG)\b")


def needs_render(v):
    """Lunch is mentioned but the fetched text has few dishes (menu probably loads with JavaScript or sits in tabs)."""
    text = "\n".join(p["text"] for p in v.get("pages", []))
    if not text or not LUNCH.search(text):
        return False
    dishes = len(DISH.findall(text))
    days = sum(1 for d in WD_FI + WD_EN if d in text.lower())
    return dishes < 6 or (days >= 2 and dishes < 12)


async def render(browser, url, weekday):
    page = await browser.new_page(locale="fi-FI", viewport={"width": 1280, "height": 1600})
    texts = []
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        # cookie banners: accept-all buttons hide the page on many sites
        for label in ("Hyväksy", "Salli kaikki", "Accept", "OK"):
            b = page.get_by_role("button", name=re.compile(label, re.I))
            if await b.count():
                try:
                    await b.first.click(timeout=1500)
                    break
                except Exception:
                    pass
        texts.append(await page.inner_text("body"))
        targets = [WD_FI[weekday], WD_EN[weekday], WD_SHORT[weekday] + " ", "lounas", "lunch"]
        clicked = 0
        for t in targets:
            loc = page.locator("button, [role=tab], a[href^='#'], li, span, div").filter(has_text=re.compile(r"^\s*" + re.escape(t.strip()) + r"\b", re.I))
            n = min(await loc.count(), 3)
            for i in range(n):
                el = loc.nth(i)
                try:
                    if not await el.is_visible():
                        continue
                    txt = (await el.inner_text())[:40]
                    if len(txt) > 30:
                        continue
                    await el.click(timeout=2000)
                    await page.wait_for_timeout(700)
                    texts.append(await page.inner_text("body"))
                    clicked += 1
                    break
                except Exception:
                    continue
            if clicked >= 2:
                break
    except Exception as e:
        texts.append("")
    finally:
        await page.close()
    # keep the most informative rendering
    best = max(texts, key=lambda x: len(DISH.findall(x or "")), default="")
    return best


async def main_async(path, days, max_sites):
    from playwright.async_api import async_playwright
    pages = json.load(open(path))
    week = days.split(",")
    weekday = min(datetime.date.today().weekday(), 4)
    todo = [(k, v) for k, v in pages.items() if needs_render(v)][:max_sites]
    print("render candidates", len(todo), file=sys.stderr)
    sem = asyncio.Semaphore(4)
    helped = 0
    async with async_playwright() as p:
        import os
        exe = os.environ.get("LOUNAS_CHROME")
        browser = await (p.chromium.launch(executable_path=exe) if exe else p.chromium.launch())

        async def one(k, v):
            nonlocal helped
            async with sem:
                url = v["pages"][0]["url"]
                txt = await render(browser, url, weekday)
                before = len(DISH.findall("\n".join(x["text"] for x in v["pages"])))
                if len(DISH.findall(txt)) > before + 2:
                    v["pages"] = [{"url": url, "text": txt[:9000], "rendered": True}] + v["pages"][:1]
                    helped += 1
        await asyncio.gather(*(one(k, v) for k, v in todo))
        await browser.close()
    json.dump(pages, open(path, "w"), ensure_ascii=False)
    print("render helped", helped, "of", len(todo), file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main_async(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 80))
