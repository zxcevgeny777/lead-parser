"""Freelance scrapers package."""
from .onliner import OnlinerScraper
from .telegram import TelegramScraper
from .kufar import KufarScraper
from .kwork import KworkScraper
from .fl import FlScraper
from .freelancehunt import FreelancehuntScraper
from .weblancer import WeblancerScraper
from .manager import FreelanceAggregator
from .watcher import FreelanceWatcher, freelance_watcher

__all__ = [
    "OnlinerScraper",
    "TelegramScraper",
    "KufarScraper",
    "KworkScraper",
    "FlScraper",
    "FreelancehuntScraper",
    "WeblancerScraper",
    "FreelanceAggregator",
    "FreelanceWatcher",
    "freelance_watcher",
]

