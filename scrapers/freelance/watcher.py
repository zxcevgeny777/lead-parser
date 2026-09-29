"""Background watcher daemon for monitoring Onliner and freelance exchanges in real-time.

Polls exchanges periodically and sends immediate alerts to Telegram when new web orders are posted.
"""
import asyncio
import logging
import threading
import time
from typing import Set, List, Optional, Callable

from core.models import FreelanceOrder
from core.notifier import load_settings, send_telegram_alert
from .manager import FreelanceAggregator

logger = logging.getLogger(__name__)


class FreelanceWatcher:
    """Background monitor that periodically scrapes freelance exchanges and alerts via Telegram."""

    def __init__(self, interval_seconds: int = 180):
        self.interval = interval_seconds
        self.is_running = False
        self._seen_urls: Set[str] = set()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.last_check_time: Optional[float] = None
        self.orders_found_count: int = 0
        self.on_new_order: Optional[Callable[[FreelanceOrder], None]] = None

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("[Watcher] Background freelance watcher started.")

    def stop(self):
        self.is_running = False
        logger.info("[Watcher] Background freelance watcher stopped.")

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._worker())
        self._loop.close()

    async def _worker(self):
        # Initial run: collect baseline so we don't spam 50 old orders at startup
        aggregator = FreelanceAggregator(headless=True)
        try:
            cfg = load_settings()
            platforms = []
            if cfg.get("notify_onliner", True):
                platforms.append("onliner")
            if cfg.get("notify_kwork", True):
                platforms.append("kwork")
            if cfg.get("notify_fl", True):
                platforms.append("fl")
            if not platforms:
                platforms = ["onliner", "kwork"]

            initial_orders = await aggregator.search(query="сайт", platforms=platforms, limit=40)
            for o in initial_orders:
                self._seen_urls.add(o.url)
            self.last_check_time = time.time()
            logger.info(f"[Watcher] Baseline collected: {len(self._seen_urls)} existing orders cached.")
        except Exception as e:
            logger.debug(f"[Watcher] Error during baseline collection: {e}")

        while self.is_running:
            cfg = load_settings()
            if not cfg.get("auto_monitor_enabled", False):
                await asyncio.sleep(10)
                continue

            interval_min = int(cfg.get("monitor_interval_minutes", 3))
            sleep_sec = max(interval_min * 60, 60)

            await asyncio.sleep(sleep_sec)
            if not self.is_running:
                break

            try:
                platforms = []
                if cfg.get("notify_onliner", True):
                    platforms.append("onliner")
                if cfg.get("notify_kwork", True):
                    platforms.append("kwork")
                if cfg.get("notify_fl", True):
                    platforms.append("fl")
                if not platforms:
                    platforms = ["onliner"]

                orders = await aggregator.search(query="сайт", platforms=platforms, limit=30)
                self.last_check_time = time.time()

                for o in orders:
                    if o.url not in self._seen_urls:
                        self._seen_urls.add(o.url)
                        self.orders_found_count += 1

                        if self.on_new_order:
                            self.on_new_order(o)

                        # Send Telegram notification if credentials provided
                        msg = (
                            f"🔔 <b>Новый заказ на разработку сайта!</b>\n\n"
                            f"📌 <b>Платформа:</b> {o.platform}\n"
                            f"💼 <b>Заголовок:</b> {o.title}\n"
                            f"💰 <b>Бюджет:</b> <code>{o.price}</code>\n"
                            f"📝 <b>Описание:</b> {o.description[:200]}...\n\n"
                            f"🔗 <a href='{o.url}'>Открыть заказ и откликнуться</a>"
                        )
                        send_telegram_alert(msg)

            except Exception as e:
                logger.debug(f"[Watcher] Check error: {e}")


# Singleton watcher instance
freelance_watcher = FreelanceWatcher()
