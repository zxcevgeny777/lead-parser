"""Persistent memory and history tracking for scraped organizations."""
import json
import logging
import os
import re
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any, Set

from core.models import Lead, LeadPriority, WebsiteStatus

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "leads_memory.db"
)


class LeadsMemory:
    """Manages persistent SQLite storage of all checked businesses to prevent duplicate scraping."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=20.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes database tables and indexes."""
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS checked_places (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    org_id TEXT UNIQUE,
                    map_url TEXT,
                    source TEXT,
                    name TEXT,
                    city TEXT,
                    category TEXT,
                    address TEXT,
                    phones TEXT,
                    primary_phone TEXT,
                    website TEXT,
                    website_status TEXT,
                    lead_priority TEXT,
                    created_at TEXT,
                    last_checked_at TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_checked_org_id ON checked_places(org_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_checked_map_url ON checked_places(map_url)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_checked_primary_phone ON checked_places(primary_phone)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_checked_name_city ON checked_places(name, city)")
            conn.commit()

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """Extracts plain digits from phone string for index lookups."""
        if not phone:
            return ""
        digits = re.sub(r"\D", "", phone)
        if len(digits) == 11 and digits[0] in ("7", "8"):
            return digits[1:]
        return digits

    def is_checked(
        self,
        url: Optional[str] = None,
        org_id: Optional[str] = None,
        phone: Optional[str] = None,
        name: Optional[str] = None,
        city: Optional[str] = None,
        map_url: Optional[str] = None,
    ) -> bool:
        """Checks if a business was already scraped previously."""
        target_url = url or map_url
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if org_id:
                cursor.execute("SELECT 1 FROM checked_places WHERE org_id = ? LIMIT 1", (org_id,))
                if cursor.fetchone():
                    return True

            if target_url:
                cursor.execute("SELECT 1 FROM checked_places WHERE map_url = ? OR org_id = ? LIMIT 1", (target_url, target_url))
                if cursor.fetchone():
                    return True

            if phone:
                norm_p = self._normalize_phone(phone)
                if norm_p:
                    cursor.execute("SELECT 1 FROM checked_places WHERE primary_phone = ? LIMIT 1", (norm_p,))
                    if cursor.fetchone():
                        return True

            if name and city:
                cursor.execute(
                    "SELECT 1 FROM checked_places WHERE LOWER(name) = LOWER(?) AND LOWER(city) = LOWER(?) LIMIT 1",
                    (name.strip(), city.strip()),
                )
                if cursor.fetchone():
                    return True

        return False

    def load_cached_lookups(self) -> Dict[str, Set[str]]:
        """Loads sets of checked URLs, org_ids, and phones into RAM for O(1) in-memory checks."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT org_id, map_url, primary_phone, name, city FROM checked_places")
            rows = cursor.fetchall()

        urls: Set[str] = set()
        phones: Set[str] = set()
        name_city: Set[str] = set()

        for r in rows:
            if r["org_id"]:
                urls.add(r["org_id"])
            if r["map_url"]:
                urls.add(r["map_url"])
            if r["primary_phone"]:
                phones.add(r["primary_phone"])
            if r["name"] and r["city"]:
                name_city.add(f"{r['name'].strip().lower()}_{r['city'].strip().lower()}")

        return {
            "urls": urls,
            "phones": phones,
            "name_city": name_city,
        }

    def save_lead(self, lead: Lead):
        """Saves or updates a single lead in memory."""
        self.save_leads([lead])

    def save_leads(self, leads: List[Lead]):
        """Batch saves leads in a single fast transaction."""
        if not leads:
            return

        now = datetime.now().isoformat()
        records = []

        for l in leads:
            org_id = l.id or l.map_url
            if not org_id:
                continue

            phones_json = json.dumps(l.phones, ensure_ascii=False)
            norm_phone = self._normalize_phone(l.primary_phone)

            status_val = l.website_status.value if hasattr(l.website_status, "value") else str(l.website_status)
            priority_val = l.lead_priority.value if hasattr(l.lead_priority, "value") else str(l.lead_priority)

            records.append((
                org_id,
                l.map_url or org_id,
                l.source,
                l.name,
                l.city,
                l.category,
                l.address,
                phones_json,
                norm_phone,
                l.website,
                status_val,
                priority_val,
                now,
                now,
            ))

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO checked_places (
                    org_id, map_url, source, name, city, category, address,
                    phones, primary_phone, website, website_status, lead_priority,
                    created_at, last_checked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(org_id) DO UPDATE SET
                    map_url=excluded.map_url,
                    source=excluded.source,
                    name=excluded.name,
                    city=excluded.city,
                    category=excluded.category,
                    address=excluded.address,
                    phones=excluded.phones,
                    primary_phone=excluded.primary_phone,
                    website=excluded.website,
                    website_status=excluded.website_status,
                    lead_priority=excluded.lead_priority,
                    last_checked_at=excluded.last_checked_at
            """, records)
            conn.commit()

        logger.debug(f"[LeadsMemory] Saved/updated {len(records)} places in memory.")

    def get_stats(self) -> Dict[str, Any]:
        """Returns summary statistics of remembered places."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM checked_places")
            total = cursor.fetchone()["cnt"]

            cursor.execute("SELECT COUNT(*) as cnt FROM checked_places WHERE lead_priority LIKE '%Высокий%' OR website IS NULL OR website = ''")
            hot_count = cursor.fetchone()["cnt"]

            cursor.execute("SELECT COUNT(*) as cnt FROM checked_places WHERE lead_priority LIKE '%Средний%'")
            med_count = cursor.fetchone()["cnt"]

            cursor.execute("SELECT COUNT(*) as cnt FROM checked_places WHERE website IS NOT NULL AND website != '' AND lead_priority LIKE '%Низкий%'")
            has_website = cursor.fetchone()["cnt"]

            cursor.execute("SELECT city, COUNT(*) as cnt FROM checked_places WHERE city != '' GROUP BY city ORDER BY cnt DESC LIMIT 5")
            top_cities = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT source, COUNT(*) as cnt FROM checked_places GROUP BY source")
            sources = [dict(r) for r in cursor.fetchall()]

        return {
            "total_checked": total,
            "hot_leads": hot_count,
            "medium_leads": med_count,
            "has_website": has_website,
            "top_cities": top_cities,
            "sources": sources,
        }

    def clear_memory(self) -> int:
        """Clears all stored memory and returns number of rows deleted."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM checked_places")
            total = cursor.fetchone()["cnt"]
            cursor.execute("DELETE FROM checked_places")
            conn.commit()
            cursor.execute("VACUUM")
            conn.commit()
        return total


# Global singleton instance
memory_db = LeadsMemory()
