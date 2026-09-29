"""Yandex Maps scraper using Playwright with human-like scrolling, parallel card enrichment, and smart quota filtering."""
import asyncio
import logging
import re
import urllib.parse
from typing import List, Dict, Any, Optional, Callable

from core.models import Lead, LeadPriority, classify_website, parse_and_format_phone
from core.memory import memory_db
from .base import BaseScraper

logger = logging.getLogger(__name__)

# Universal phone patterns matching Belarus (+375), Russia/Kazakhstan (+7/8), and international
PHONE_PATTERNS = [
    # Belarus (+375 or 80)
    re.compile(r"(?:\+?375|8[\s-]?0)[-\s(]*(?:29|33|44|25|17|16|21|22|23|15)[-\s)]*\d{3}[-\s]*\d{2}[-\s]*\d{2}"),
    # Russia & Kazakhstan (+7 or 8)
    re.compile(r"(?:\+?7|8)[-\s(]*\d{3}[-\s)]*\d{3}[-\s]*\d{2}[-\s]*\d{2}"),
    # General International
    re.compile(r"\+\d{1,3}[-\s(]*\d{2,4}[-\s)]*[\d\s-]{6,10}"),
]

IGNORABLE_DOMAINS = [
    "yandex", "ya.ru", "ya.by", "google", "apple.com", "2gis",
    "appgallery", "googleplay", "play.google", "youtube.com", "maps/org", "clck/"
]


class YandexScraper(BaseScraper):
    """Scraper for Yandex Maps organizations."""

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
        self._seen_urls = set()
        self.skipped_checked_count: int = 0

    async def _scroll_results(self) -> bool:
        """Scrolls the actual scroll container in Yandex Maps sidebar."""
        if not self.page:
            return False
        try:
            return await self.page.evaluate("""() => {
                const container = document.querySelector('div.scroll__container') ||
                                  document.querySelector('ul.search-list-view__list') ||
                                  document.querySelector('div[class*="search-list-view"]');
                if (container) {
                    container.scrollBy({ top: 1200, behavior: 'smooth' });
                    return true;
                }
                window.scrollBy({ top: 1200, behavior: 'smooth' });
                return false;
            }""")
        except Exception:
            return False

    async def _enrich_card(self, sem: asyncio.Semaphore, item: Dict[str, Any], city: str) -> Optional[Lead]:
        """Enriches organization card in a dedicated page with semaphore concurrency."""
        if not self.context or not item.get("url"):
            return None

        card_page = None
        phones = list(item.get("phones", []))
        website = item.get("website")
        socials = {}

        try:
            async with sem:
                card_page = await self.context.new_page()
                card_page.set_default_timeout(14000)

                await card_page.goto(item["url"], wait_until="domcontentloaded")
                try:
                    await card_page.wait_for_selector(
                        'h1, div.card-title-view, div.orgpage-header-view',
                        timeout=2500,
                    )
                except Exception:
                    pass
                await asyncio.sleep(0.3)

                # 1. Look for phone reveal buttons
                buttons = await card_page.query_selector_all('button, [role="button"], div[class*="phone"]')
                for b in buttons:
                    try:
                        btxt = await b.inner_text()
                        if "телефон" in btxt.lower() or "показать" in btxt.lower():
                            for pat in PHONE_PATTERNS:
                                for m in pat.findall(btxt):
                                    fp, _, _ = parse_and_format_phone(m, city_hint=city)
                                    if fp and fp not in phones:
                                        phones.append(fp)
                            await b.click(timeout=800)
                            await asyncio.sleep(0.3)
                            break
                    except Exception:
                        pass

                # 2. Extract direct tel: links (most reliable source)
                tel_links = await card_page.query_selector_all('a[href^="tel:"]')
                for t_el in tel_links:
                    try:
                        thref = await t_el.get_attribute("href")
                        if thref:
                            clean_tel = thref.replace("tel:", "").strip()
                            fp, _, _ = parse_and_format_phone(clean_tel, city_hint=city)
                            if fp and fp not in phones:
                                phones.append(fp)
                    except Exception:
                        pass

                # 3. Extract phone numbers from page text via universal regex
                page_text = await card_page.inner_text("body")
                for pat in PHONE_PATTERNS:
                    for m in pat.findall(page_text):
                        fp, _, _ = parse_and_format_phone(m, city_hint=city)
                        if fp and fp not in phones:
                            phones.append(fp)

                # 4. Direct extraction of official website from Yandex business-urls block
                official_site_el = await card_page.query_selector(
                    'div.business-urls-view a, a.business-urls-view__link, [class*="business-urls"] a'
                )
                if official_site_el:
                    site_href = await official_site_el.get_attribute("href")
                    if site_href and not any(ign in site_href.lower() for ign in IGNORABLE_DOMAINS):
                        website = site_href

                # 4. Extract social media links and external links
                external_links = await card_page.query_selector_all('a[href^="http"]')
                for el in external_links:
                    href = await el.get_attribute("href")
                    if not href:
                        continue
                    h_lower = href.lower()
                    if any(ign in h_lower for ign in IGNORABLE_DOMAINS):
                        continue

                    if ("vk.com" in h_lower or "vk.ru" in h_lower) and "yandex" not in h_lower:
                        socials["vk"] = href
                    elif ("t.me" in h_lower or "telegram.me" in h_lower) and "yandex" not in h_lower:
                        socials["telegram"] = href
                    elif "wa.me" in h_lower or "whatsapp.com" in h_lower:
                        socials["whatsapp"] = href
                    elif "instagram.com" in h_lower:
                        socials["instagram"] = href
                    elif "ok.ru" in h_lower or "odnoklassniki.ru" in h_lower:
                        socials["ok"] = href
                    elif "viber.click" in h_lower or "viber.com" in h_lower:
                        socials["viber"] = href
                    elif "facebook.com" in h_lower or "fb.com" in h_lower:
                        socials["facebook"] = href
                    elif not website:
                        website = href

            if website:
                w_chk = website.lower()
                if any(ign in w_chk for ign in IGNORABLE_DOMAINS) or "maps/org" in w_chk or "clck/" in w_chk:
                    website = None

        except Exception as e:
            logger.debug(f"[Yandex Maps] Error enriching card for {item.get('name')}: {e}")
        finally:
            if card_page:
                try:
                    await card_page.close()
                except Exception:
                    pass

        status, priority = classify_website(website)

        lead = Lead(
            id=item["url"],
            name=item["name"],
            source="Яндекс Карты",
            category=item["category"],
            city=city,
            address=item["address"],
            phones=phones,
            website=website,
            website_status=status,
            lead_priority=priority,
            social_links=socials,
            rating=item["rating"],
            reviews_count=item["reviews_count"],
            map_url=item["url"],
        )
        return lead

    async def search(
        self,
        query: str,
        city: str = "",
        limit: int = 50,
        enrich_contacts: bool = True,
        filter_no_website_only: bool = False,
        filter_type: str = "hot_warm",
        skip_checked: bool = True,
    ) -> List[Lead]:
        """Searches Yandex Maps for leads matching the query and city."""
        self.leads = []
        self._seen_urls = set()
        self.skipped_checked_count = 0

        # Preload remembered organizations for instant O(1) in-memory deduplication
        cached_memory = (
            memory_db.load_cached_lookups()
            if skip_checked
            else {"urls": set(), "phones": set(), "name_city": set()}
        )
        if skip_checked and cached_memory["urls"]:
            logger.info(f"[Yandex Maps] Loaded {len(cached_memory['urls'])} remembered places from memory.")

        full_query = f"{query} {city}".strip() if city else query.strip()
        encoded_query = urllib.parse.quote(full_query)
        target_url = f"https://yandex.ru/maps/?text={encoded_query}"

        await self.start()
        logger.info(f"[Yandex Maps] Navigating to {target_url}")

        # Calculate optimal candidate pool size
        if filter_no_website_only or filter_type == "hot_only":
            raw_target = min(max(limit * 3, 30), 120)
        elif filter_type in ("hot_warm", "social_only"):
            raw_target = min(max(limit * 2, 25), 100)
        else:
            raw_target = min(limit, 80)

        raw_items: List[Dict[str, Any]] = []

        try:
            await self.page.goto(target_url, wait_until="domcontentloaded", timeout=self.timeout)
            await asyncio.sleep(3.5)

            scroll_attempts = 0
            max_scrolls = 30
            unchanged_scrolls = 0
            last_count = 0

            while len(raw_items) < raw_target and scroll_attempts < max_scrolls:
                snippets = await self.page.query_selector_all("li.search-snippet-view")

                for snip in snippets:
                    org_link_el = await snip.query_selector('a[href*="/maps/org/"]')
                    if not org_link_el:
                        continue
                    name = (await org_link_el.inner_text()).strip()
                    if not name:
                        continue

                    href = await org_link_el.get_attribute("href")
                    if not href:
                        continue
                    map_url = urllib.parse.urljoin("https://yandex.ru", href)

                    if map_url in self._seen_urls:
                        continue
                    self._seen_urls.add(map_url)

                    # Check memory: skip previously checked places without opening their card!
                    if skip_checked:
                        name_key = f"{name.strip().lower()}_{(city or 'Россия').strip().lower()}"
                        if map_url in cached_memory["urls"] or name_key in cached_memory["name_city"]:
                            self.skipped_checked_count += 1
                            logger.debug(f"[Yandex Maps] Skipping already checked place: {name}")
                            continue

                    # Category
                    cat_el = await snip.query_selector('a[href*="/category/"]')
                    category = (await cat_el.inner_text()).strip() if cat_el else ""

                    # Address
                    addr_el = await snip.query_selector('a[href*="/house/"], div[class*="address"]')
                    address = (await addr_el.inner_text()).strip() if addr_el else ""

                    # Rating and reviews
                    rating = None
                    reviews_count = None
                    rev_el = await snip.query_selector('a[href*="/reviews/"]')
                    if rev_el:
                        rev_text = await rev_el.inner_text()
                        r_match = re.search(r"(\d+[,\.]\d+)", rev_text)
                        if r_match:
                            try:
                                rating = float(r_match.group(1).replace(",", "."))
                            except ValueError:
                                pass
                        c_match = re.search(r"(\d+)\s*(?:отзыв|оцен)", rev_text)
                        if c_match:
                            try:
                                reviews_count = int(c_match.group(1))
                            except ValueError:
                                pass

                    # Website if already present on snippet
                    site_el = await snip.query_selector('a[href^="http"]:not([href*="yandex"])')
                    website = await site_el.get_attribute("href") if site_el else None

                    # Phone if already present in snippet text
                    phones = []
                    snip_text = await snip.inner_text()
                    for pat in PHONE_PATTERNS:
                        for m in pat.findall(snip_text):
                            fp, _, _ = parse_and_format_phone(m, city_hint=city)
                            if fp and fp not in phones:
                                phones.append(fp)

                    raw_items.append({
                        "name": name,
                        "url": map_url,
                        "category": category,
                        "address": address,
                        "phones": phones,
                        "website": website,
                        "rating": rating,
                        "reviews_count": reviews_count,
                    })

                if len(raw_items) >= raw_target:
                    break

                # Scroll down results panel
                await self._scroll_results()
                await asyncio.sleep(1.3)

                if len(raw_items) == last_count:
                    unchanged_scrolls += 1
                else:
                    unchanged_scrolls = 0
                    last_count = len(raw_items)

                if unchanged_scrolls >= 4:
                    logger.info("[Yandex Maps] Reached end of search results.")
                    break

                if self.on_progress and len(raw_items) > 0:
                    self.on_progress(f"Поиск компаний на карте ({len(raw_items)} найдено)...")

                scroll_attempts += 1

            logger.info(f"[Yandex Maps] Snippets collected: {len(raw_items)}. Enriching contacts...")

            # Filter helper function
            def is_qualifying(lead: Lead) -> bool:
                if filter_no_website_only or filter_type == "hot_only":
                    return lead.lead_priority == LeadPriority.HIGH and (not lead.website or lead.website_status == WebsiteStatus.NO_WEBSITE)
                elif filter_type == "social_only":
                    return lead.lead_priority == LeadPriority.MEDIUM
                elif filter_type == "hot_warm":
                    return lead.lead_priority in (LeadPriority.HIGH, LeadPriority.MEDIUM)
                return True

            # Parallel card enrichment with Semaphore(3)
            sem = asyncio.Semaphore(3)
            chunk_size = 9

            for i in range(0, len(raw_items), chunk_size):
                if len(self.leads) >= limit:
                    break

                chunk = raw_items[i:i + chunk_size]
                if self.on_progress:
                    self.on_progress(f"Проверка сайтов и контактов ({min(i + len(chunk), len(raw_items))}/{len(raw_items)})...")
                if enrich_contacts:
                    tasks = [self._enrich_card(sem, it, city=city or "Россия") for it in chunk]
                    enriched_leads = await asyncio.gather(*tasks)
                else:
                    enriched_leads = []
                    for it in chunk:
                        status, priority = classify_website(it["website"])
                        enriched_leads.append(Lead(
                            id=it["url"],
                            name=it["name"],
                            source="Яндекс Карты",
                            category=it["category"],
                            city=city or "Россия",
                            address=it["address"],
                            phones=it["phones"],
                            website=it["website"],
                            website_status=status,
                            lead_priority=priority,
                            rating=it["rating"],
                            reviews_count=it["reviews_count"],
                            map_url=it["url"],
                        ))

                valid_batch = [l for l in enriched_leads if l]
                if valid_batch:
                    memory_db.save_leads(valid_batch)

                for lead in enriched_leads:
                    if not lead:
                        continue
                    if is_qualifying(lead):
                        if lead not in self.leads:
                            self.leads.append(lead)
                            if self.on_lead_found:
                                self.on_lead_found(lead)
                            if len(self.leads) >= limit:
                                break

        except Exception as e:
            logger.error(f"[Yandex Maps] Search error: {e}")
        finally:
            await self.close()

        logger.info(
            f"[Yandex Maps] Finished. Extracted {len(self.leads)} leads. "
            f"Skipped {self.skipped_checked_count} previously checked places."
        )
        return self.leads[:limit]
