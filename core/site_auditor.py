"""Express Website Auditor for Lead Qualification.

Performs non-blocking fast checks of business websites:
- Mobile responsiveness (viewport check)
- SSL Certificate security
- Response speed (ms)
- Active advertising pixels (Yandex Metrika, Google Ads, VK/FB Pixels)
- CMS / Builder detection
"""
import asyncio
import re
import time
import urllib.parse
import urllib.request
import ssl
from typing import Dict, Any, Optional, Tuple, List

from .models import Lead, LeadPriority, WebsiteStatus

# Common advertising and analytics signatures
AD_PIXEL_PATTERNS = {
    "Яндекс.Метрика / Директ": [
        r"mc\.yandex\.ru/metrika",
        r"yandex_metrika_callbacks",
        r"ym\(\d+,\s*['\"]init['\"]",
        r"tag\.js\?id=\d+",
    ],
    "Google Ads / Analytics": [
        r"googletagmanager\.com/gtag",
        r"googletagmanager\.com/gtm\.js",
        r"google-analytics\.com/analytics\.js",
        r"gtag\(['\"]config['\"]",
    ],
    "Meta / FB Pixel": [
        r"connect\.facebook\.net/[^/]+/fbevents\.js",
        r"fbq\(['\"]init['\"]",
    ],
    "VK Пиксель": [
        r"vk\.com/js/api/openapi\.js",
        r"VK\.Retargeting\.Init",
        r"top-fwz1\.mail\.ru/js/code\.js",
    ],
    "TikTok Pixel": [
        r"analytics\.tiktok\.com/i18n/pixel",
        r"ttq\.load\(",
    ],
}

# CMS signatures
CMS_PATTERNS = {
    "Tilda": [r"tilda\.cc", r"tildacdn\.com", r"t-records"],
    "WordPress": [r"wp-content", r"wp-includes", r"wordpress"],
    "1C-Битрикс": [r"/bitrix/js/", r"/bitrix/templates/", r"bitrix\.info"],
    "Wix": [r"wix\.com", r"wixstatic\.com", r"_wix"],
    "OpenCart": [r"catalog/view/theme", r"route=product/"],
    "Joomla": [r"/media/system/js/", r"/templates/"],
    "Shopify": [r"cdn\.shopify\.com"],
    "Webflow": [r"webflow\.com", r"data-wf-site"],
}


def parse_html_audit_signals(raw_html: str) -> Dict[str, Any]:
    """Parses raw HTML string for viewport, advertising pixels, and CMS."""
    res = {
        "has_mobile_viewport": False,
        "detected_ad_pixels": [],
        "detected_cms": None,
        "summary_badges": [],
        "flaws": [],
        "strengths": [],
    }

    # 1. Check Mobile Viewport
    viewport_match = re.search(r'<meta[^>]+name=["\']viewport["\'][^>]*>', raw_html, re.I)
    if viewport_match:
        res["has_mobile_viewport"] = True
        res["strengths"].append("Мобильная адаптация есть")
    else:
        res["has_mobile_viewport"] = False
        res["flaws"].append("НЕТ мобильной версии (шрифты и блоки ломаются на смартфонах)")
        res["summary_badges"].append("📱 НЕТ МОБИЛКИ!")

    # 2. Check Ad Pixels & Analytics
    for pixel_name, patterns in AD_PIXEL_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, raw_html, re.I):
                res["detected_ad_pixels"].append(pixel_name)
                break

    if res["detected_ad_pixels"]:
        res["summary_badges"].append("💰 КРУТЯТ РЕКЛАМУ")
        res["strengths"].append(f"Реклама: {', '.join(res['detected_ad_pixels'])}")

    # 3. Check CMS / Builder
    for cms_name, patterns in CMS_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, raw_html, re.I):
                res["detected_cms"] = cms_name
                break
        if res["detected_cms"]:
            break

    if res["detected_cms"]:
        res["summary_badges"].append(f"🛠️ {res['detected_cms']}")

    return res


def audit_website_sync(url: str, timeout: float = 3.5) -> Dict[str, Any]:
    """Performs rapid HTTP express audit of a target website."""
    res = {
        "reachable": False,
        "is_ssl": False,
        "response_time_ms": 0,
        "has_mobile_viewport": False,
        "detected_ad_pixels": [],
        "detected_cms": None,
        "summary_badges": [],
        "flaws": [],
        "strengths": [],
    }

    if not url or not isinstance(url, str):
        return res

    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url

    parsed = urllib.parse.urlparse(clean_url)
    if not parsed.netloc:
        return res

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    start_t = time.time()
    try:
        req = urllib.request.Request(
            clean_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            }
        )

        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            elapsed = int((time.time() - start_t) * 1000)
            res["response_time_ms"] = elapsed
            res["reachable"] = True
            final_url = resp.geturl()
            res["is_ssl"] = final_url.startswith("https://")

            # Read first 120KB of HTML (sufficient for head, meta, analytics scripts)
            raw_html = resp.read(120000).decode("utf-8", errors="replace")

            # Parse HTML signals
            signals = parse_html_audit_signals(raw_html)
            res["has_mobile_viewport"] = signals["has_mobile_viewport"]
            res["detected_ad_pixels"] = signals["detected_ad_pixels"]
            res["detected_cms"] = signals["detected_cms"]
            res["summary_badges"].extend(signals["summary_badges"])
            res["flaws"].extend(signals["flaws"])
            res["strengths"].extend(signals["strengths"])

            # 4. Check SSL
            if not res["is_ssl"]:
                res["flaws"].append("Нет безопасного HTTPS-протокола (браузеры пишут 'Не защищено')")
                res["summary_badges"].append("🔒 НЕТ SSL")

            # 5. Check speed
            if elapsed > 3000:
                res["flaws"].append(f"Медленный отклик ({elapsed/1000:.1f} сек)")
                res["summary_badges"].append(f"⚡ Медленный ({elapsed/1000:.1f}с)")

    except Exception as e:
        res["reachable"] = False
        res["flaws"].append(f"Сайт недоступен или ошибка загрузки: {str(e)[:50]}")
        res["summary_badges"].append("❌ ОШИБКА САЙТА")

    return res


async def audit_lead_website(lead: Lead) -> Lead:
    """Asynchronously audits lead website and boosts priority if high-ticket redesign flaws detected."""
    if not lead.website:
        return lead

    # Sanity check: do not audit search engines, map links, taplinks, social media or booking widgets
    w_lower = str(lead.website).lower().strip()
    if any(pat in w_lower for pat in ["yandex.", "ya.ru", "ya.by", "google.", "2gis.", "apple.", "maps/org", "clck/"]):
        lead.website = None
        lead.website_status = WebsiteStatus.NO_WEBSITE
        lead.lead_priority = LeadPriority.HIGH
        lead.site_audit_summary = ""
        return lead

    if lead.website_status in (WebsiteStatus.NO_WEBSITE, WebsiteStatus.SOCIAL, WebsiteStatus.TAPLINK):
        return lead

    loop = asyncio.get_event_loop()
    audit = await loop.run_in_executor(None, audit_website_sync, lead.website)

    badges = audit.get("summary_badges", [])
    unreachable = not audit.get("reachable", True)

    if unreachable:
        lead.website_status = WebsiteStatus.NO_WEBSITE
        lead.lead_priority = LeadPriority.HIGH
        lead.site_audit_summary = "❌ САЙТ НЕ ОТКРЫВАЕТСЯ"
        lead.notes = (lead.notes or "") + " [Сайт из карточки не открывается - критическая потеря клиентов]"
        lead.pain_points.append("Сайт из карточки на картах не открывается")
        return lead

    if badges:
        lead.site_audit_summary = " | ".join(badges)

    # Opportunity scoring:
    has_no_mobile = not audit.get("has_mobile_viewport", True)
    paying_ads = bool(audit.get("detected_ad_pixels"))

    if has_no_mobile and paying_ads:
        lead.lead_priority = LeadPriority.HIGH
        lead.notes = (lead.notes or "") + " [🔥 КРУТЯТ РЕКЛАМУ БЕЗ МОБИЛЬНОЙ ВЕРСИИ! Сливают бюджет]"
        lead.pain_points.append("Сайт рекламируется, но не адаптирован под телефоны")

    elif has_no_mobile:
        lead.lead_priority = LeadPriority.HIGH
        lead.notes = (lead.notes or "") + " [НЕТ мобильной версии сайта]"
        lead.pain_points.append("Нет мобильной адаптации")

    elif paying_ads:
        lead.lead_priority = LeadPriority.MEDIUM
        lead.notes = (lead.notes or "") + f" [Платят за рекламу: {', '.join(audit['detected_ad_pixels'])}]"

    return lead
