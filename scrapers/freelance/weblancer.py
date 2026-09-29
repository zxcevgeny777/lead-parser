"""Scraper for Weblancer freelance exchange."""
import asyncio
import urllib.parse
from typing import List, Optional, Callable
from playwright.async_api import async_playwright

from core.models import FreelanceOrder


class WeblancerScraper:
    """Scrapes jobs on Weblancer.net."""

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
        clean_q = query.strip() if query.strip() else "сайт"

        if self.on_progress:
            self.on_progress(f"Weblancer: поиск заказов «{clean_q}»...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="ru-RU",
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()

            url = f"https://www.weblancer.net/jobs/?query={urllib.parse.quote(clean_q)}"

            try:
                await page.goto(url, timeout=30000, wait_until="commit")
                try:
                    await page.wait_for_selector("a[href*='/jobs/'], .row", timeout=12000)
                except Exception:
                    await asyncio.sleep(2)

                raw_orders = await page.evaluate('''() => {
                    const links = Array.from(document.querySelectorAll('a[href*="/jobs/"]'));
                    const results = [];
                    const seen = new Set();
                    for (const a of links) {
                        const href = a.href;
                        const text = a.innerText.trim();
                        if (!href.includes('/jobs/') || href.endsWith('/jobs/') || href.includes('?') || seen.has(href)) continue;
                        if (text.length > 5 && !text.includes('Категории') && !text.includes('Все заказы') && !text.includes('Подписаться')) {
                            seen.add(href);
                            const parent = a.closest('.row, div, tr') || a.parentElement;
                            const priceEl = parent ? parent.querySelector('.amount, [class*="price"]') : null;
                            const descEl = parent ? parent.querySelector('.collapse, .text-muted, p') : null;
                            results.push({
                                title: text,
                                url: href,
                                price: priceEl ? priceEl.innerText.trim() : 'По договоренности',
                                desc: descEl ? descEl.innerText.trim() : ''
                            });
                        }
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

                    order = FreelanceOrder(
                        platform="Weblancer",
                        title=t,
                        price=item.get("price", "По договоренности"),
                        description=item.get("desc", ""),
                        url=u,
                        proposals_count="",
                        date_posted="Свежий",
                        category="Разработка сайтов",
                    )
                    orders.append(order)
                    if self.on_order_found:
                        self.on_order_found(order)

                if self.on_progress:
                    self.on_progress(f"Weblancer: найдено {len(orders)} проектов.")

            except Exception as e:
                print(f"[WeblancerScraper] Error: {e}")
                if self.on_progress:
                    self.on_progress(f"Weblancer: ошибка ({e})")
            finally:
                await browser.close()

        return orders
