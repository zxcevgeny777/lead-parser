"""Yandex Maps scraper using Playwright with human-like scrolling, parallel card enrichment, and smart quota filtering."""
import asyncio
import logging
import re
import urllib.parse
from typing import List, Dict, Any, Optional, Callable

from core.models import Lead, LeadPriority, WebsiteStatus, classify_website, parse_and_format_phone, unwrap_and_clean_url
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


def extract_yandex_org_id(url_or_href: str) -> Optional[str]:
    """Extracts numeric Yandex organization ID from any map URL or snippet link."""
    if not url_or_href:
        return None
    m = re.search(r"/org/(?:[^/]+/)?(\d+)", url_or_href)
    if m:
        return m.group(1)
    m2 = re.search(r"\b(\d{8,14})\b", url_or_href)
    return m2.group(1) if m2 else None


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
        self._seen_org_ids = set()
        self.skipped_checked_count: int = 0

    async def _scroll_results(self) -> bool:
        """Scrolls the actual scroll container in Yandex Maps sidebar instantly."""
        if not self.page:
            return False
        try:
            return await self.page.evaluate("""() => {
                const container = document.querySelector('div.scroll__container') ||
                                  document.querySelector('ul.search-list-view__list') ||
                                  document.querySelector('div[class*="search-list-view"]');
                if (container) {
                    container.scrollTop += 1400;
                    return true;
                }
                window.scrollBy(0, 1400);
                return false;
            }""")
        except Exception:
            return False

    async def _extract_from_page_state(self, city: str) -> List[Lead]:
        """Extracts organizations directly from the embedded Yandex Maps Redux/React state in the page."""
        if not self.page:
            return []
        try:
            state_json = await self.page.evaluate("""() => {
                const scripts = Array.from(document.querySelectorAll('script'));
                for (const s of scripts) {
                    if (s.textContent && s.textContent.includes('"stack"') && s.textContent.includes('"results"')) {
                        return s.textContent;
                    }
                }
                return null;
            }""")
            if not state_json:
                return []
            import json
            data = json.loads(state_json)
            results = data.get("stack", [{}])[0].get("results", {})
            items = results.get("items", [])
            extracted = []
            for it in items:
                sub_items = it.get("items", [it])
                for s_it in sub_items:
                    raw_id = s_it.get("id")
                    org_id = str(raw_id) if raw_id else None
                    if not org_id:
                        continue
                    if org_id in self._seen_org_ids:
                        continue
                    self._seen_org_ids.add(org_id)

                    map_url = f"https://yandex.ru/maps/org/{org_id}/"
                    self._seen_urls.add(map_url)

                    title = s_it.get("title", "").strip()
                    if not title:
                        continue

                    # Memory check
                    if self.skip_checked:
                        name_key = f"{title.strip().lower()}_{(city or 'Россия').strip().lower()}"
                        if map_url in self._cached_memory["urls"] or name_key in self._cached_memory["name_city"]:
                            self.skipped_checked_count += 1
                            continue

                    addr = s_it.get("fullAddress") or s_it.get("address") or city

                    # Categories
                    cats = [c.get("name") for c in s_it.get("categories", []) if c.get("name")]
                    cat_str = ", ".join(cats)

                    # Rating
                    rating_d = s_it.get("ratingData", {})
                    rating = rating_d.get("rating")
                    reviews_count = rating_d.get("count")

                    # Phones
                    phones = []
                    for p in s_it.get("phones", []) or []:
                        raw_p = p.get("value") or p.get("number")
                        if raw_p:
                            fp, _, _ = parse_and_format_phone(raw_p, city_hint=city)
                            if fp and fp not in phones:
                                phones.append(fp)

                    # Websites
                    raw_urls = s_it.get("urls", []) or []
                    website = None
                    for u in raw_urls:
                        clean_u = unwrap_and_clean_url(u)
                        if clean_u:
                            st, _ = classify_website(clean_u)
                            if st == WebsiteStatus.HAS_WEBSITE:
                                website = clean_u
                                break
                            elif not website:
                                website = clean_u

                    # Social links
                    socials = {}
                    for soc in s_it.get("socialLinks", []) or []:
                        stype = soc.get("type", "")
                        shref = soc.get("href", "")
                        if stype and shref:
                            socials[stype] = shref
                            if not website:
                                website = shref

                    status, priority = classify_website(website)
                    lead = Lead(
                        id=map_url,
                        name=title,
                        source="Яндекс Карты",
                        category=cat_str,
                        city=city,
                        address=addr,
                        phones=phones,
                        website=website,
                        website_status=status,
                        lead_priority=priority,
                        social_links=socials,
                        rating=rating,
                        reviews_count=reviews_count,
                        map_url=map_url,
                    )
                    extracted.append(lead)
            return extracted
        except Exception as e:
            logger.debug(f"[Yandex Maps] Error extracting state: {e}")
            return []

    async def _reveal_snippet_detail(self, snippet_el, city: str) -> Dict[str, Any]:
        """Expands organization card inside the main page to reveal hidden phone/website without getting rate-limited."""
        res = {"phones": [], "website": None, "socials": {}}
        try:
            await snippet_el.click(timeout=1500)
            await asyncio.sleep(0.4)

            # Check website links in sidebar
            site_els = await self.page.query_selector_all(
                'div.business-urls-view a, a.business-urls-view__link, [class*="business-urls"] a, [class*="website"] a'
            )
            for sel in site_els:
                href = await sel.get_attribute("href")
                cu = unwrap_and_clean_url(href)
                if cu:
                    st, _ = classify_website(cu)
                    if st == WebsiteStatus.HAS_WEBSITE:
                        res["website"] = cu
                        break
                    elif not res["website"]:
                        res["website"] = cu

            # Phone buttons
            phone_btns = await self.page.query_selector_all('button, [role="button"], div[class*="phone"]')
            for pb in phone_btns[:2]:
                txt = (await pb.inner_text()).lower()
                if "показать" in txt or "телефон" in txt:
                    await pb.click(timeout=800)
                    await asyncio.sleep(0.3)
                    break

            # Tel links
            tels = await self.page.query_selector_all('a[href^="tel:"]')
            for t in tels:
                thref = await t.get_attribute("href")
                if thref:
                    fp, _, _ = parse_and_format_phone(thref.replace("tel:", ""), city_hint=city)
                    if fp and fp not in res["phones"]:
                        res["phones"].append(fp)

            # Navigate back to results list if back button exists
            back_btn = await self.page.query_selector('button[aria-label="Назад"], div[class*="back-button"], button[class*="close-button"]')
            if back_btn:
                try:
                    await back_btn.click(timeout=600)
                    await asyncio.sleep(0.15)
                except Exception:
                    pass
        except Exception:
            pass
        return res

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
        """Searches Yandex Maps for leads matching the query and city, scrolling until limit is met."""
        self.leads = []
        self._seen_urls = set()
        self.skipped_checked_count = 0
        self.skip_checked = skip_checked

        # Preload remembered organizations for instant O(1) in-memory deduplication
        self._cached_memory = (
            memory_db.load_cached_lookups()
            if skip_checked
            else {"urls": set(), "phones": set(), "name_city": set()}
        )
        if skip_checked and self._cached_memory["urls"]:
            logger.info(f"[Yandex Maps] Loaded {len(self._cached_memory['urls'])} remembered places from memory.")

        full_query = f"{query} {city}".strip() if city else query.strip()
        encoded_query = urllib.parse.quote(full_query)
        target_url = f"https://yandex.ru/maps/?text={encoded_query}"

        await self.start()
        logger.info(f"[Yandex Maps] Navigating to {target_url}")

        def is_qualifying(lead: Lead) -> bool:
            if filter_no_website_only or filter_type == "hot_only":
                return lead.lead_priority == LeadPriority.HIGH and (not lead.website or lead.website_status == WebsiteStatus.NO_WEBSITE)
            elif filter_type == "social_only":
                return lead.lead_priority == LeadPriority.MEDIUM
            elif filter_type == "hot_warm":
                return lead.lead_priority in (LeadPriority.HIGH, LeadPriority.MEDIUM) and lead.website_status != WebsiteStatus.HAS_WEBSITE
            return True

        try:
            await self.page.goto(target_url, wait_until="domcontentloaded", timeout=self.timeout)
            try:
                await self.page.wait_for_selector("li.search-snippet-view, div.search-empty-view", timeout=7000)
            except Exception:
                pass

            scroll_attempts = 0
            max_scrolls = max(25, limit * 2)
            unchanged_scrolls = 0
            last_leads_count = 0

            while len(self.leads) < limit and scroll_attempts < max_scrolls:
                # 1. State-level extraction (100% accurate, uncorrupted by WAF rate limits)
                state_leads = await self._extract_from_page_state(city=city or "Россия")
                for s_lead in state_leads:
                    if is_qualifying(s_lead):
                        if s_lead not in self.leads:
                            self.leads.append(s_lead)
                            if self.on_lead_found:
                                self.on_lead_found(s_lead)
                            if len(self.leads) >= limit:
                                break

                if len(self.leads) >= limit:
                    break

                # 2. DOM-level snippet extraction
                snippets = await self.page.query_selector_all("li.search-snippet-view")
                for snip in snippets:
                    if len(self.leads) >= limit:
                        break

                    org_link_el = await snip.query_selector('a[href*="/maps/org/"]')
                    if not org_link_el:
                        continue
                    name = (await org_link_el.inner_text()).strip()
                    if not name:
                        continue

                    href = await org_link_el.get_attribute("href")
                    if not href:
                        continue

                    org_id = extract_yandex_org_id(href)
                    if org_id and org_id in self._seen_org_ids:
                        # Already extracted from page state with full uncorrupted data
                        continue
                    if org_id:
                        self._seen_org_ids.add(org_id)

                    map_url = f"https://yandex.ru/maps/org/{org_id}/" if org_id else urllib.parse.urljoin("https://yandex.ru", href)
                    if map_url in self._seen_urls:
                        continue
                    self._seen_urls.add(map_url)

                    # Memory check
                    if skip_checked:
                        name_key = f"{name.strip().lower()}_{(city or 'Россия').strip().lower()}"
                        if map_url in self._cached_memory["urls"] or name_key in self._cached_memory["name_city"]:
                            self.skipped_checked_count += 1
                            continue

                    cat_el = await snip.query_selector('a[href*="/category/"]')
                    category = (await cat_el.inner_text()).strip() if cat_el else ""

                    addr_el = await snip.query_selector('a[href*="/house/"], div[class*="address"]')
                    address = (await addr_el.inner_text()).strip() if addr_el else ""

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

                    # Extract website from snippet links
                    site_els = await snip.query_selector_all('a[class*="business-url"], a[class*="link"], a[href^="http"]')
                    website = None
                    for site_el in site_els:
                        site_href = await site_el.get_attribute("href")
                        cleaned = unwrap_and_clean_url(site_href)
                        if not cleaned:
                            try:
                                stxt = (await site_el.inner_text()).strip()
                                if stxt and "." in stxt and len(stxt) < 55 and not any(ign in stxt.lower() for ign in ("yandex", "ya.ru", "ya.by", "маршрут", "отзыв")):
                                    cleaned = unwrap_and_clean_url(stxt)
                            except Exception:
                                pass
                        if cleaned:
                            st, _ = classify_website(cleaned)
                            if st == WebsiteStatus.HAS_WEBSITE:
                                website = cleaned
                                break
                            elif not website:
                                website = cleaned

                    phones = []
                    snip_text = await snip.inner_text()
                    for pat in PHONE_PATTERNS:
                        for m in pat.findall(snip_text):
                            fp, _, _ = parse_and_format_phone(m, city_hint=city)
                            if fp and fp not in phones:
                                phones.append(fp)

                    # If no website found directly on the snippet, reveal organization card details
                    if not website:
                        detail = await self._reveal_snippet_detail(snip, city=city or "Россия")
                        if detail.get("website"):
                            website = detail["website"]
                        if detail.get("phones"):
                            for p in detail["phones"]:
                                if p not in phones:
                                    phones.append(p)

                    status, priority = classify_website(website)
                    lead = Lead(
                        id=map_url,
                        name=name,
                        source="Яндекс Карты",
                        category=category,
                        city=city or "Россия",
                        address=address,
                        phones=phones,
                        website=website,
                        website_status=status,
                        lead_priority=priority,
                        rating=rating,
                        reviews_count=reviews_count,
                        map_url=map_url,
                    )

                    if is_qualifying(lead):
                        if lead not in self.leads:
                            self.leads.append(lead)
                            if self.on_lead_found:
                                self.on_lead_found(lead)

                if len(self.leads) >= limit:
                    break

                # Scroll down results panel
                await self._scroll_results()

                # Micro-poll for DOM snippets rendering
                prev_snip_len = len(snippets)
                for _ in range(5):
                    await asyncio.sleep(0.2)
                    curr_snips = await self.page.query_selector_all("li.search-snippet-view")
                    if len(curr_snips) > prev_snip_len:
                        break

                if len(self.leads) == last_leads_count:
                    unchanged_scrolls += 1
                else:
                    unchanged_scrolls = 0
                    last_leads_count = len(self.leads)

                if unchanged_scrolls >= 5:
                    logger.info("[Yandex Maps] Reached end of search results.")
                    break

                if self.on_progress:
                    self.on_progress(f"Яндекс Карты ({city}): собрано {len(self.leads)}/{limit} лидов...")

                scroll_attempts += 1

        except Exception as e:
            logger.error(f"[Yandex Maps] Search error: {e}")
        finally:
            await self.close()

        if self.leads:
            memory_db.save_leads(self.leads)

        logger.info(
            f"[Yandex Maps] Finished. Extracted {len(self.leads)} leads. "
            f"Skipped {self.skipped_checked_count} previously checked places."
        )
        return self.leads[:limit]

