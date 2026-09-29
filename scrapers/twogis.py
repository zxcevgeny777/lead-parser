"""2GIS scraper using Playwright with network API interception, DOM fallback, and Captcha handling."""
import asyncio
import json
import logging
import socket
import urllib.parse
from typing import List, Dict, Any, Optional, Callable

from core.models import Lead, classify_website
from core.memory import memory_db
from .base import BaseScraper

logger = logging.getLogger(__name__)

# City name to 2GIS slug mapping (including Belarus, Kazakhstan, UAE)
CITY_SLUGS = {
    # Belarus (2gis.by)
    "минск": "minsk",
    "брест": "brest",
    "гродно": "grodno",
    "гомель": "gomel",
    "витебск": "vitebsk",
    "могилев": "mogilev",
    # Russia
    "москва": "moscow",
    "санкт-петербург": "spb",
    "спб": "spb",
    "питер": "spb",
    "новосибирск": "novosibirsk",
    "екатеринбург": "ekaterinburg",
    "казань": "kazan",
    "нижний новгород": "n_novgorod",
    "челябинск": "chelyabinsk",
    "самара": "samara",
    "уфа": "ufa",
    "ростов-на-дону": "rostov",
    "красноярск": "krasnoyarsk",
    "воронеж": "voronezh",
    "пермь": "perm",
    "волгоград": "volgograd",
    "краснодар": "krasnodar",
    "саратов": "saratov",
    "тюмень": "tumen",
    "сочи": "sochi",
    # Kazakhstan & UAE
    "алматы": "almaty",
    "астана": "astana",
    "дубай": "dubai",
}


class TwoGisScraper(BaseScraper):
    """Scraper for 2GIS organizations."""

    def __init__(
        self,
        headless: bool = True,
        proxy: Optional[Dict[str, str]] = None,
        on_lead_found: Optional[Callable[[Lead], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(headless=headless, proxy=proxy)
        self.on_lead_found = on_lead_found
        self.on_progress = on_progress
        self.leads: List[Lead] = []
        self._seen_ids = set()
        self.skip_checked: bool = True
        self.skipped_checked_count: int = 0
        self._cached_memory: Dict[str, Set[str]] = {"urls": set(), "phones": set(), "name_city": set()}

    def _parse_api_item(self, item: Dict[str, Any], default_city: str) -> Optional[Lead]:
        """Parses a raw 2GIS catalog item from API into a Lead object."""
        try:
            item_id = str(item.get("id", ""))
            if item_id in self._seen_ids:
                return None
            self._seen_ids.add(item_id)

            name = item.get("name", "").strip()
            if not name:
                return None

            map_url = f"https://2gis.ru/firm/{item_id}" if item_id else None

            city_name = item.get("adm_div", [{}])[0].get("name", default_city)

            # Skip previously checked places from memory
            if self.skip_checked:
                name_key = f"{name.lower()}_{(city_name or default_city).lower()}"
                if (
                    item_id in self._cached_memory["urls"]
                    or (map_url and map_url in self._cached_memory["urls"])
                    or name_key in self._cached_memory["name_city"]
                ):
                    self.skipped_checked_count += 1
                    return None

            rubrics = item.get("rubrics", [])
            category = rubrics[0].get("name", "") if rubrics else ""

            address_name = item.get("address_name", "")
            city_name = item.get("adm_div", [{}])[0].get("name", default_city)
            full_address = f"{city_name}, {address_name}".strip(", ") if city_name else address_name

            reviews_info = item.get("reviews", {})
            rating = None
            try:
                if reviews_info.get("general_rating"):
                    rating = float(reviews_info.get("general_rating"))
            except (ValueError, TypeError):
                pass

            reviews_count = None
            try:
                if reviews_info.get("general_review_count"):
                    reviews_count = int(reviews_info.get("general_review_count"))
            except (ValueError, TypeError):
                pass

            phones = []
            website = None
            social_links = {}

            contact_groups = item.get("contact_groups", [])
            for group in contact_groups:
                for contact in group.get("contacts", []):
                    c_type = contact.get("type", "").lower()
                    c_text = contact.get("text", "")
                    c_url = contact.get("url", "")
                    c_value = contact.get("value", "")

                    if c_type == "phone":
                        phone_val = c_text or c_value
                        if phone_val and phone_val not in phones:
                            phones.append(phone_val)
                    elif c_type == "website":
                        site_url = c_url or c_text
                        if site_url:
                            website = site_url
                    elif "vk" in c_type:
                        social_links["vk"] = c_url or c_value or c_text
                    elif "telegr" in c_type or c_type == "tg":
                        social_links["telegram"] = c_url or c_value or c_text
                    elif "whats" in c_type or c_type == "wa":
                        social_links["whatsapp"] = c_url or c_value or c_text
                    elif "insta" in c_type:
                        social_links["instagram"] = c_url or c_value or c_text

            schedule_info = item.get("schedule", {})
            working_hours = schedule_info.get("description") if schedule_info else None
            map_url = f"https://2gis.ru/firm/{item_id}" if item_id else None

            status, priority = classify_website(website)

            lead = Lead(
                id=item_id,
                name=name,
                source="2ГИС",
                category=category,
                city=city_name or default_city,
                address=full_address,
                phones=phones,
                website=website,
                website_status=status,
                lead_priority=priority,
                social_links=social_links,
                rating=rating,
                reviews_count=reviews_count,
                working_hours=working_hours,
                map_url=map_url,
            )
            return lead
        except Exception as e:
            logger.debug(f"Error parsing 2GIS API item: {e}")
            return None

    async def _handle_network_response(self, response, city: str, limit: int):
        """Intercepts network responses from 2GIS API."""
        url = response.url
        if ("catalog.api.2gis" in url or "items" in url or "search" in url) and response.status == 200:
            try:
                content_type = response.headers.get("content-type", "")
                if "json" in content_type:
                    data = await response.json()
                    items = []
                    if isinstance(data, dict):
                        result = data.get("result", {})
                        if isinstance(result, dict):
                            items = result.get("items", [])
                        elif isinstance(result, list):
                            items = result

                    for item in items:
                        if len(self.leads) >= limit:
                            break
                        if isinstance(item, dict):
                            lead = self._parse_api_item(item, city)
                            if lead:
                                self.leads.append(lead)
                                if self.on_lead_found:
                                    self.on_lead_found(lead)
            except Exception:
                pass

    async def _parse_dom_cards(self, city: str, limit: int):
        """Extracts visible business cards from DOM."""
        if not self.page:
            return
        try:
            cards = await self.page.query_selector_all('a[href*="/firm/"], div[class*="_1hf7139"]')
            for card in cards:
                if len(self.leads) >= limit:
                    break
                try:
                    card_text = await card.inner_text()
                    lines = [l.strip() for l in card_text.split("\n") if l.strip()]
                    if not lines:
                        continue
                    name = lines[0]
                    card_id = f"dom_{hash(name)}"
                    if card_id in self._seen_ids:
                        continue
                    self._seen_ids.add(card_id)

                    href = await card.get_attribute("href")
                    map_url = f"https://2gis.ru{href}" if href and href.startswith("/") else href

                    lead = Lead(
                        id=card_id,
                        name=name,
                        source="2ГИС",
                        category=lines[1] if len(lines) > 1 else "",
                        city=city,
                        address=f"{city}, {lines[2]}" if len(lines) > 2 else city,
                        phones=[],
                        website=None,
                        map_url=map_url,
                    )
                    self.leads.append(lead)
                    if self.on_lead_found:
                        self.on_lead_found(lead)
                except Exception:
                    pass
        except Exception:
            pass

    async def search(
        self,
        query: str,
        city: str = "",
        limit: int = 50,
        filter_no_website_only: bool = False,
        skip_checked: bool = True,
    ) -> List[Lead]:
        """Searches 2GIS for leads matching query and city."""
        self.leads = []
        self._seen_ids = set()
        self.skip_checked = skip_checked
        self.skipped_checked_count = 0
        self._cached_memory = (
            memory_db.load_cached_lookups()
            if skip_checked
            else {"urls": set(), "phones": set(), "name_city": set()}
        )
        if skip_checked and self._cached_memory["urls"]:
            logger.info(f"[2GIS] Loaded {len(self._cached_memory['urls'])} remembered places from memory.")

        clean_city = city.strip().lower()
        city_slug = CITY_SLUGS.get(clean_city, "")
        encoded_query = urllib.parse.quote(query.strip())
        domain = "2gis.ru"

        if city_slug:
            target_url = f"https://{domain}/{city_slug}/search/{encoded_query}"
        elif clean_city:
            target_url = f"https://{domain}/search/{urllib.parse.quote(f'{clean_city} {query.strip()}')}"
        else:
            target_url = f"https://{domain}/search/{encoded_query}"

        # Fast reachability check to avoid 30s timeout if 2GIS is blocked/unreachable
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect((domain, 443))
            s.close()
        except Exception:
            msg = f"[2GIS] Домен {domain} недоступен с вашего интернет-провайдера. Поиск продолжится через другие источники."
            logger.warning(msg)
            if self.on_progress:
                self.on_progress(msg)
            return []

        await self.start()
        logger.info(f"[2GIS] Navigating to {target_url}")

        self.page.on("response", lambda resp: asyncio.create_task(
            self._handle_network_response(resp, city or "Россия", limit)
        ))

        try:
            await self.page.goto(target_url, wait_until="domcontentloaded", timeout=self.timeout)
            await asyncio.sleep(3.0)

            # Check for captcha redirect
            if "captcha.2gis" in self.page.url:
                if not self.headless:
                    logger.warning("[2GIS] Обнаружена капча. Ожидание ручного прохождения 15 сек...")
                    for _ in range(15):
                        await asyncio.sleep(1.0)
                        if "captcha" not in self.page.url:
                            logger.info("[2GIS] Капча успешно пройдена!")
                            break
                else:
                    logger.warning(
                        "[2GIS] Запрос заблокирован защитой 2GIS от ботов (reCAPTCHA на данном IP). "
                        "Рекомендуется запустить с параметром headless=False или использовать прокси."
                    )
                    return []

            # Scroll loop
            scroll_attempts = 0
            max_scrolls = max(15, limit // 3)
            unchanged = 0
            last_cnt = len(self.leads)

            while len(self.leads) < limit and scroll_attempts < max_scrolls:
                await self.smooth_scroll_container('div[class*="_1g3w02m"], div[class*="sidebar"], div[class*="_awux"]', distance=600)
                await asyncio.sleep(2.0)

                if len(self.leads) == last_cnt:
                    unchanged += 1
                else:
                    unchanged = 0
                    last_cnt = len(self.leads)

                if unchanged >= 4:
                    break
                scroll_attempts += 1

            if len(self.leads) < limit:
                await self._parse_dom_cards(city, limit)

        except Exception as e:
            logger.error(f"[2GIS] Search error: {e}")
        finally:
            await self.close()

        if self.leads:
            memory_db.save_leads(self.leads)

        results = self.leads[:limit]
        if filter_no_website_only:
            results = [l for l in results if not l.website]

        logger.info(
            f"[2GIS] Extracted {len(results)} leads. "
            f"Skipped {self.skipped_checked_count} previously checked places."
        )
        return results
