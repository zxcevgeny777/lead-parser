"""Scrapers module for Google Maps, Yandex Maps and 2GIS."""
from .base import BaseScraper
from .twogis import TwoGisScraper
from .yandex import YandexScraper
from .google import GoogleMapsScraper

__all__ = ["BaseScraper", "TwoGisScraper", "YandexScraper", "GoogleMapsScraper"]
