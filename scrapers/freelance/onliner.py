"""Scraper for Belarusian freelance and tasks on Onliner Услуги (s.onliner.by)."""
import asyncio
import json
import re
import urllib.parse
import urllib.request
from typing import List, Optional, Callable

from core.models import FreelanceOrder
from .filters import is_valid_web_task


class OnlinerScraper:
    """Scrapes web development and IT tasks from Onliner Услуги (s.onliner.by).

    Queries developer & webdesign sections specifically and strictly filters for website creation/maintenance.
    """

    def __init__(
        self,
        on_order_found: Optional[Callable[[FreelanceOrder], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        self.on_order_found = on_order_found
        self.on_progress = on_progress

    async def search(self, query: str = "сайт", limit: int = 30) -> List[FreelanceOrder]:
        orders: List[FreelanceOrder] = []
        if self.on_progress:
            self.on_progress("Onliner: получение задач по веб-разработке из Беларуси...")

        def _fetch_tasks():
            # Query developer and webdesign sections directly for actual web client orders
            url = "https://s.onliner.by/api/tasks?sections[]=developer&sections[]=webdesign&limit=50"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "ru-RU,ru;q=0.9",
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))

        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, _fetch_tasks)
            tasks = data.get("tasks", [])

            seen_urls = set()
            for t in tasks:
                if len(orders) >= limit:
                    break

                raw_url = t.get("html_url", "")
                if not raw_url or raw_url in seen_urls:
                    continue

                title = t.get("title", "").strip()
                desc = t.get("description", "").strip()

                # Strict thematic validation: website/landing/CMS tasks only
                if not is_valid_web_task(title=title, desc=desc, query=query):
                    continue

                seen_urls.add(raw_url)

                # Format price in BYN
                price_dict = t.get("price")
                if price_dict and isinstance(price_dict, dict) and price_dict.get("amount"):
                    amount = price_dict.get("amount")
                    curr = price_dict.get("currency", "BYN")
                    price = f"{amount} {curr}"
                else:
                    price = "По договоренности"

                proposals = f"{t.get('proposals_qty', 0)} откл."
                loc = t.get("location", {})
                city = loc.get("city", "Беларусь") if loc else "Беларусь"
                date_str = t.get("created_at", "")[:10] if t.get("created_at") else "Свежий"

                order = FreelanceOrder(
                    platform="Onliner",
                    title=title,
                    price=price,
                    description=desc[:250] + ("..." if len(desc) > 250 else ""),
                    url=raw_url,
                    proposals_count=proposals,
                    date_posted=f"{date_str} ({city})",
                    category="Разработка сайтов (РБ)",
                )
                orders.append(order)
                if self.on_order_found:
                    self.on_order_found(order)

            if self.on_progress:
                self.on_progress(f"Onliner: найдено {len(orders)} актуальных заказов по сайтам.")

        except Exception as e:
            safe_err = str(e).encode('ascii', 'replace').decode('ascii')
            print(f"[OnlinerScraper] Error: {safe_err}")
            if self.on_progress:
                self.on_progress(f"Onliner: ошибка ({safe_err})")

        return orders
