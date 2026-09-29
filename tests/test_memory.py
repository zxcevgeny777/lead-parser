"""Unit tests for LeadsMemory SQLite persistence and deduplication."""
import os
import tempfile
from core.models import Lead, WebsiteStatus, LeadPriority
from core.memory import LeadsMemory


def test_memory_crud_and_lookups():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        mem = LeadsMemory(db_path=db_path)

        # 1. Initial state
        stats = mem.get_stats()
        assert stats["total_checked"] == 0

        # 2. Add lead
        lead1 = Lead(
            id="https://yandex.ru/maps/org/test_org/123456/",
            name="Тестовый Автосервис",
            source="Яндекс Карты",
            city="Москва",
            address="ул. Ленина, 10",
            phones=["+7 (999) 111-22-33"],
            website=None,
        )
        mem.save_lead(lead1)

        # Check stats
        stats = mem.get_stats()
        assert stats["total_checked"] == 1
        assert stats["hot_leads"] == 1

        # 3. Check lookups
        assert mem.is_checked(url="https://yandex.ru/maps/org/test_org/123456/")
        assert mem.is_checked(org_id="https://yandex.ru/maps/org/test_org/123456/")
        assert mem.is_checked(phone="+7 999 111-22-33")
        assert mem.is_checked(name="Тестовый Автосервис", city="Москва")
        assert not mem.is_checked(url="https://yandex.ru/maps/org/another/999999/")
        assert not mem.is_checked(phone="+7 999 000-00-00")

        # 4. Cached lookups
        cache = mem.load_cached_lookups()
        assert "https://yandex.ru/maps/org/test_org/123456/" in cache["urls"]
        assert "9991112233" in cache["phones"]
        assert "тестовый автосервис_москва" in cache["name_city"]

        # 5. Batch save with conflict update
        lead2 = Lead(
            id="https://yandex.ru/maps/org/test_clinic/654321/",
            name="Стоматология Улыбка",
            source="Яндекс Карты",
            city="Москва",
            phones=["8 (916) 555-44-33"],
            website="https://smiledental.ru",
        )
        mem.save_leads([lead1, lead2])

        stats = mem.get_stats()
        assert stats["total_checked"] == 2
        assert stats["has_website"] == 1

        # 6. Clear memory
        deleted = mem.clear_memory()
        assert deleted == 2
        stats_after = mem.get_stats()
        assert stats_after["total_checked"] == 0

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
