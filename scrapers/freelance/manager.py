"""Freelance aggregator manager that orchestrates multi-exchange search."""
import asyncio
import logging
from typing import List, Optional, Callable, Dict, Any

from core.models import FreelanceOrder

logger = logging.getLogger(__name__)
from .filters import is_valid_web_task
from .onliner import OnlinerScraper
from .telegram import TelegramScraper
from .kufar import KufarScraper
from .kwork import KworkScraper
from .fl import FlScraper
from .freelancehunt import FreelancehuntScraper
from .weblancer import WeblancerScraper


class FreelanceAggregator:
    """Aggregates and filters website development orders from multiple freelance platforms.

    Enforces strict web development relevance across all sources.
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

    async def search(
        self,
        query: str = "разработка сайта",
        platforms: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[FreelanceOrder]:
        if not platforms:
            platforms = ["onliner", "telegram", "kwork", "fl", "freelancehunt"]

        active_platforms = [p.lower() for p in platforms]
        all_orders: List[FreelanceOrder] = []
        seen_urls = set()

        def _handle_found(order: FreelanceOrder):
            if order.url not in seen_urls:
                # Shield: only accept orders that are strictly website/web development related
                if not is_valid_web_task(order.title, order.description, query=query):
                    return
                seen_urls.add(order.url)
                all_orders.append(order)
                if self.on_order_found:
                    self.on_order_found(order)

        per_platform_limit = max(limit // len(active_platforms) + 5, 12)

        tasks = []

        # 1. Onliner Услуги (Belarus Top #1)
        if "onliner" in active_platforms or "онлайнер" in active_platforms:
            onliner_scraper = OnlinerScraper(
                on_order_found=_handle_found,
                on_progress=self.on_progress
            )
            tasks.append(onliner_scraper.search(query=query, limit=per_platform_limit))

        # 2. Telegram channels (@freelance_feed etc.)
        if "telegram" in active_platforms or "tg" in active_platforms or "телеграм" in active_platforms:
            tg_scraper = TelegramScraper(
                on_order_found=_handle_found,
                on_progress=self.on_progress
            )
            tasks.append(tg_scraper.search(query=query, limit=per_platform_limit))

        # 3. Kufar (Belarus - with strict demand filter)
        if "kufar" in active_platforms or "куфар" in active_platforms:
            kufar_scraper = KufarScraper(
                headless=self.headless,
                on_order_found=_handle_found,
                on_progress=self.on_progress
            )
            tasks.append(kufar_scraper.search(query=query, limit=per_platform_limit))

        # 4. Kwork (Friendly for BY)
        if "kwork" in active_platforms or "кворк" in active_platforms:
            kw_scraper = KworkScraper(
                headless=self.headless,
                on_order_found=_handle_found,
                on_progress=self.on_progress
            )
            tasks.append(kw_scraper.search(query=query, limit=per_platform_limit))

        # 5. FL.ru (Friendly for BY)
        if "fl" in active_platforms or "fl.ru" in active_platforms:
            fl_scraper = FlScraper(
                headless=self.headless,
                on_order_found=_handle_found,
                on_progress=self.on_progress
            )
            tasks.append(fl_scraper.search(query=query, limit=per_platform_limit))

        # 6. Freelancehunt
        if "freelancehunt" in active_platforms or "fh" in active_platforms:
            fh_scraper = FreelancehuntScraper(
                on_order_found=_handle_found,
                on_progress=self.on_progress
            )
            tasks.append(fh_scraper.search(query=query, limit=per_platform_limit))

        # 7. Weblancer
        if "weblancer" in active_platforms:
            wl_scraper = WeblancerScraper(
                headless=self.headless,
                on_order_found=_handle_found,
                on_progress=self.on_progress
            )
            tasks.append(wl_scraper.search(query=query, limit=per_platform_limit))

        if self.on_progress:
            self.on_progress(f"Запуск сбора с бирж ({', '.join(active_platforms)})...")

        # Run scrapers concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, Exception):
                logger.warning(f"[FreelanceAggregator] Platform error: {res}")
            elif isinstance(res, list):
                for order in res:
                    if order.url not in seen_urls:
                        if not is_valid_web_task(order.title, order.description, query=query):
                            continue
                        seen_urls.add(order.url)
                        all_orders.append(order)

        # Sort: explicit price first, then договорная
        def _price_sort_key(o: FreelanceOrder):
            p = (o.price or "").lower()
            if "договор" in p or "собеседован" in p or not p:
                return 1
            return 0

        all_orders.sort(key=_price_sort_key)
        final_list = all_orders[:limit]

        if self.on_progress:
            self.on_progress(f"Готово! Собрано {len(final_list)} целевых заказов по сайтам.")

        return final_list
