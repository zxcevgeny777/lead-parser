"""Scraper for Belarusian client requests on Kufar.by."""
import asyncio
import urllib.parse
from typing import List, Optional, Callable
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from core.models import FreelanceOrder
from .filters import is_valid_web_task, is_valid_kufar_client_task


class KufarScraper:
    """Scrapes website creation and development client requests on Kufar.by.

    Strictly filters out competing web studios and freelancers offering services.
    """

    def __init__(
        self,
        headless: bool = True,
        on_order_found: Optional[Callable[[FreelanceOrder], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        self.headless = headless
        self.on_order_found = on_order_found
        self.on_progress = on_progress

    async def search(self, query: str = "разработка сайта", limit: int = 30) -> List[FreelanceOrder]:
        orders: List[FreelanceOrder] = []
        user_q = query.strip() if query.strip() else "разработка сайта"

        # If user searched generic "сайт" or "разработка сайта", search for demand tasks
        if any(w in user_q.lower() for w in ["разработка сайта", "создание сайта", "сайт под ключ"]):
            search_query = f"требуется {user_q}"
        else:
            search_query = user_q

        if self.on_progress:
            self.on_progress(f"Kufar: поиск клиентских запросов на kufar.by «{search_query}»...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="ru-BY",
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()
            stealth = Stealth()
            await stealth.apply_stealth_async(page)

            url = f"https://www.kufar.by/l?query={urllib.parse.quote(search_query)}"

            try:
                await page.goto(url, timeout=25000, wait_until="commit")
                await asyncio.sleep(2.5)

                raw_items = await page.evaluate('''() => {
                    const links = Array.from(document.querySelectorAll('a[href*="/item/"]'));
                    const results = [];
                    const seen = new Set();
                    for (const a of links) {
                        const href = a.href;
                        if (seen.has(href)) continue;
                        seen.add(href);

                        const text = a.innerText.trim();
                        if (text.length < 5) continue;

                        const parent = a.closest('section, div, article') || a.parentElement;
                        const pEl = parent ? parent.querySelector('[class*="price"], span[class*="price"]') : null;
                        const price = pEl ? pEl.innerText.trim().replace(/\\s+/g, ' ') : 'По договоренности';

                        results.push({
                            title: text.split('\\n')[0].trim(),
                            desc: text.replace(/\\n+/g, ' ').trim(),
                            price: price,
                            url: href
                        });
                    }
                    return results;
                }''')

                seen_urls = set()
                for item in raw_items:
                    if len(orders) >= limit:
                        break
                    u = item.get("url", "")
                    t = item.get("title", "")
                    desc = item.get("desc", "")
                    if not u or not t or u in seen_urls:
                        continue

                    # 1. Filter out competing studios / freelancers offering services
                    if not is_valid_kufar_client_task(t, desc):
                        continue

                    # 2. Strict web relevance
                    if not is_valid_web_task(t, desc, query=query):
                        continue

                    seen_urls.add(u)

                    order = FreelanceOrder(
                        platform="Kufar (Заказ)",
                        title=t[:90],
                        price=item.get("price", "По договоренности"),
                        description=desc[:240],
                        url=u,
                        proposals_count="",
                        date_posted="Актуально (РБ)",
                        category="Разработка сайтов (РБ)",
                    )
                    orders.append(order)
                    if self.on_order_found:
                        self.on_order_found(order)

                if self.on_progress:
                    self.on_progress(f"Kufar: найдено {len(orders)} реальных запросов от заказчиков.")

            except Exception as e:
                safe_err = str(e).encode('ascii', 'replace').decode('ascii')
                print(f"[KufarScraper] Error: {safe_err}")
                if self.on_progress:
                    self.on_progress(f"Kufar: ошибка ({safe_err})")
            finally:
                await browser.close()

        return orders
