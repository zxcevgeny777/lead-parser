"""Telegram Notification and Settings Manager.

Sends instant alerts for new freelance orders and leads to Telegram channels or private chats.
Manages persistent user settings in settings.json.
"""
import json
import os
import urllib.parse
import urllib.request
from typing import Dict, Any, Optional, Tuple

SETTINGS_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "settings.json"))

DEFAULT_SETTINGS = {
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "gemini_api_key": "",
    "auto_monitor_enabled": False,
    "monitor_interval_minutes": 3,
    "notify_onliner": True,
    "notify_kwork": True,
    "notify_fl": True,
}


def load_settings() -> Dict[str, Any]:
    """Loads configuration settings from disk."""
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Merge with defaults
            merged = DEFAULT_SETTINGS.copy()
            merged.update(data)
            return merged
    except Exception:
        return DEFAULT_SETTINGS.copy()


def save_settings(settings: Dict[str, Any]) -> bool:
    """Saves configuration settings to disk."""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def send_telegram_alert(message: str, bot_token: Optional[str] = None, chat_id: Optional[str] = None) -> Tuple[bool, str]:
    """Sends an instant message via Telegram Bot API with HTML formatting."""
    cfg = load_settings()
    token = (bot_token or cfg.get("telegram_bot_token") or "").strip()
    cid = (chat_id or cfg.get("telegram_chat_id") or "").strip()

    if not token or not cid:
        return False, "Не указан Telegram Bot Token или Chat ID в настройках"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": cid,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            if res_data.get("ok"):
                return True, "Успешно отправлено"
            return False, str(res_data.get("description", "Ошибка отправки"))
    except Exception as e:
        return False, f"Ошибка сети Telegram: {e}"
