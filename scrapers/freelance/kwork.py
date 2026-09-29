"""Scraper for Kwork projects exchange."""
import asyncio
import urllib.parse
from typing import List, Optional, Callable
from playwright.async_api import async_playwright

from core.models import FreelanceOrder


class KworkScraper:
    """Scrapes public project requests on Kwork.ru."""

    def __init__(
        self,
        headless: bool = True,
        on_order_found: Optional[Callable[[FreelanceOrder], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        self.headless = headless
        self.on_order_found = on_order_found
        self.on_progress = on_progress

    async def search(self, query: str = "создание сайта", limit: int = 30) -> List[FreelanceOrder]:
        orders: List[FreelanceOrder] = []
        clean_q = query.strip() if query.strip() else "создание сайта"

        if self.on_progress:
            self.on_progress(f"Kwork: открываем проекты по запросу «{clean_q}»...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="ru-RU",
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()

            url = f"https://kwork.ru/projects?keyword={urllib.parse.quote(clean_q)}"

            try:
                await page.goto(url, timeout=30000, wait_until="commit")
                # Wait for cards or body to load
                try:
                    await page.wait_for_selector(".want-card, div[class*='want-card']", timeout=12000)
                except Exception:
                    await asyncio.sleep(3)

                # Scroll down a bit to trigger lazy loaded items if needed
                await page.evaluate("window.scrollBy(0, 600)")
                await asyncio.sleep(1)

                raw_orders = await page.evaluate('''() => {
                    const cards = Array.from(document.querySelectorAll('.want-card, div[class*="want-card"]'));
                    const results = [];
                    for (const c of cards) {
                        const titleEl = c.querySelector('div.wants-card__header-title a') || c.querySelector('a[href*="/projects/"]');
                        if (!titleEl) continue;
                        const title = titleEl.innerText.trim();
                        let href = titleEl.getAttribute('href') || '';
                        if (href && !href.startsWith('http')) {
                            href = 'https://kwork.ru' + (href.startsWith('/') ? '' : '/') + href;
                        }

                        const priceEl = c.querySelector('.wants-card__header-price') || c.querySelector('[class*="price"]');
                        const price = priceEl ? priceEl.innerText.trim().replace(/\\s+/g, ' ') : 'По договоренности';

                        const descEl = c.querySelector('.wants-card__description-text') || c.querySelector('[class*="description"]');
                        const desc = descEl ? descEl.innerText.trim() : '';

                        const metaEl = c.querySelector('.wants-card__informers, div[class*="informers"]');
                        let meta = metaEl ? metaEl.innerText.trim().replace(/\\s+/g, ' ') : '';

                        results.push({
                            title: title,
                            url: href,
                            price: price,
                            description: desc,
                            meta: meta
                        });
                    }
                    return results;
                }''')

                seen_urls = set()
                for item in raw_orders:
                    if len(orders) >= limit:
                        break
                    u = item.get("url", "")
                    t = item.get("title", "")
                    if not u or not t or u in seen_urls:
                        continue
                    seen_urls.add(u)

                    meta_str = item.get("meta", "")
                    proposals = ""
                    date_str = ""
                    if "Предложений:" in meta_str:
                        parts = meta_str.split("Предложений:")
                        if len(parts) > 1:
                            proposals = parts[1].split()[0] + " предл."
                    if "Осталось" in meta_str:
                        date_str = "Осталось " + meta_str.split("Осталось")[-1].strip().split()[0]

                    order = FreelanceOrder(
                        platform="Kwork",
                        title=t,
                        price=item.get("price", "По договоренности"),
                        description=item.get("description", ""),
                        url=u,
                        proposals_count=proposals,
                        date_posted=date_str or "Актуально",
                        category="Разработка сайтов",
                    )
                    orders.append(order)
                    if self.on_order_found:
                        self.on_order_found(order)

                if self.on_progress:
                    self.on_progress(f"Kwork: найдено {len(orders)} проектов.")

            except Exception as e:
                print(f"[KworkScraper] Error: {e}")
                if self.on_progress:
                    self.on_progress(f"Kwork: ошибка сбора ({e})")
            finally:
                await browser.close()

        return orders
