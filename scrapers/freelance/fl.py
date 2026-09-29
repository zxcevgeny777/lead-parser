"""Scraper for FL.ru freelance exchange."""
import asyncio
import re
from typing import List, Optional, Callable
from playwright.async_api import async_playwright

from core.models import FreelanceOrder


class FlScraper:
    """Scrapes project postings on FL.ru."""

    def __init__(
        self,
        headless: bool = True,
        on_order_found: Optional[Callable[[FreelanceOrder], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        self.headless = headless
        self.on_order_found = on_order_found
        self.on_progress = on_progress

    async def search(self, query: str = "сайт", limit: int = 30) -> List[FreelanceOrder]:
        orders: List[FreelanceOrder] = []
        if self.on_progress:
            self.on_progress("FL.ru: загрузка проектов...")

        clean_q = query.strip().lower() if query else ""
        # Keywords to match if specific query given
        q_tokens = [t for t in re.split(r"[\s,]+", clean_q) if len(t) > 2]

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="ru-RU",
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()

            # FL.ru projects page (kind=5 is direct freelance projects)
            url = "https://www.fl.ru/projects/?kind=5"

            try:
                await page.goto(url, timeout=30000, wait_until="commit")
                try:
                    await page.wait_for_selector("[id*='project-item'], div[class*='project-item']", timeout=12000)
                except Exception:
                    await asyncio.sleep(2)

                raw_orders = await page.evaluate('''() => {
                    const items = Array.from(document.querySelectorAll('[id*="project-item"], div[class*="project-item"]'));
                    const results = [];
                    for (const item of items) {
                        const titleEl = item.querySelector('h2 a') || item.querySelector('a[href*="/projects/"]');
                        if (!titleEl) continue;
                        const title = titleEl.innerText.trim();
                        let href = titleEl.getAttribute('href') || '';
                        if (href && !href.startsWith('http')) {
                            href = 'https://www.fl.ru' + (href.startsWith('/') ? '' : '/') + href;
                        }

                        const priceEl = item.querySelector('div[class*="cost"], span[class*="cost"], div[class*="price"]');
                        const price = priceEl ? priceEl.innerText.trim().replace(/\\s+/g, ' ') : 'По договоренности';

                        const descEl = item.querySelector('div[class*="description"], p, div.text-gray-600');
                        const desc = descEl ? descEl.innerText.trim() : '';

                        results.push({
                            title: title,
                            url: href,
                            price: price,
                            description: desc
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
                    d = item.get("description", "")
                    if not u or not t or u in seen_urls:
                        continue

                    # Filter by query if query provided and not too generic
                    if q_tokens and not any(k in "сайт разработка веб web фриланс" for k in q_tokens):
                        combined = (t + " " + d).lower()
                        if not any(token in combined for token in q_tokens):
                            continue

                    seen_urls.add(u)
                    order = FreelanceOrder(
                        platform="FL.ru",
                        title=t,
                        price=item.get("price", "По договоренности"),
                        description=d,
                        url=u,
                        proposals_count="",
                        date_posted="Свежий",
                        category="Разработка сайтов",
                    )
                    orders.append(order)
                    if self.on_order_found:
                        self.on_order_found(order)

                if self.on_progress:
                    self.on_progress(f"FL.ru: найдено {len(orders)} проектов.")

            except Exception as e:
                print(f"[FlScraper] Error: {e}")
                if self.on_progress:
                    self.on_progress(f"FL.ru: ошибка ({e})")
            finally:
                await browser.close()

        return orders
