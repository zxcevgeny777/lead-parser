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
