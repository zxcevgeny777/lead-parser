import pytest
from core.models import Lead, WebsiteStatus, LeadPriority, classify_website
from core.web_verifier import is_aggregator_domain, verify_company_website_sync
from core.ai_pitcher import generate_algorithmic_pitch

def test_search_and_map_domains_classified_as_no_website():
    status, priority = classify_website("https://yandex.by")
    assert status == WebsiteStatus.NO_WEBSITE
    assert priority == LeadPriority.HIGH

    status, priority = classify_website("https://yandex.ru/maps/org/123")
    assert status == WebsiteStatus.NO_WEBSITE
    assert priority == LeadPriority.HIGH

    status, priority = classify_website("https://google.com/maps/place/123")
    assert status == WebsiteStatus.NO_WEBSITE
    assert priority == LeadPriority.HIGH


def test_booking_and_catalog_domains_classified_as_taplink():
    status, priority = classify_website("https://dikidi.net/123")
    assert status == WebsiteStatus.TAPLINK
    assert priority == LeadPriority.MEDIUM

    status, priority = classify_website("https://yclients.com/b123")
    assert status == WebsiteStatus.TAPLINK
    assert priority == LeadPriority.MEDIUM

    status, priority = classify_website("https://minsk.ouuo.ru/firm/123")
    assert status == WebsiteStatus.TAPLINK
    assert priority == LeadPriority.MEDIUM


def test_lead_sanitizes_map_and_search_urls():
    lead = Lead(
        id="1",
        name="Тахмина Колос",
        source="Яндекс Карты",
        website="https://yandex.by",
    )
    assert lead.website is None
    assert lead.website_status == WebsiteStatus.NO_WEBSITE
    assert lead.lead_priority == LeadPriority.HIGH


def test_aggregator_filtering():
    assert is_aggregator_domain("https://yandex.by/maps/org/123") is True
    assert is_aggregator_domain("dikidi.net") is True
    assert is_aggregator_domain("ouuo.ru") is True
    assert is_aggregator_domain("buk.by") is True
    assert is_aggregator_domain("charodey.com") is False


def test_ai_pitcher_for_booking_services():
    lead = Lead(
        id="2",
        name="Women's Room 2.0",
        source="Яндекс Карты",
        category="Салон красоты",
        city="Минск",
        website="https://dikidi.net/12345",
        website_status=WebsiteStatus.TAPLINK,
    )
    msg, call = generate_algorithmic_pitch(lead)
    assert "DIKIDI" in msg
    assert "онлайн-запись" in msg
    assert "https://dikidi.net" not in msg
    assert "Изучил ваш сайт https://dikidi.net" not in msg


def test_unwrap_noisy_button_text_and_redirects():
    from core.models import unwrap_and_clean_url

    assert unwrap_and_clean_url("stroyka.by ↗") == "https://stroyka.by"
    assert unwrap_and_clean_url("Перейти на сайт auto-service.ru") == "https://auto-service.ru"
    assert unwrap_and_clean_url("https://link.2gis.ru/abc12345") is None
    assert unwrap_and_clean_url("https://2gis.by/redirect/https://belstroy.by/catalog") == "https://belstroy.by/catalog"


def test_twogis_shortlink_falls_back_to_text_domain():
    from scrapers.twogis import TwoGisScraper

    scraper = TwoGisScraper(headless=True)
    item = {
        "id": "70000001055555555",
        "name": "СтройМастер Плюс",
        "address_name": "ул. Притыцкого, 29",
        "contact_groups": [
            {
                "contacts": [
                    {"type": "phone", "value": "+375291112233"},
                    {
                        "type": "website",
                        "url": "https://link.2gis.ru/987654321",
                        "text": "stroymaster.by",
                        "value": "http://link.2gis.ru/987654321",
                    },
                ]
            }
        ],
    }
    lead = scraper._parse_api_item(item, default_city="Минск")
    assert lead is not None
    assert lead.website == "https://stroymaster.by"
    assert lead.website_status == WebsiteStatus.HAS_WEBSITE
    assert lead.lead_priority == LeadPriority.LOW
    scraper.filter_type = "hot_only"
    assert scraper._is_qualifying(lead) is False
    scraper.filter_type = "hot_warm"
    assert scraper._is_qualifying(lead) is False


def test_expanded_niches_catalog():
    from core.niches import POPULAR_NICHES, QUICK_NICHES, QUICK_INTL_NICHES, clean_map_query

    assert len(POPULAR_NICHES) >= 75
    assert len(QUICK_NICHES) >= 12
    assert len(QUICK_INTL_NICHES) >= 12

    # Verify query cleaner simplifies compound niche strings for map search engines
    assert clean_map_query("Монтаж септиков и канализации Минск") == "Септики Минск"
    assert clean_map_query("Строительство каркасных домов Гомель") == "Каркасные дома Гомель"
    assert clean_map_query("Выездной шиномонтаж 24/7 Минск") == "Выездной шиномонтаж Минск"


def test_yandex_org_id_extraction_and_lead_strictness():
    from scrapers.yandex import extract_yandex_org_id
    from core.models import Lead, WebsiteStatus, LeadPriority

    # Canonical and slugged Yandex map URLs
    assert extract_yandex_org_id("https://yandex.ru/maps/org/1234567890/") == "1234567890"
    assert extract_yandex_org_id("/maps/org/shinomontazh_24/9876543210/") == "9876543210"
    assert extract_yandex_org_id("1122334455") == "1122334455"

    # Lead strict classification invariant: lead with website cannot be NO_WEBSITE or HIGH priority
    lead_with_site = Lead(
        name="Компания с сайтом",
        source="yandex",
        website="https://stroyservis.by",
        phones=["+375291234567"],
    )
    assert lead_with_site.website_status == WebsiteStatus.HAS_WEBSITE
    assert lead_with_site.lead_priority == LeadPriority.LOW



