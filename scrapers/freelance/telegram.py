"""Scraper for freelance website development orders from public Telegram channels."""
import asyncio
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from typing import List, Optional, Callable

from core.models import FreelanceOrder
from .filters import is_valid_web_task, clean_bot_title_and_price

# Active, high-volume channels for live freelance orders and tasks
DEFAULT_TG_CHANNELS = [
    "freelance_feed",     # Live stream of fresh tasks from exchanges with prices
    "forfreelancers",     # Real freelance tasks
    "freelancetaverna",   # Tech & web freelance tasks
    "workinprog",         # Freelance web tasks
]


class TelegramScraper:
    """Scrapes public freelance and website development job posts from Telegram channels.

    Guarantees fresh posts (default <= 5 days) and strict thematic filtering for web development.
    """

    def __init__(
        self,
        channels: Optional[List[str]] = None,
        max_age_days: int = 5,
        on_order_found: Optional[Callable[[FreelanceOrder], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        self.channels = channels or DEFAULT_TG_CHANNELS
        self.max_age_days = max_age_days
        self.on_order_found = on_order_found
        self.on_progress = on_progress

    async def search(self, query: str = "сайт", limit: int = 30) -> List[FreelanceOrder]:
        orders: List[FreelanceOrder] = []

        if self.on_progress:
            self.on_progress("Telegram: поиск свежих заказов в каналах (@freelance_feed и др.)...")

        def _fetch_channel_html(ch: str) -> str:
            url = f"https://t.me/s/{ch}"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                }
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.read().decode("utf-8", errors="replace")

        loop = asyncio.get_event_loop()
        seen_urls = set()
        now_utc = datetime.now(timezone.utc)

        for ch in self.channels:
            if len(orders) >= limit:
                break
            try:
                html = await loop.run_in_executor(None, _fetch_channel_html, ch)
                # Split by message block to parse independently
                raw_blocks = html.split('<div class="tgme_widget_message_wrap')
                posts = []
                for block in raw_blocks[1:]:
                    text_match = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.DOTALL)
                    link_match = re.search(r'<a class="tgme_widget_message_date" href="([^"]+)"', block)
                    date_match = re.search(r'<time datetime="([^"]+)"', block)
                    if text_match and link_match:
                        t_html = text_match.group(1)
                        l_url = link_match.group(1)
                        d_str = date_match.group(1) if date_match else ""
                        posts.append((t_html, l_url, d_str))

                # Iterate newest posts first
                for text_html, link, date_str in reversed(posts):
                    if len(orders) >= limit:
                        break
                    if not link or link in seen_urls:
                        continue

                    # 1. Date check: discard posts older than max_age_days
                    try:
                        post_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        age_days = (now_utc - post_dt).total_seconds() / 86400
                        if age_days > self.max_age_days:
                            continue
                        date_display = post_dt.strftime("%d.%m %H:%M")
                    except Exception:
                        date_display = date_str[:10] if date_str else "Свежий"

                    # 2. Clean message text
                    text = re.sub(r'<br\s*/?>', '\n', text_html)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = unescape(text).strip()
                    if len(text) < 15:
                        continue

                    title, price, desc = clean_bot_title_and_price(text)

                    # 3. Strict thematic web validation (no SMM, 1C, video editing, logos, etc.)
                    if not is_valid_web_task(title=title, desc=desc, query=query):
                        continue

                    seen_urls.add(link)
                    order = FreelanceOrder(
                        platform=f"Telegram (@{ch})",
                        title=title,
                        price=price,
                        description=desc if desc else title,
                        url=link,
                        proposals_count="",
                        date_posted=f"{date_display} (TG)",
                        category="Telegram заказы",
                    )
                    orders.append(order)
                    if self.on_order_found:
                        self.on_order_found(order)

            except Exception as e:
                # Avoid crashing on console encoding
                safe_err = str(e).encode('ascii', 'replace').decode('ascii')
                print(f"[TelegramScraper] Error for @{ch}: {safe_err}")

        if self.on_progress:
            self.on_progress(f"Telegram: найдено {len(orders)} свежих заказов по сайтам.")

        return orders
