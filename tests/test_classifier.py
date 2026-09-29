"""Unit tests for lead classification, scoring, and data models."""
from core.models import Lead, WebsiteStatus, LeadPriority, classify_website, format_phone


def test_classify_no_website():
    status, priority = classify_website(None)
    assert status == WebsiteStatus.NO_WEBSITE
    assert priority == LeadPriority.HIGH

    status, priority = classify_website("")
    assert status == WebsiteStatus.NO_WEBSITE
    assert priority == LeadPriority.HIGH

    status, priority = classify_website("-")
    assert status == WebsiteStatus.NO_WEBSITE
    assert priority == LeadPriority.HIGH


def test_classify_taplink():
    status, priority = classify_website("https://taplink.cc/beautysalon")
    assert status == WebsiteStatus.TAPLINK
    assert priority == LeadPriority.MEDIUM

    status, priority = classify_website("linktr.ee/coolstore")
    assert status == WebsiteStatus.TAPLINK
    assert priority == LeadPriority.MEDIUM


def test_classify_social():
    status, priority = classify_website("https://vk.com/autoservice_msk")
    assert status == WebsiteStatus.SOCIAL
    assert priority == LeadPriority.MEDIUM

    status, priority = classify_website("https://t.me/remont_kvartir")
    assert status == WebsiteStatus.SOCIAL
    assert priority == LeadPriority.MEDIUM

    status, priority = classify_website("https://instagram.com/nail_studio")
    assert status == WebsiteStatus.SOCIAL
    assert priority == LeadPriority.MEDIUM


def test_classify_builder():
    status, priority = classify_website("https://mysite.tilda.ws")
    assert status == WebsiteStatus.BUILDER
    assert priority == LeadPriority.MEDIUM

    status, priority = classify_website("https://test.wixsite.com/site")
    assert status == WebsiteStatus.BUILDER
    assert priority == LeadPriority.MEDIUM


def test_classify_regular_website():
    status, priority = classify_website("https://avtoservis-expert.ru")
    assert status == WebsiteStatus.HAS_WEBSITE
    assert priority == LeadPriority.LOW

    status, priority = classify_website("www.dentistry-moscow.com")
    assert status == WebsiteStatus.HAS_WEBSITE
    assert priority == LeadPriority.LOW


def test_format_phone():
    assert format_phone("89991112233") == "+7 (999) 111-22-33"
    assert format_phone("+7 (999) 111-22-33") == "+7 (999) 111-22-33"
    assert format_phone("74951234567") == "+7 (495) 123-45-67"


def test_lead_model():
    lead = Lead(
        name="ООО Автомастер",
        source="2ГИС",
        category="Автосервис",
        city="Москва",
        address="ул. Тверская, 1",
        phones=["89260001122"],
        website=None,
    )
    assert lead.lead_priority == LeadPriority.HIGH
    assert lead.website_status == WebsiteStatus.NO_WEBSITE
    assert lead.primary_phone == "+7 (926) 000-11-22"
