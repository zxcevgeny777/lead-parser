"""Google Maps scraper for European and US businesses using Playwright."""
import asyncio
import logging
import re
import urllib.parse
from typing import List, Optional, Callable, Dict, Any

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright_stealth import Stealth

from core.models import Lead, WebsiteStatus, LeadPriority, classify_website, format_phone
from core.memory import memory_db
from core.web_verifier import verify_company_website

logger = logging.getLogger(__name__)


class GoogleMapsScraper:
    """Scrapes local business leads across USA, Europe, and globally from Google Maps.

    Fast feed-scrolling with instant extraction of Name, Rating, Reviews, Phone, Address, and Website status.
    """

    def __init__(
        self,
        headless: bool = True,
        on_lead_found: Optional[Callable[[Lead], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        self.headless = headless
        self.on_lead_found = on_lead_found
        self.on_progress = on_progress
        self.is_running = False

    async def search(
        self,
        query: str,
        city: str = "Miami",
        limit: int = 50,
        filter_type: str = "hot_warm",
        skip_checked: bool = True,
        verify_web: bool = True,
    ) -> List[Lead]:
        self.is_running = True
        leads: List[Lead] = []
        seen_urls = set()

        full_query = f"{query} in {city}" if city and city.lower() not in query.lower() else query
        search_url = f"https://www.google.com/maps/search/{urllib.parse.quote(full_query)}?hl=en"

        if self.on_progress:
            self.on_progress(f"Google Maps: открытие поиска «{full_query}»...")

        async with async_playwright() as p:
            browser: Browser = await p.chromium.launch(
                headless=self.headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-ipv6",
                    "--dns-result-order=ipv4first",
                    "--enable-features=NetworkService,NetworkServiceInProcess",
                    "--lang=en-US,en",
                ]
            )
            context: BrowserContext = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                locale="en-US",
                viewport={"width": 1280, "height": 900},
            )

            # Block heavy map tiles, photos, and trackers for 3x faster card loading
            BLOCKED_RESOURCES = frozenset({"image", "media", "font"})
            async def block_heavy(route):
                req = route.request
                if req.resource_type in BLOCKED_RESOURCES:
                    await route.abort()
                    return
                r_url = req.url.lower()
                if any(t in r_url for t in ("google-analytics", "doubleclick", "googletagmanager", "adservice")):
                    await route.abort()
                    return
                await route.continue_()

            await context.route("**/*", block_heavy)
            page: Page = await context.new_page()
            stealth = Stealth()
            await stealth.apply_stealth_async(page)

            try:
                # Retry up to 3 times in case of cold socket initialization
                for attempt in range(1, 4):
                    try:
                        await page.goto(search_url, timeout=35000, wait_until="domcontentloaded")
                        break
                    except Exception as ex:
                        if ("ERR_SOCKET_NOT_CONNECTED" in str(ex) or "ERR_CONNECTION" in str(ex) or "net::" in str(ex)) and attempt < 3:
                            logger.warning(f"Google Maps attempt {attempt} failed ({ex}). Retrying in 1s...")
                            await asyncio.sleep(1.0)
                        else:
                            raise ex

                # 1. Handle Google Cookie / GDPR Consent if shown
                consent_loc = page.locator(
                    'button:has-text("Accept all"), button:has-text("I agree"), '
                    'form[action*="consent"] button, button[aria-label*="Accept all" i]'
                )
                if await consent_loc.count() > 0:
                    try:
                        await consent_loc.first.click(timeout=2500)
                    except Exception:
                        pass

                # Wait for results feed or place card
                try:
                    await page.wait_for_selector('div[role="feed"], h1', timeout=6000)
                except Exception:
                    pass
                if await feed_loc.count() == 0:
                    # Check if single place directly opened
                    if "/maps/place/" in page.url:
                        single_lead = await self._parse_single_place(page, city, query)
                        if single_lead:
                            leads.append(single_lead)
                            if self.on_lead_found:
                                self.on_lead_found(single_lead)
                    await browser.close()
                    return leads

                # 3. Scroll feed and collect items
                consecutive_no_new = 0
                max_scroll_attempts = min(limit * 2 + 10, 80)
                scroll_count = 0

                while len(leads) < limit and scroll_count < max_scroll_attempts and self.is_running:
                    scroll_count += 1

                    # Extract current visible cards
                    cards = await page.evaluate('''() => {
                        const feed = document.querySelector('div[role="feed"]');
                        if (!feed) return [];
                        
                        const items = Array.from(feed.querySelectorAll('div.Nv2PK'));
                        return items.map(item => {
                            const nameEl = item.querySelector('.qBF1Pd, .fontHeadlineSmall, [class*="fontHeadline"]');
                            const name = nameEl ? nameEl.innerText.trim() : "";
                            
                            const linkEl = item.querySelector('a[href*="/maps/place/"]');
                            const link = linkEl ? linkEl.href : "";
                            
                            const ratingEl = item.querySelector('span.MW4etd, span[class*="rating"]');
                            const rating = ratingEl ? ratingEl.innerText.trim() : "";
                            
                            const reviewsEl = item.querySelector('span.UY7F9, span[class*="review"]');
                            const reviews = reviewsEl ? reviewsEl.innerText.trim().replace(/[()]/g, '') : "";
                            
                            const siteEl = item.querySelector('a[data-value="Website"], a[aria-label*="website" i]');
                            const website = siteEl ? siteEl.href : "";
                            
                            const lines = item.innerText.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                            
                            return {
                                name,
                                link,
                                rating,
                                reviews,
                                website,
                                raw_text: item.innerText,
                                lines
                            };
                        });
                    }''')

                    new_in_pass = 0
                    for c in cards:
                        if len(leads) >= limit or not self.is_running:
                            break

                        place_url = c.get("link", "")
                        name = c.get("name", "").strip()
                        if not name or not place_url or place_url in seen_urls:
                            continue

                        seen_urls.add(place_url)
                        new_in_pass += 1

                        # Memory check
                        if skip_checked and memory_db.is_checked(url=place_url, name=name, city=city):
                            continue

                        raw_text = c.get("raw_text", "")
                        raw_website = c.get("website", "").strip()

                        # Extract phone number via regex from card text
                        phone_match = re.search(
                            r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
                            raw_text
                        )
                        phones = [format_phone(phone_match.group(0).strip())] if phone_match else []

                        # Extract category and address from lines
                        lines = c.get("lines", [])
                        category = query
                        address = city

                        # Lines usually: [Name, Name, Rating(Reviews), Category · Address, Open hours · Phone]
                        for line in lines[2:]:
                            parts = [p.strip() for p in line.split("·") if p.strip()]
                            for p_part in parts:
                                if not phone_match or p_part != phone_match.group(0):
                                    if any(w in p_part.lower() for w in ["open", "closed", "24 hours", "am", "pm"]):
                                        continue
                                    if len(p_part) > 3 and not re.search(r'\d{3}[-.\s]?\d{4}', p_part):
                                        if not category or category == query:
                                            category = p_part
                                        elif not address or address == city:
                                            address = f"{p_part}, {city}"

                        # Rating and reviews
                        rating_val = None
                        try:
                            if c.get("rating"):
                                rating_val = float(c["rating"].replace(",", "."))
                        except Exception:
                            pass

                        reviews_val = None
                        try:
                            if c.get("reviews"):
                                clean_rev = re.sub(r'\D', '', c["reviews"])
                                if clean_rev:
                                    reviews_val = int(clean_rev)
                        except Exception:
                            pass

                        # Determine website status & priority
                        website_status, priority = classify_website(raw_website if raw_website else None)

                        # Filter by user preference
                        if filter_type == "hot_only" and website_status != WebsiteStatus.NO_WEBSITE:
                            continue
                        elif filter_type == "social_only" and website_status not in (WebsiteStatus.SOCIAL, WebsiteStatus.TAPLINK, WebsiteStatus.BUILDER):
                            continue
                        elif filter_type == "hot_warm" and website_status == WebsiteStatus.HAS_WEBSITE:
                            continue

                        # Web verification check if requested and marked as NO_WEBSITE
                        if verify_web and website_status == WebsiteStatus.NO_WEBSITE:
                            try:
                                has_site, detected_site = await verify_company_website(name, city)
                                if has_site and detected_site:
                                    if filter_type in ("hot_only", "hot_warm"):
                                        continue
                                    website_status = WebsiteStatus.HAS_WEBSITE
                                    priority = LeadPriority.LOW
                                    raw_website = detected_site
                            except Exception:
                                pass

                        lead = Lead(
                            name=name,
                            source="Google Maps",
                            category=category,
                            city=city,
                            address=address,
                            phones=phones,
                            website=raw_website if raw_website else None,
                            website_status=website_status,
                            lead_priority=priority,
                            rating=rating_val,
                            reviews_count=reviews_val,
                            map_url=place_url,
                        )

                        # Save to memory
                        memory_db.save_lead(lead)

                        leads.append(lead)
                        if self.on_lead_found:
                            self.on_lead_found(lead)

                        if self.on_progress:
                            self.on_progress(f"Google Maps ({city}): найдено {len(leads)}/{limit} лидов...")

                    if new_in_pass == 0:
                        consecutive_no_new += 1
                        if consecutive_no_new >= 6:
                            break
                    else:
                        consecutive_no_new = 0

                    # Scroll feed down by scrolling into view the last card & setting scrollTop
                    await page.evaluate('''() => {
                        const f = document.querySelector('div[role="feed"]');
                        if (f) {
                            const cards = f.querySelectorAll('div.Nv2PK');
                            if (cards.length > 0) {
                                cards[cards.length - 1].scrollIntoView();
                            }
                            f.scrollTop = f.scrollHeight;
                        }
                    }''')
                    
                    # Micro-poll for DOM updates instead of fixed 1.8s delay
                    prev_card_count = len(cards)
                    for _ in range(5):
                        await asyncio.sleep(0.15)
                        cnt = await page.evaluate('''() => {
                            const f = document.querySelector('div[role="feed"]');
                            return f ? f.querySelectorAll('div.Nv2PK').length : 0;
                        }''')
                        if cnt > prev_card_count:
                            break

                if self.on_progress:
                    self.on_progress(f"Google Maps: сбор завершен. Всего найдено {len(leads)} лидов.")

            except Exception as e:
                safe_err = str(e).encode("ascii", "replace").decode("ascii")
                logger.error(f"Google Maps scraper error: {safe_err}")
                if self.on_progress:
                    self.on_progress(f"Google Maps: ошибка ({safe_err})")
            finally:
                await browser.close()

        return leads

    async def _parse_single_place(self, page: Page, city: str, query: str) -> Optional[Lead]:
        """Parses details when Google Maps redirects directly to a single business card."""
        try:
            info = await page.evaluate('''() => {
                const name = document.querySelector('h1')?.innerText?.trim() || "";
                const rating = document.querySelector('div.F7nice span[aria-hidden="true"]')?.innerText?.trim() || "";
                const reviews = document.querySelector('div.F7nice span:last-child')?.innerText?.trim()?.replace(/[()]/g, '') || "";
                const address = document.querySelector('button[data-item-id="address"]')?.innerText?.trim() || "";
                const phone = document.querySelector('button[data-item-id^="phone:"]')?.innerText?.trim() || "";
                const website = document.querySelector('a[data-item-id="authority"]')?.href || "";
                const category = document.querySelector('button[jsaction*="category"]')?.innerText?.trim() || "";
                return { name, rating, reviews, address, phone, website, category };
            }''')

            name = info.get("name")
            if not name:
                return None

            raw_site = info.get("website", "").strip()
            status, priority = classify_website(raw_site if raw_site else None)
            phone_val = info.get("phone", "").strip()

            return Lead(
                name=name,
                source="Google Maps",
                category=info.get("category") or query,
                city=city,
                address=info.get("address") or city,
                phones=[format_phone(phone_val)] if phone_val else [],
                website=raw_site if raw_site else None,
                website_status=status,
                lead_priority=priority,
                map_url=page.url,
            )
        except Exception:
            return None
