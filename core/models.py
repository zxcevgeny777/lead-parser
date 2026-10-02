"""Data models and qualification logic for website development leads."""
from enum import Enum
import re
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse, parse_qs, unquote
from pydantic import BaseModel, Field, computed_field


class WebsiteStatus(str, Enum):
    NO_WEBSITE = "🔥 Нет сайта"
    TAPLINK = "⚡ Только Taplink"
    SOCIAL = "⚡ Только соцсеть"
    BUILDER = "💡 Конструктор (Tilda/Wix)"
    HAS_WEBSITE = "⚪ Есть свой сайт"


class LeadPriority(str, Enum):
    HIGH = "🔥 Высокий (Горячий)"
    MEDIUM = "⚡ Средний (Теплый)"
    LOW = "⚪ Низкий"


# Domains and signatures for classification
TAPLINK_DOMAINS = {
    "taplink.cc",
    "taplink.ru",
    "linktr.ee",
    "hipolink.me",
    "mssg.me",
    "mssg.cc",
    "inlnk.ru",
    "aqulas.me",
    "tap.link",
    "meconnect.ru",
    "msto.me",
}

SOCIAL_DOMAINS = {
    "vk.com",
    "vk.me",
    "t.me",
    "telegram.me",
    "instagram.com",
    "instagr.am",
    "ok.ru",
    "odnoklassniki.ru",
    "facebook.com",
    "fb.com",
    "wa.me",
    "whatsapp.com",
    "api.whatsapp.com",
    "viber.click",
    "youtube.com",
    "youtu.be",
    "rutube.ru",
    "dzen.ru",
    "zen.yandex.ru",
}

FREE_BUILDER_PATTERNS = [
    r"\.tilda\.ws",
    r"\.wixsite\.com",
    r"\.setup\.ru",
    r"\.nethouse\.ru",
    r"\.vigbo\.com",
    r"\.craftum\.io",
    r"\.tobiz\.net",
    r"\.site123\.me",
    r"\.mozello\.com",
    r"\.webnode\.ru",
    r"\.jimdosite\.com",
]

MAP_AND_SEARCH_DOMAINS = {
    "yandex.ru", "yandex.by", "yandex.kz", "yandex.com", "yandex.uz", "ya.ru", "ya.by",
    "google.com", "google.ru", "google.by", "maps.google.com", "2gis.ru", "2gis.by", "2gis.com",
    "apple.com", "maps.apple.com", "duckduckgo.com", "bing.com", "mail.ru", "dzen.ru", "rambler.ru",
}

BOOKING_DOMAINS = {
    "yclients.com", "yclients.site", "dikidi.ru", "dikidi.net", "dikidi.online", "dikidi.app", "dikidi.me",
    "clients.site", "alteg.io", "altegio.com", "rubitime.ru", "gnom.guru", "bnovo.ru", "traveline.ru",
    "mst.link",
}

DIRECTORY_CATALOG_DOMAINS = {
    "zoon.ru", "zoon.by", "prodoctorov.ru", "docdoc.ru", "sberhealth.ru",
    "tam.by", "relax.by", "deal.by", "kufar.by", "onliner.by", "s.onliner.by", "catalog.onliner.by",
    "103.by", "doska.by", "infopark.by", "tochka.by", "b2b.by", "kartoteka.by", "spr.by", "spr.ru",
    "infominsk.by", "minsk-in.net", "gorod24.by", "otzyvy.by", "prof-master.by", "flagma.by",
    "ouuo.ru", "ayle.ru", "buk.by", "maxi.by", "tut.by", "govorim.by",
    "flamp.ru", "otzovik.com", "irecommend.ru", "yell.ru", "cataloxy.ru", "cataloxy.by", "orgpage.ru",
    "yp.ru", "vl.ru", "pulscen.ru", "pulscen.by", "tiu.ru", "blizko.ru", "blizko.by", "avito.ru",
    "allinform.ru", "infomesto.com", "checko.ru", "rusprofile.ru", "spark-interfax.ru", "list-org.com",
    "hh.ru", "superjob.ru", "rabota.ru", "rabota.by", "praca.by",
}


def unwrap_and_clean_url(raw_url: Optional[str]) -> Optional[str]:
    """Unwraps redirect wrappers (Yandex clck/jsredir, Google url?q=, 2GIS redirect)
    and removes pure map/search engine links.
    Returns cleaned business URL or None if company has no official website.
    """
    if not raw_url or not isinstance(raw_url, str):
        return None
    url = raw_url.strip()
    if not url or url.lower() in {"нет", "none", "null", "-", "отсутствует", "undefined"}:
        return None

    if not url.startswith(("http://", "https://")):
        if "." in url and not url.startswith("/") and " " not in url:
            url = "https://" + url
        else:
            return None

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    # 1. Check query parameters for wrapped destination URL (Yandex, Google, 2GIS redirects)
    qs = parse_qs(parsed.query)
    for p in ("text", "url", "q", "target", "dest", "link", "to", "r"):
        if p in qs and qs[p]:
            candidate = unquote(qs[p][0]).strip()
            if candidate.startswith(("http://", "https://")):
                try:
                    c_parsed = urlparse(candidate)
                    c_netloc = c_parsed.netloc.lower()
                    if not any(ign in c_netloc for ign in ("yandex.", "ya.ru", "ya.by", "google.", "2gis.", "apple.")):
                        return unwrap_and_clean_url(candidate)
                except Exception:
                    pass

    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # 2. Check search engine / map links (NOT business websites!)
    for map_domain in MAP_AND_SEARCH_DOMAINS:
        if netloc == map_domain or netloc.endswith("." + map_domain) or any(d in netloc for d in ("yandex.", "google.", "2gis.")):
            return None

    clean_site = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
    return clean_site or f"{parsed.scheme}://{parsed.netloc}"


def classify_website(raw_url: Optional[str]) -> Tuple[WebsiteStatus, LeadPriority]:
    """Classifies a business website for lead scoring.

    Returns (WebsiteStatus, LeadPriority).
    """
    clean_url = unwrap_and_clean_url(raw_url)
    if not clean_url:
        return WebsiteStatus.NO_WEBSITE, LeadPriority.HIGH

    try:
        parsed = urlparse(clean_url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
    except Exception:
        return WebsiteStatus.NO_WEBSITE, LeadPriority.HIGH

    # 0. Check search engine / map links (NOT business websites!)
    for map_domain in MAP_AND_SEARCH_DOMAINS:
        if netloc == map_domain or netloc.endswith("." + map_domain) or any(d in netloc for d in ("yandex.", "google.", "2gis.")):
            return WebsiteStatus.NO_WEBSITE, LeadPriority.HIGH

    # 1. Check Taplink / Link aggregators
    for tap_domain in TAPLINK_DOMAINS:
        if netloc == tap_domain or netloc.endswith("." + tap_domain):
            return WebsiteStatus.TAPLINK, LeadPriority.MEDIUM

    # 2. Check Social Networks / Messengers
    for soc_domain in SOCIAL_DOMAINS:
        if netloc == soc_domain or netloc.endswith("." + soc_domain):
            return WebsiteStatus.SOCIAL, LeadPriority.MEDIUM

    # 3. Check Free builder subdomains
    for pattern in FREE_BUILDER_PATTERNS:
        if re.search(pattern, netloc):
            return WebsiteStatus.BUILDER, LeadPriority.MEDIUM

    # 4. Check Booking and widget platforms
    for book_domain in BOOKING_DOMAINS:
        if netloc == book_domain or netloc.endswith("." + book_domain):
            return WebsiteStatus.TAPLINK, LeadPriority.MEDIUM

    # 5. Check Catalogs / Directories (Profiles in aggregators are not personal websites)
    for cat_domain in DIRECTORY_CATALOG_DOMAINS:
        if netloc == cat_domain or netloc.endswith("." + cat_domain):
            return WebsiteStatus.TAPLINK, LeadPriority.MEDIUM

    # 6. Normal website
    return WebsiteStatus.HAS_WEBSITE, LeadPriority.LOW


def parse_and_format_phone(phone: str, country_hint: str = "", city_hint: str = "") -> Tuple[str, bool, str]:
    """Parses, formats, and detects phone type (mobile vs landline).

    Returns:
        (formatted_phone, is_mobile, clean_digits_with_cc)
    """
    if not phone or not isinstance(phone, str):
        return "", False, ""

    digits = re.sub(r"\D", "", phone)
    if not digits:
        return phone.strip(), False, ""

    city_str = str(city_hint).lower()
    is_by_context = any(w in city_str for w in [
        "минск", "брест", "гродно", "витебск", "могилев", "гомель",
        "барановичи", "бобруйск", "пинск", "борисов", "солигорск", "лида",
        "молодечно", "полоцк", "новополоцк", "беларусь", "рб", "by"
    ]) or "by" in str(country_hint).lower()

    # 1. Belarus (+375)
    # 12 digits starting with 375: +375 29 123-45-67
    if digits.startswith("375") and len(digits) == 12:
        code = digits[3:5]
        is_mob = code in ("29", "33", "44", "25")
        formatted = f"+375 ({code}) {digits[5:8]}-{digits[8:10]}-{digits[10:12]}"
        return formatted, is_mob, digits

    # Belarus local short formats: 8029..., 8044..., 8033..., 8025..., 8017... or (029)...
    by_prefixes = ("8029", "8033", "8044", "8025", "8017", "8016", "8021", "8022", "8023", "8015")
    by_0_prefixes = ("029", "033", "044", "025", "017", "016", "021", "022", "023", "015")

    if digits.startswith("80") and (is_by_context or any(digits.startswith(p) for p in by_prefixes)):
        tail = digits[2:]
        if len(tail) == 9:
            full_digits = "375" + tail
            code = tail[:2]
            is_mob = code in ("29", "33", "44", "25")
            formatted = f"+375 ({code}) {tail[2:5]}-{tail[5:7]}-{tail[7:9]}"
            return formatted, is_mob, full_digits

    if digits.startswith("0") and len(digits) == 10 and (is_by_context or any(digits.startswith(p) for p in by_0_prefixes)):
        tail = digits[1:]
        if len(tail) == 9:
            full_digits = "375" + tail
            code = tail[:2]
            is_mob = code in ("29", "33", "44", "25")
            formatted = f"+375 ({code}) {tail[2:5]}-{tail[5:7]}-{tail[7:9]}"
            return formatted, is_mob, full_digits

    # 9-digit direct mobile without country code in BY context: e.g. 291234567
    if len(digits) == 9 and is_by_context and digits[:2] in ("29", "33", "44", "25"):
        full_digits = "375" + digits
        code = digits[:2]
        formatted = f"+375 ({code}) {digits[2:5]}-{digits[5:7]}-{digits[7:9]}"
        return formatted, True, full_digits

    # 2. Russia (+7) / Kazakhstan (+7)
    if len(digits) == 11 and digits[0] in ("7", "8") and not is_by_context:
        full_digits = "7" + digits[1:]
        code = digits[1:4]
        # Russian mobile: 900-999; Kazakh mobile: 700-709, 771-778
        is_mob = code.startswith("9") or code in [
            "700", "701", "702", "705", "707", "708", "747", "771", "775", "776", "777", "778"
        ]
        formatted = f"+7 ({code}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
        return formatted, is_mob, full_digits

    if len(digits) == 10 and not is_by_context and not any(w in city_str for w in ["miami", "new york", "usa", "los angeles", "chicago"]):
        full_digits = "7" + digits
        code = digits[0:3]
        is_mob = code.startswith("9")
        formatted = f"+7 ({code}) {digits[3:6]}-{digits[6:8]}-{digits[8:10]}"
        return formatted, is_mob, full_digits

    # 3. US / Canada (+1)
    if len(digits) == 11 and digits.startswith("1"):
        formatted = f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:11]}"
        return formatted, True, digits

    if len(digits) == 10 and any(w in city_str for w in ["miami", "new york", "usa", "los angeles", "chicago", "houston", "dallas"]):
        full_digits = "1" + digits
        formatted = f"+1 ({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"
        return formatted, True, full_digits

    # 4. Other International (+44 UK, +49 Germany, +48 Poland, etc.)
    if phone.startswith("+"):
        return phone.strip(), False, digits
    return f"+{digits}", False, digits


def format_phone(phone: str, country_hint: str = "", city_hint: str = "") -> str:
    """Formats phone number to standard format (supports US/CA +1, BY +375, RU +7, and international)."""
    formatted, _, _ = parse_and_format_phone(phone, country_hint=country_hint, city_hint=city_hint)
    return formatted


class Lead(BaseModel):
    """Business lead model with enriched marketing qualification."""
    id: Optional[str] = None
    name: str = Field(..., description="Business / Organization name")
    source: str = Field(..., description="Source: 'Google Maps', 'Яндекс Карты' or '2ГИС'")
    category: str = Field(default="", description="Industry / Niche (e.g. Автосервис)")
    city: str = Field(default="", description="City / Region")
    address: str = Field(default="", description="Full physical address")
    phones: List[str] = Field(default_factory=list, description="Extracted contact phone numbers")
    website: Optional[str] = Field(default=None, description="Website URL if present")
    website_status: WebsiteStatus = Field(default=WebsiteStatus.NO_WEBSITE)
    lead_priority: LeadPriority = Field(default=LeadPriority.HIGH)
    social_links: Dict[str, str] = Field(default_factory=dict, description="VK, TG, WA, Inst links")
    rating: Optional[float] = Field(default=None, description="Average rating (1.0 - 5.0)")
    reviews_count: Optional[int] = Field(default=None, description="Number of customer reviews")
    working_hours: Optional[str] = Field(default=None, description="Working schedule")
    map_url: Optional[str] = Field(default=None, description="Direct URL to organization card")
    notes: Optional[str] = Field(default="", description="Extra metadata / features")
    
    # Enrichment fields
    is_mobile: bool = Field(default=False, description="Whether primary phone is a verified mobile number")
    clean_phone: str = Field(default="", description="Clean digits with country code for messenger links")
    ai_pitch: Optional[str] = Field(default="", description="Personalized AI sales pitch for WhatsApp/Telegram")
    call_script: Optional[str] = Field(default="", description="30-second cold call script for sales")
    site_audit_summary: Optional[str] = Field(default="", description="Quick audit badges: SSL, Mobile, Ads")
    pain_points: List[str] = Field(default_factory=list, description="Extracted customer pain points / review issues")

    def __init__(self, **data):
        super().__init__(**data)

        # Sanitize website: unwrap tracking redirects and clear pure map links
        cleaned_site = unwrap_and_clean_url(self.website)
        object.__setattr__(self, "website", cleaned_site)

        # Automatically classify website if not explicitly given
        if "website_status" not in data or "lead_priority" not in data:
            status, priority = classify_website(cleaned_site)
            object.__setattr__(self, "website_status", status)
            object.__setattr__(self, "lead_priority", priority)
        elif not cleaned_site:
            object.__setattr__(self, "website_status", WebsiteStatus.NO_WEBSITE)
            object.__setattr__(self, "lead_priority", LeadPriority.HIGH)

        # Format phones and determine mobile status
        if self.phones:
            cleaned_phones = []
            primary_is_mobile = False
            primary_clean_digits = ""
            city_hint = str(data.get("city", ""))
            country_hint = "US" if any(w in city_hint.lower() for w in ["miami", "new york", "los angeles", "houston", "dallas", "chicago", "usa", "сша"]) else ""

            for idx, p in enumerate(self.phones):
                fp, is_mob, clean_dig = parse_and_format_phone(p, country_hint=country_hint, city_hint=city_hint)
                if fp not in cleaned_phones:
                    cleaned_phones.append(fp)
                if idx == 0:
                    primary_is_mobile = is_mob
                    primary_clean_digits = clean_dig

            object.__setattr__(self, "phones", cleaned_phones)
            object.__setattr__(self, "is_mobile", primary_is_mobile)
            object.__setattr__(self, "clean_phone", primary_clean_digits)

    @computed_field
    @property
    def primary_phone(self) -> str:
        return self.phones[0] if self.phones else ""

    @computed_field
    @property
    def clean_phone_digits(self) -> str:
        """Returns clean phone digits with country code for messenger links."""
        if self.clean_phone:
            return self.clean_phone
        if not self.primary_phone:
            return ""
        digits = re.sub(r"\D", "", self.primary_phone)
        if len(digits) == 10 and not self.primary_phone.startswith("+7"):
            digits = "1" + digits
        elif len(digits) == 11 and digits.startswith("8"):
            digits = "7" + digits[1:]
        return digits

    @computed_field
    @property
    def phone_type_badge(self) -> str:
        """Visual badge indicating mobile or landline status."""
        if not self.primary_phone:
            return "—"
        return "📱 Моб." if self.is_mobile else "☎️ Гор."

    @computed_field
    @property
    def is_cis(self) -> bool:
        """Checks if lead is from Belarus/Russia/CIS."""
        if self.city and any(c.lower() in self.city.lower() for c in [
            "минск", "брест", "гродно", "витебск", "могилев", "гомель",
            "барановичи", "бобруйск", "пинск", "борисов", "москва", "спб",
            "санкт-петербург", "россия", "беларусь"
        ]):
            return True
        if self.primary_phone and (self.primary_phone.startswith("+375") or self.primary_phone.startswith("+7")):
            return True
        return False

    @computed_field
    @property
    def whatsapp_url(self) -> Optional[str]:
        """Returns direct WhatsApp chat link (https://wa.me/<digits>). Only for mobile numbers in CIS."""
        if not self.is_mobile and self.is_cis:
            return None
        d = self.clean_phone_digits
        if not d:
            return None
        return f"https://wa.me/{d}"

    @computed_field
    @property
    def telegram_url(self) -> Optional[str]:
        """Returns direct Telegram chat link (https://t.me/+<digits>). Only for mobile or if username present."""
        if "telegram" in self.social_links and self.social_links["telegram"]:
            tg_val = self.social_links["telegram"]
            if tg_val.startswith("http"):
                return tg_val
            tg_clean = tg_val.replace("@", "").strip()
            return f"https://t.me/{tg_clean}"
        if not self.is_mobile and self.is_cis:
            return None
        d = self.clean_phone_digits
        if not d:
            return None
        return f"https://t.me/+{d}"

    @computed_field
    @property
    def viber_url(self) -> Optional[str]:
        """Returns direct Viber chat link (viber://chat?number=%2B<digits>). Only for mobile numbers in CIS."""
        if not self.is_mobile and self.is_cis:
            return None
        d = self.clean_phone_digits
        return f"viber://chat?number=%2B{d}" if d else None

    @property
    def phones_str(self) -> str:
        return ", ".join(self.phones) if self.phones else ""

    @property
    def socials_str(self) -> str:
        if not self.social_links:
            return ""
        return ", ".join(f"{k}: {v}" for k, v in self.social_links.items())


class FreelanceOrder(BaseModel):
    """Freelance exchange job/order model."""
    id: Optional[str] = None
    platform: str = Field(..., description="Exchange name: 'Kwork', 'FL.ru', 'Freelancehunt', 'Weblancer', 'Onliner'")
    title: str = Field(..., description="Order / project title")
    price: str = Field(default="По договоренности", description="Budget / price string")
    description: str = Field(default="", description="Order details / description snippet")
    url: str = Field(..., description="Direct URL to view/bid on project")
    proposals_count: Optional[str] = Field(default="", description="Number of bids / proposals")
    date_posted: Optional[str] = Field(default="", description="Published date or relative time")
    category: Optional[str] = Field(default="Разработка сайтов", description="Category / specialization")


