"""Unit tests for Lead Parser upgrade features (Belarus localization, site audit, AI pitch, telegram notifier)."""
import pytest
from core.models import Lead, LeadPriority, WebsiteStatus, parse_and_format_phone
from core.web_verifier import is_aggregator_domain, verify_company_website_sync
from core.site_auditor import parse_html_audit_signals
from core.ai_pitcher import generate_algorithmic_pitch, enrich_lead_with_pitch
from core.notifier import load_settings, save_settings, SETTINGS_FILE
from scrapers.freelance.watcher import FreelanceWatcher


def test_belarus_phone_parsing():
    # 8029... format
    fmt, is_mob, clean = parse_and_format_phone("80291234567")
    assert clean == "375291234567"
    assert fmt == "+375 (29) 123-45-67"
    assert is_mob is True

    # +375 44... format
    fmt, is_mob, clean = parse_and_format_phone("+375 (44) 765-43-21")
    assert clean == "375447654321"
    assert fmt == "+375 (44) 765-43-21"
    assert is_mob is True

    # 033... format (without country code)
    fmt, is_mob, clean = parse_and_format_phone("033 999 88 77")
    assert clean == "375339998877"
    assert fmt == "+375 (33) 999-88-77"
    assert is_mob is True

    # Landline Minsk (17)
    fmt, is_mob, clean = parse_and_format_phone("+375 (17) 200-11-22")
    assert clean == "375172001122"
    assert fmt == "+375 (17) 200-11-22"
    assert is_mob is False

    # Russian mobile
    fmt, is_mob, clean = parse_and_format_phone("89161234567")
    assert clean == "79161234567"
    assert fmt == "+7 (916) 123-45-67"
    assert is_mob is True


def test_lead_model_links_and_badges():
    lead_mob = Lead(
        name="ООО Минск Авто",
        source="Яндекс Карты",
        category="Автосервис",
        city="Минск",
        address="пр-т Победителей, 10",
        phones=["80295554433"],
        website=None,
    )
    assert lead_mob.is_mobile is True
    assert lead_mob.phone_type_badge == "📱 Моб."
    assert "wa.me/375295554433" in lead_mob.whatsapp_url
    assert "t.me/+375295554433" in lead_mob.telegram_url
    assert "viber://" in lead_mob.viber_url and "375295554433" in lead_mob.viber_url

    lead_landline = Lead(
        name="Офис Сервис",
        source="2ГИС",
        category="Юрист",
        city="Минск",
        address="ул. Ленина, 5",
        phones=["+375 17 210-00-00"],
        website=None,
    )
    assert lead_landline.is_mobile is False
    assert lead_landline.phone_type_badge == "☎️ Гор."
    assert lead_landline.whatsapp_url is None
    assert lead_landline.telegram_url is None
    assert lead_landline.viber_url is None


def test_belarus_aggregators():
    assert is_aggregator_domain("https://s.onliner.by/tasks/123") is True
    assert is_aggregator_domain("https://kufar.by/item/123") is True
    assert is_aggregator_domain("https://tam.by/autoservice") is True
    assert is_aggregator_domain("https://relax.by/minsk/places") is True
    assert is_aggregator_domain("https://103.by/doctors") is True

    # Real business site should not be aggregator
    assert is_aggregator_domain("https://minsk-autoremont.by") is False
    assert is_aggregator_domain("https://stroy-minsk.com") is False


def test_site_auditor_signals():
    html_with_pixels = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script>
            (function(m,e,t,r,i,k,a){m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};
            ym(123456, "init", {});
        </script>
        <script>
            fbq('init', '987654321');
        </script>
    </head>
    <body>
        <h1>Компания</h1>
    </body>
    </html>
    """
    signals = parse_html_audit_signals(html_with_pixels)
    assert signals["has_mobile_viewport"] is True
    assert "Яндекс.Метрика / Директ" in signals["detected_ad_pixels"]
    assert "Meta / FB Pixel" in signals["detected_ad_pixels"]
    assert "💰 КРУТЯТ РЕКЛАМУ" in signals["summary_badges"]

    html_broken_mobile = "<html><head><title>Old Site</title></head><body>No mobile</body></html>"
    signals_broken = parse_html_audit_signals(html_broken_mobile)
    assert signals_broken["has_mobile_viewport"] is False
    assert len(signals_broken["detected_ad_pixels"]) == 0
    assert "📱 НЕТ МОБИЛКИ!" in signals_broken["summary_badges"]


def test_ai_pitcher():
    lead = Lead(
        name="Автосервис Восток",
        source="2ГИС",
        category="Автосервис",
        city="Минск",
        phones=["80291112233"],
        website=None,
    )
    enrich_lead_with_pitch(lead)
    assert lead.ai_pitch != ""
    assert lead.call_script != ""
    assert "Автосервис Восток" in lead.ai_pitch or "Автосервис" in lead.ai_pitch
    assert "30 секунд" in lead.call_script or "Здравствуйте" in lead.call_script


def test_freelance_watcher_instance():
    watcher = FreelanceWatcher()
    assert watcher.is_running is False
    assert watcher.orders_found_count == 0
