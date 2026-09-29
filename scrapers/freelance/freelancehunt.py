"""Scraper for Freelancehunt exchange using fast RSS stream."""
import asyncio
import re
import urllib.request
import xml.etree.ElementTree as ET
from typing import List, Optional, Callable
from html import unescape

from core.models import FreelanceOrder


class FreelancehuntScraper:
    """Scrapes public project requests on Freelancehunt.com via high-speed RSS."""

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
            self.on_progress("Freelancehunt: получение свежей ленты заказов...")

        clean_q = query.strip().lower() if query else ""
        q_tokens = [t for t in re.split(r"[\s,]+", clean_q) if len(t) > 2]

        def _fetch_rss():
            url = "https://freelancehunt.com/projects.rss"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                }
            )
            with urllib.request.urlopen(req, timeout=12) as response:
                return response.read()

        try:
            loop = asyncio.get_event_loop()
            raw_data = await loop.run_in_executor(None, _fetch_rss)
            root = ET.fromstring(raw_data)

            items = root.findall(".//item")
            seen_urls = set()

            for it in items:
                if len(orders) >= limit:
                    break

                raw_title = it.findtext("title") or ""
                raw_link = it.findtext("link") or ""
                pub_date = it.findtext("pubDate") or ""
                raw_desc = it.findtext("description") or ""

                if not raw_link or raw_link in seen_urls:
                    continue

                # Clean URL (strip utm trackers)
                clean_url = raw_link.split("?")[0]
                seen_urls.add(clean_url)

                # Extract budget from title: e.g. "Создание сайта - 25000UAH" or "Верстка лендинга - 10000RUB"
                price = "По договоренности"
                clean_title = raw_title.strip()
                if " - " in clean_title:
                    parts = clean_title.rsplit(" - ", 1)
                    if any(curr in parts[1].upper() for curr in ("UAH", "RUB", "USD", "EUR", "ГРН", "РУБ", "₽")):
                        clean_title = parts[0].strip()
                        raw_price = parts[1].strip()
                        # Format nicely
                        if "UAH" in raw_price:
                            price = raw_price.replace("UAH", "").strip() + " грн"
                        elif "RUB" in raw_price:
                            price = raw_price.replace("RUB", "").strip() + " ₽"
                        else:
                            price = raw_price

                # Clean description HTML tags
                desc_text = re.sub(r"<[^>]+>", " ", raw_desc)
                desc_text = unescape(desc_text).strip()
                desc_text = re.sub(r"\s+", " ", desc_text)

                # Filter by query relevance if specific search term given
                if q_tokens and not any(k in "сайт разработка веб web фриланс" for k in q_tokens):
                    combined = (clean_title + " " + desc_text).lower()
                    if not any(tok in combined for tok in q_tokens):
                        continue

                # Format date
                date_str = pub_date[:16] if pub_date else "Сегодня"

                order = FreelanceOrder(
                    platform="Freelancehunt",
                    title=clean_title,
                    price=price,
                    description=desc_text[:280] + ("..." if len(desc_text) > 280 else ""),
                    url=clean_url,
                    proposals_count="",
                    date_posted=date_str,
                    category="Разработка сайтов",
                )
                orders.append(order)
                if self.on_order_found:
                    self.on_order_found(order)

            if self.on_progress:
                self.on_progress(f"Freelancehunt: получено {len(orders)} проектов.")

        except Exception as e:
            print(f"[FreelancehuntScraper] Error: {e}")
            if self.on_progress:
                self.on_progress(f"Freelancehunt: ошибка ({e})")

        return orders
