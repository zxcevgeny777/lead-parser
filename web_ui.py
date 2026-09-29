"""Local web dashboard for Yandex Maps, 2GIS, and Freelance Exchanges Lead Scraper.
Runs an HTTP server with REST endpoints and a modern responsive browser interface.
"""
import asyncio
import json
import os
import re
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import threading
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from typing import List, Dict, Any, Optional

from core.models import Lead, LeadPriority, WebsiteStatus, FreelanceOrder
from core.exporter import export_to_excel, export_to_csv, export_freelance_to_excel, export_freelance_to_csv
from core.niches import (
    POPULAR_NICHES, QUICK_NICHES,
    US_EU_HIGH_TICKET_NICHES, QUICK_INTL_NICHES, INTL_CITIES, BY_CITIES
)
from core.memory import memory_db
from core.web_verifier import verify_company_website
from core.site_auditor import audit_lead_website
from core.ai_pitcher import enrich_lead_with_pitch
from core.notifier import load_settings, save_settings, send_telegram_alert
from scrapers.twogis import TwoGisScraper
from scrapers.yandex import YandexScraper
from scrapers.google import GoogleMapsScraper
from scrapers.freelance import FreelanceAggregator, freelance_watcher

# Global state for Maps Lead Search
CURRENT_STATE = {
    "is_running": False,
    "progress_message": "Готов к работе",
    "total_target": 0,
    "leads": [],
    "last_excel_path": None,
    "last_csv_path": None,
    "skipped_count": 0,
    "memory_stats": memory_db.get_stats(),
}

# Global state for Freelance Exchanges Search
FREELANCE_STATE = {
    "is_running": False,
    "progress_message": "Готов к поиску заказов",
    "total_target": 0,
    "orders": [],
    "last_excel_path": None,
    "last_csv_path": None,
}

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Лид-Парсер | Поиск клиентов и заказов на разработку сайтов</title>
    <style>
        :root, [data-theme="dark"] {
            --bg: #0f172a;
            --surface: #1e293b;
            --surface-hover: #334155;
            --primary: #3b82f6;
            --primary-hover: #2563eb;
            --success: #10b981;
            --warning: #f59e0b;
            --text: #f8fafc;
            --text-dim: #94a3b8;
            --border: #334155;
            --input-bg: #0f172a;
            --header-gradient: linear-gradient(90deg, #60a5fa, #a855f7);
        }
        [data-theme="midnight"] {
            --bg: #080c14;
            --surface: #0f172a;
            --surface-hover: #1e293b;
            --primary: #6366f1;
            --primary-hover: #4f46e5;
            --success: #10b981;
            --warning: #f59e0b;
            --text: #f1f5f9;
            --text-dim: #94a3b8;
            --border: #1e293b;
            --input-bg: #080c14;
            --header-gradient: linear-gradient(90deg, #818cf8, #c084fc);
        }
        [data-theme="emerald"] {
            --bg: #04130d;
            --surface: #09261a;
            --surface-hover: #0f3827;
            --primary: #10b981;
            --primary-hover: #059669;
            --success: #34d399;
            --warning: #f59e0b;
            --text: #ecfdf5;
            --text-dim: #6ee7b7;
            --border: #134e35;
            --input-bg: #04130d;
            --header-gradient: linear-gradient(90deg, #34d399, #10b981);
        }
        [data-theme="cyberpunk"] {
            --bg: #11071f;
            --surface: #1f0d36;
            --surface-hover: #301654;
            --primary: #d946ef;
            --primary-hover: #c026d3;
            --success: #06b6d4;
            --warning: #facc15;
            --text: #fdf4ff;
            --text-dim: #d8b4fe;
            --border: #441b77;
            --input-bg: #11071f;
            --header-gradient: linear-gradient(90deg, #f43f5e, #d946ef, #06b6d4);
        }
        [data-theme="light"] {
            --bg: #f1f5f9;
            --surface: #ffffff;
            --surface-hover: #f8fafc;
            --primary: #2563eb;
            --primary-hover: #1d4ed8;
            --success: #059669;
            --warning: #d97706;
            --text: #0f172a;
            --text-dim: #64748b;
            --border: #cbd5e1;
            --input-bg: #ffffff;
            --header-gradient: linear-gradient(90deg, #2563eb, #7c3aed);
        }

        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: var(--bg); color: var(--text); padding: 24px; min-height: 100vh; transition: background 0.25s, color 0.25s; }
        .container { max-width: 1400px; margin: 0 auto; }
        header { margin-bottom: 20px; }
        header h1 { font-size: 26px; font-weight: 800; background: var(--header-gradient); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        header p { color: var(--text-dim); margin-top: 6px; font-size: 14px; }

        /* Top Navigation Tabs */
        .tabs-nav {
            display: flex;
            gap: 10px;
            margin-bottom: 22px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 12px;
            flex-wrap: wrap;
        }
        .tab-btn {
            background: var(--surface);
            color: var(--text-dim);
            border: 1px solid var(--border);
            padding: 11px 22px;
            border-radius: 10px;
            font-size: 14px;
            font-weight: 700;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: all 0.2s;
        }
        .tab-btn:hover {
            background: var(--surface-hover);
            color: var(--text);
            transform: translateY(-1px);
        }
        .tab-btn.active {
            background: var(--primary);
            color: white;
            border-color: var(--primary);
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.35);
        }
        .tab-badge {
            background: rgba(255, 255, 255, 0.22);
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: 800;
        }

        .tab-content { display: none; }
        .tab-content.active { display: block; }

        .card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 22px; margin-bottom: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2); transition: background 0.25s, border-color 0.25s; }
        .grid-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px; align-items: end; }
        
        label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 6px; color: var(--text-dim); }
        input, select { width: 100%; padding: 10px 14px; background: var(--input-bg); border: 1px solid var(--border); border-radius: 8px; color: var(--text); font-size: 14px; outline: none; transition: border-color 0.2s, background 0.2s; }
        input:focus, select:focus { border-color: var(--primary); }

        .btn { padding: 10px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; border: none; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 7px; transition: all 0.2s; text-decoration: none; }
        .btn-primary { background: var(--primary); color: white; width: 100%; }
        .btn-primary:hover { background: var(--primary-hover); }
        .btn-success { background: var(--success); color: white; }
        .btn-success:hover { filter: brightness(1.1); }
        .btn-secondary { background: var(--surface-hover); color: var(--text); border: 1px solid var(--border); }
        .btn-secondary:hover { filter: brightness(1.15); }

        .stats-bar { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 20px; }
        .stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; text-align: center; }
        .stat-val { font-size: 24px; font-weight: 800; margin-top: 4px; }
        .stat-label { font-size: 12px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; }

        .progress-box { margin-bottom: 20px; display: none; }
        .progress-box.active { display: block; }
        .progress-bar-bg { width: 100%; height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; margin-top: 8px; }
        .progress-bar-fill { height: 100%; width: 0%; background: linear-gradient(90deg, var(--primary), var(--success)); transition: width 0.3s; }

        .table-wrap { overflow-x: auto; max-height: 620px; border: 1px solid var(--border); border-radius: 8px; }
        table { width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }
        th { background: var(--bg); padding: 12px 14px; font-weight: 600; color: var(--text-dim); position: sticky; top: 0; z-index: 10; border-bottom: 1px solid var(--border); }
        td { padding: 10px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }
        tr:hover { background: rgba(255,255,255,0.03); }

        .badge { display: inline-block; padding: 4px 9px; border-radius: 6px; font-size: 11px; font-weight: 700; white-space: nowrap; }
        .badge-high { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.35); }
        .badge-med { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.35); }
        .badge-low { background: rgba(148, 163, 184, 0.15); color: var(--text-dim); border: 1px solid var(--border); }

        /* Platform Badges */
        .badge-onliner { background: rgba(234, 179, 8, 0.18); color: #facc15; border: 1px solid rgba(234, 179, 8, 0.4); }
        .badge-kufar { background: rgba(20, 184, 166, 0.18); color: #2dd4bf; border: 1px solid rgba(20, 184, 166, 0.4); }
        .badge-tg { background: rgba(56, 189, 248, 0.18); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4); }
        .badge-kwork { background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.35); }
        .badge-fl { background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.35); }
        .badge-fh { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.35); }
        .badge-wl { background: rgba(249, 115, 22, 0.15); color: #fb923c; border: 1px solid rgba(249, 115, 22, 0.35); }
        .badge-price { background: rgba(34, 197, 94, 0.18); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.4); font-size: 12px; font-weight: 800; }
        
        .chip {
            background: var(--input-bg);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 4px 10px;
            border-radius: 16px;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
            user-select: none;
        }
        .chip:hover {
            background: var(--primary);
            border-color: var(--primary);
            color: white;
            transform: translateY(-1px);
        }
        .chip-city {
            font-size: 11px;
            padding: 3px 8px;
            border-radius: 6px;
        }

        .badge-google { background: rgba(66, 133, 244, 0.2); color: #60a5fa; border: 1px solid rgba(66, 133, 244, 0.45); font-weight: 700; }
        
        .region-toggle-wrap {
            display: flex;
            gap: 12px;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }
        .region-toggle-btn {
            flex: 1;
            min-width: 250px;
            padding: 12px 18px;
            border-radius: 10px;
            border: 2px solid var(--border);
            background: var(--surface);
            color: var(--text-dim);
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 12px;
            text-align: left;
        }
        .region-toggle-btn:hover {
            border-color: var(--surface-hover);
            filter: brightness(1.1);
        }
        .region-toggle-btn.active-us {
            border-color: #38bdf8;
            background: rgba(56, 189, 248, 0.12);
            color: #38bdf8;
            box-shadow: 0 0 15px rgba(56, 189, 248, 0.2);
        }
        .region-toggle-btn.active-cis {
            border-color: #10b981;
            background: rgba(16, 185, 129, 0.12);
            color: #10b981;
            box-shadow: 0 0 15px rgba(16, 185, 129, 0.2);
        }

        /* Clickable organization link */
        a.org-link {
            color: var(--text);
            text-decoration: none;
            font-weight: 700;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            transition: color 0.15s;
        }
        a.org-link:hover {
            color: var(--primary);
            text-decoration: underline;
        }
        a.org-link .link-icon {
            font-size: 11px;
            opacity: 0.6;
            color: var(--primary);
        }

        a.tel-link { color: #38bdf8; text-decoration: none; font-weight: 600; white-space: nowrap; }
        a.tel-link:hover { text-decoration: underline; }
        a.site-link { color: #818cf8; text-decoration: none; max-width: 170px; display: inline-block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        a.site-link:hover { text-decoration: underline; }

        /* Row action buttons */
        .actions-cell {
            display: flex;
            gap: 5px;
            align-items: center;
            white-space: nowrap;
        }
        .btn-act {
            padding: 5px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            text-decoration: none;
            cursor: pointer;
            border: 1px solid var(--border);
            background: var(--surface-hover);
            color: var(--text);
            display: inline-flex;
            align-items: center;
            gap: 3px;
            transition: all 0.15s;
        }
        .btn-act:hover {
            filter: brightness(1.2);
            transform: translateY(-1px);
        }
        .btn-act-vb { background: rgba(147, 51, 234, 0.18); border-color: rgba(147, 51, 234, 0.45); color: #c084fc; font-weight: 700; }
        .btn-act-wa { background: rgba(37, 211, 102, 0.15); border-color: rgba(37, 211, 102, 0.4); color: #25d366; }
        .btn-act-tg { background: rgba(56, 189, 248, 0.15); border-color: rgba(56, 189, 248, 0.4); color: #38bdf8; }
        .btn-act-map { background: rgba(245, 158, 11, 0.15); border-color: rgba(245, 158, 11, 0.4); color: #f59e0b; }
        .btn-act-proj { background: rgba(59, 130, 246, 0.15); border-color: rgba(59, 130, 246, 0.4); color: #60a5fa; font-weight: 700; }
        .btn-act-pitch {
            background: linear-gradient(135deg, rgba(168, 85, 247, 0.22), rgba(59, 130, 246, 0.22));
            border-color: rgba(168, 85, 247, 0.5);
            color: #c084fc;
            font-weight: 700;
        }
        .badge-mob {
            background: rgba(16, 185, 129, 0.18);
            color: #34d399;
            border: 1px solid rgba(16, 185, 129, 0.4);
            border-radius: 4px;
            padding: 2px 5px;
            font-size: 11px;
            font-weight: 700;
            display: inline-block;
            margin-right: 4px;
        }
        .badge-land {
            background: rgba(148, 163, 184, 0.15);
            color: #94a3b8;
            border: 1px solid rgba(148, 163, 184, 0.3);
            border-radius: 4px;
            padding: 2px 5px;
            font-size: 11px;
            font-weight: 600;
            display: inline-block;
            margin-right: 4px;
        }
        .audit-tag {
            display: inline-block;
            font-size: 10px;
            font-weight: 800;
            padding: 2px 6px;
            border-radius: 4px;
            margin-top: 3px;
            margin-right: 3px;
        }
        .audit-no-mobile { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }
        .audit-ads { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }
        .audit-no-ssl { background: rgba(244, 63, 94, 0.2); color: #fb7185; border: 1px solid rgba(244, 63, 94, 0.4); }
        .audit-slow { background: rgba(168, 85, 247, 0.2); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4); }
        .audit-cms { background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.35); }

        /* Pitch Modal */
        .modal-overlay {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0, 0, 0, 0.75);
            backdrop-filter: blur(4px);
            z-index: 9999;
            display: none;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .modal-overlay.active { display: flex; }
        .modal-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            max-width: 680px;
            width: 100%;
            max-height: 90vh;
            overflow-y: auto;
            padding: 24px;
            box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5);
            position: relative;
        }
        .modal-close {
            position: absolute;
            top: 18px;
            right: 18px;
            background: none;
            border: none;
            color: var(--text-dim);
            font-size: 22px;
            cursor: pointer;
            line-height: 1;
        }
        .pitch-box {
            background: var(--input-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px 14px;
            margin-top: 6px;
            font-size: 13px;
            line-height: 1.5;
            white-space: pre-wrap;
            color: var(--text);
            user-select: all;
        }

        /* Toast notification */
        #toast {
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: #10b981;
            color: white;
            padding: 12px 20px;
            border-radius: 8px;
            font-weight: 600;
            font-size: 13px;
            box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3);
            z-index: 1000;
            display: none;
            animation: fadeIn 0.2s;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px;">
                <div>
                    <h1>🚀 Лид-Парсер Pro: США, Европа, СНГ & Биржи</h1>
                    <p>Поиск прямых клиентов на Google Maps ($1,500–$5,000+ чек), Яндекс/2ГИС и свежих заказов с фриланс-бирж и Telegram</p>
                </div>
                <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
                    <!-- Theme Selector -->
                    <div style="display: flex; align-items: center; gap: 6px; background: var(--surface); padding: 6px 12px; border-radius: 8px; border: 1px solid var(--border);">
                        <span style="font-size: 13px;">🎨</span>
                        <select id="themeSelect" onchange="setTheme(this.value)" style="width: auto; padding: 4px 8px; font-size: 12px; border: none; background: transparent; cursor: pointer;">
                            <option value="dark">🌙 Dark Tech</option>
                            <option value="midnight">🌌 Midnight Blue</option>
                            <option value="emerald">🌲 Emerald Matrix</option>
                            <option value="cyberpunk">🔮 Cyberpunk</option>
                            <option value="light">☀️ Clean Light</option>
                        </select>
                    </div>

                    <!-- Memory Counter -->
                    <div style="display: flex; align-items: center; gap: 8px; background: var(--surface); padding: 6px 12px; border-radius: 8px; border: 1px solid var(--border);">
                        <span style="font-size: 13px; color: var(--text-dim);">🧠 Память:</span>
                        <span id="memCountBadge" style="font-weight: 700; color: #38bdf8; font-size: 13px;">0</span>
                        <button type="button" onclick="clearMemory()" class="btn btn-secondary" style="padding: 3px 7px; font-size: 11px; margin-left: 2px;" title="Очистить историю проверенных мест">
                            🗑 Сброс
                        </button>
                    </div>
                </div>
            </div>
        </header>

        <!-- Mode Switcher Tabs -->
        <div class="tabs-nav">
            <button type="button" class="tab-btn active" id="tabBtnMaps" onclick="switchTab('maps')">
                <span>🗺️ Лиды на картах (Google Maps, Яндекс, 2ГИС)</span>
                <span class="tab-badge" style="background: linear-gradient(90deg, #38bdf8, #818cf8); color: white;">🇺🇸 США • 🇪🇺 Европа • 🇧🇾 РБ</span>
            </button>
            <button type="button" class="tab-btn" id="tabBtnFreelance" onclick="switchTab('freelance')">
                <span>💼 Заказы с бирж и Telegram</span>
                <span class="tab-badge">🇧🇾 Onliner • Kufar • TG • Kwork</span>
            </button>
            <button type="button" class="tab-btn" id="tabBtnSettings" onclick="switchTab('settings')">
                <span>⚙️ Настройки & Telegram-бот</span>
                <span id="watcherActiveBadge" class="tab-badge" style="display:none; background:#10b981; color:white;">● Мониторинг ON</span>
            </button>
        </div>

        <!-- ================= TAB 1: MAPS SEARCH ================= -->
        <div id="tabContentMaps" class="tab-content active">
            <div class="card">
                <!-- Region Switcher -->
                <div class="region-toggle-wrap">
                    <button type="button" id="regBtnUS" class="region-toggle-btn active-us" onclick="setRegion('us')">
                        <span style="font-size: 22px;">🇺🇸 🇪🇺</span>
                        <div>
                            <div style="font-size: 14px; font-weight: 800;">США & Западная Европа (Google Maps)</div>
                            <div style="font-size: 11px; opacity: 0.85; font-weight: 500;">Чек $1,500 – $5,000+ • Высокомаржинальные ниши • 🟢 WhatsApp & Call</div>
                        </div>
                    </button>
                    <button type="button" id="regBtnCIS" class="region-toggle-btn" onclick="setRegion('cis')">
                        <span style="font-size: 22px;">🇧🇾 🇷🇺</span>
                        <div>
                            <div style="font-size: 14px; font-weight: 800;">Беларусь & СНГ (Яндекс + 2ГИС)</div>
                            <div style="font-size: 11px; opacity: 0.85; font-weight: 500;">Чек $300 – $1,000 • Локальный бизнес • 🟣 Viber, WA & TG</div>
                        </div>
                    </button>
                </div>

                <form id="searchForm" onsubmit="startSearch(event)">
                    <div class="grid-form">
                        <div style="grid-column: span 2;">
                            <label>Ниша / Поисковый запрос</label>
                            <div style="display: flex; gap: 8px;">
                                <input type="text" id="query" list="nichesListUS" placeholder="например, Roofing Contractors или Dental Clinic" required value="Roofing Contractors">
                                <select id="nicheSelectUS" onchange="if(this.value){setNiche(this.value);}" style="width: auto; max-width: 250px;">
                                    <option value="">📂 Выбрать топ-нишу США/ЕС...</option>
                                    __US_NICHE_OPTIONS__
                                </select>
                                <select id="nicheSelectCIS" onchange="if(this.value){setNiche(this.value);}" style="width: auto; max-width: 250px; display: none;">
                                    <option value="">📂 Выбрать нишу РБ/РФ...</option>
                                    __NICHE_OPTIONS__
                                </select>
                            </div>
                            <datalist id="nichesListUS">
                                __US_NICHE_DATALIST__
                            </datalist>
                            <datalist id="nichesListCIS">
                                __NICHE_DATALIST__
                            </datalist>
                        </div>
                        <div>
                            <label>Город(а) поиска (можно несколько через запятую)</label>
                            <input type="text" id="city" placeholder="например, Miami, FL или London" value="Miami, FL">
                            <!-- US Cities -->
                            <div id="cityChipsUS" style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px;">
                                __US_CITY_CHIPS__
                            </div>
                            <!-- CIS Cities -->
                            <div id="cityChipsCIS" style="display: none; flex-wrap: wrap; gap: 4px; margin-top: 6px;">
                                __BY_CITY_CHIPS__
                            </div>
                        </div>
                        <div>
                            <label>Источник карт</label>
                            <select id="source">
                                <option value="both" selected>🇧🇾 🇷🇺 Яндекс Карты + 2ГИС (РБ / СНГ)</option>
                                <option value="yandex">Только Яндекс Карты</option>
                                <option value="google">🇺🇸 🇪🇺 Google Maps (США, Европа, Весь мир)</option>
                                <option value="2gis">Только 2ГИС</option>
                                <option value="all">🌍 Все источники сразу</option>
                            </select>
                        </div>
                        <div>
                            <label>Фильтр лидов</label>
                            <select id="filter">
                                <option value="hot_warm" selected>🔥 Без сайта + ⚡ Соцсети / Taplink (Рекомендуется)</option>
                                <option value="hot_only">🔥 Только БЕЗ САЙТА (100% строгий — нет сайтов)</option>
                                <option value="social_only">⚡ Только соцсети / Taplink / Конструкторы</option>
                                <option value="all">⚪ Все организации (горячие без сайта вверху)</option>
                            </select>
                        </div>
                        <div>
                            <label>Количество лидов</label>
                            <input type="number" id="limit" min="5" max="500" value="50">
                        </div>
                        <div>
                            <button type="submit" id="startBtn" class="btn btn-primary">
                                <span>🚀 Начать сбор лидов</span>
                            </button>
                        </div>
                    </div>

                    <div style="margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 8px;">
                        <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; font-size: 13px; color: var(--text-dim);">
                            <input type="checkbox" id="skipChecked" checked style="width: 16px; height: 16px; cursor: pointer; accent-color: var(--primary);">
                            <span>🧠 <b>Не парсить уже проверенные места</b> (пропускать компании, которые уже есть в памяти)</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; font-size: 13px; color: #38bdf8;">
                            <input type="checkbox" id="verifyWeb" checked style="width: 16px; height: 16px; cursor: pointer; accent-color: #38bdf8;">
                            <span>🌐 <b>Проверять наличие сайта в интернете по названию</b> (поиск домена и в поисковиках для 100% подтверждения)</span>
                        </label>
                    </div>

                    <!-- US Niche Chips -->
                    <div id="nicheChipsUS" style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; align-items: center;">
                        <span style="font-size: 12px; color: #38bdf8; font-weight: 700;">🔥 Горячие ниши США/ЕС ($1.5k–$5k чек):</span>
                        __US_NICHE_CHIPS__
                    </div>

                    <!-- CIS Niche Chips -->
                    <div id="nicheChipsCIS" style="display: none; flex-wrap: wrap; gap: 6px; margin-top: 12px; align-items: center;">
                        <span style="font-size: 12px; color: #10b981; font-weight: 700;">💼 Высокочековые ниши РБ/РФ:</span>
                        __NICHE_CHIPS__
                    </div>
                </form>
            </div>

            <div class="progress-box" id="progressBox">
                <div style="display: flex; justify-content: space-between; font-size: 14px;">
                    <span id="progressMsg" style="color: var(--primary); font-weight: 600;">Сбор данных...</span>
                    <span id="progressCount" style="color: var(--text-dim);">0 / 50</span>
                </div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill" id="progressBar"></div>
                </div>
            </div>

            <div class="stats-bar">
                <div class="stat-card">
                    <div class="stat-label">Всего в базе</div>
                    <div class="stat-val" id="statTotal" style="color: #38bdf8;">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">🔥 Совсем нет сайта</div>
                    <div class="stat-val" id="statHigh" style="color: #34d399;">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">⚡ Только соцсеть/Taplink</div>
                    <div class="stat-val" id="statMed" style="color: #fbbf24;">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">📞 С номерами телефонов</div>
                    <div class="stat-val" id="statPhones" style="color: #a855f7;">0</div>
                </div>
            </div>

            <div class="card" style="padding: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; flex-wrap: wrap; gap: 10px;">
                    <div>
                        <h2 style="font-size: 18px; font-weight: 700;">Собранная база клиентов</h2>
                        <div id="tableCounter" style="font-size: 12px; color: var(--text-dim); margin-top: 2px;"></div>
                    </div>
                    <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                        <input type="text" id="tableFilterInput" placeholder="🔍 Быстрый поиск в таблице..." oninput="filterTable()" style="width: 230px; padding: 7px 12px; font-size: 13px;">
                        <button onclick="copyAllPhones()" class="btn btn-secondary" id="btnCopyPhones" disabled title="Скопировать все найденные телефоны в буфер обмена">
                            📋 Скопировать телефоны
                        </button>
                        <button onclick="downloadFile('excel')" class="btn btn-success" id="btnExcel" disabled>
                            📥 Excel (.xlsx)
                        </button>
                        <button onclick="downloadFile('csv')" class="btn btn-secondary" id="btnCsv" disabled>
                            📄 CSV
                        </button>
                    </div>
                </div>

                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th style="width: 45px;">№</th>
                                <th style="width: 155px;">Статус сайта</th>
                                <th>Компания (ссылка на карты)</th>
                                <th>Телефон</th>
                                <th>Сайт / Ссылка</th>
                                <th>Отзывы</th>
                                <th>Адрес</th>
                                <th>Источник</th>
                                <th style="width: 210px; text-align: center;">Быстрые действия (Viber / WA / TG)</th>
                            </tr>
                        </thead>
                        <tbody id="leadsTableBody">
                            <tr>
                                <td colspan="9" style="text-align: center; color: var(--text-dim); padding: 40px;">
                                    Задайте параметры поиска и нажмите кнопку «Начать сбор лидов»
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- ================= TAB 2: FREELANCE EXCHANGES SEARCH ================= -->
        <div id="tabContentFreelance" class="tab-content">
            <div class="card">
                <form id="freelanceForm" onsubmit="startFreelanceSearch(event)">
                    <div class="grid-form">
                        <div style="grid-column: span 2;">
                            <label>Поисковый запрос / Специализация</label>
                            <input type="text" id="flQuery" placeholder="например, разработка сайта, лендинг, tilda, интернет-магазин" required value="разработка сайта">
                        </div>
                        <div>
                            <label>Количество заказов</label>
                            <input type="number" id="flLimit" min="10" max="200" value="50">
                        </div>
                        <div>
                            <button type="submit" id="flStartBtn" class="btn btn-primary" style="background: linear-gradient(90deg, #6366f1, #a855f7);">
                                <span>🚀 Найти заказы на биржах</span>
                            </button>
                        </div>
                    </div>

                    <!-- Platform Checkboxes -->
                    <div style="margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); display: flex; align-items: center; flex-wrap: wrap; gap: 14px;">
                        <span style="font-size: 13px; font-weight: 600; color: var(--text-dim);">Площадки:</span>
                        <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; font-size: 13px;">
                            <input type="checkbox" id="pfOnliner" checked style="width: 16px; height: 16px; accent-color: #facc15;">
                            <span class="badge badge-onliner">🇧🇾 Onliner Услуги</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; font-size: 13px;">
                            <input type="checkbox" id="pfTg" checked style="width: 16px; height: 16px; accent-color: #38bdf8;">
                            <span class="badge badge-tg">✈️ Telegram (Свежие заказы)</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; font-size: 13px;" title="Только реальные запросы от заказчиков (предложения других студий отсекаются)">
                            <input type="checkbox" id="pfKufar" style="width: 16px; height: 16px; accent-color: #2dd4bf;">
                            <span class="badge badge-kufar">🇧🇾 Kufar (Только заказчики)</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; font-size: 13px;">
                            <input type="checkbox" id="pfKwork" checked style="width: 16px; height: 16px; accent-color: #a855f7;">
                            <span class="badge badge-kwork">Kwork (РБ)</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; font-size: 13px;">
                            <input type="checkbox" id="pfFl" checked style="width: 16px; height: 16px; accent-color: #3b82f6;">
                            <span class="badge badge-fl">FL.ru (РБ)</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; font-size: 13px;">
                            <input type="checkbox" id="pfFh" checked style="width: 16px; height: 16px; accent-color: #10b981;">
                            <span class="badge badge-fh">Freelancehunt</span>
                        </label>
                    </div>

                    <!-- Keyword Presets Chips -->
                    <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; align-items: center;">
                        <span style="font-size: 12px; color: var(--text-dim); font-weight: 600;">Быстрые тематики:</span>
                        <button type="button" class="chip" onclick="setFlQuery('разработка сайта под ключ')">🌐 Сайт под ключ</button>
                        <button type="button" class="chip" onclick="setFlQuery('лендинг')">🚀 Лендинг пейдж</button>
                        <button type="button" class="chip" onclick="setFlQuery('интернет-магазин')">🛒 Интернет-магазин</button>
                        <button type="button" class="chip" onclick="setFlQuery('tilda')">🎨 Tilda / No-Code</button>
                        <button type="button" class="chip" onclick="setFlQuery('доработка сайта')">🔧 Доработка сайта / Правки</button>
                        <button type="button" class="chip" onclick="setFlQuery('верстка')">💻 Верстка / Frontend</button>
                        <button type="button" class="chip" onclick="setFlQuery('wordpress')">📦 WordPress / CMS</button>
                    </div>
                </form>
            </div>

            <!-- Freelance Progress Box -->
            <div class="progress-box" id="flProgressBox">
                <div style="display: flex; justify-content: space-between; font-size: 14px;">
                    <span id="flProgressMsg" style="color: #818cf8; font-weight: 600;">Поиск заказов...</span>
                    <span id="flProgressCount" style="color: var(--text-dim);">0 / 50</span>
                </div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill" id="flProgressBar" style="background: linear-gradient(90deg, #6366f1, #10b981);"></div>
                </div>
            </div>

            <!-- Freelance Stats Bar -->
            <div class="stats-bar">
                <div class="stat-card">
                    <div class="stat-label">Всего заказов</div>
                    <div class="stat-val" id="statFlTotal" style="color: #38bdf8;">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">💰 С указанным бюджетом</div>
                    <div class="stat-val" id="statFlPriced" style="color: #34d399;">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">🇧🇾 Беларусь (Onliner / Kufar)</div>
                    <div class="stat-val" id="statFlBy" style="color: #facc15;">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">✈️ Telegram & Биржи</div>
                    <div class="stat-val" id="statFlTg" style="color: #c084fc;">0</div>
                </div>
            </div>

            <!-- Freelance Table Card -->
            <div class="card" style="padding: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; flex-wrap: wrap; gap: 10px;">
                    <div>
                        <h2 style="font-size: 18px; font-weight: 700;">Свежие заказы с бирж и каналов</h2>
                        <div id="flTableCounter" style="font-size: 12px; color: var(--text-dim); margin-top: 2px;"></div>
                    </div>
                    <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                        <input type="text" id="flTableFilterInput" placeholder="🔍 Быстрый поиск в заказах..." oninput="filterFreelanceTable()" style="width: 240px; padding: 7px 12px; font-size: 13px;">
                        <button onclick="downloadFreelance('excel')" class="btn btn-success" id="btnFlExcel" disabled>
                            📥 Excel (.xlsx)
                        </button>
                        <button onclick="downloadFreelance('csv')" class="btn btn-secondary" id="btnFlCsv" disabled>
                            📄 CSV
                        </button>
                    </div>
                </div>

                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th style="width: 45px;">№</th>
                                <th style="width: 160px;">Платформа</th>
                                <th>Заказ / Название проекта</th>
                                <th style="width: 170px;">Бюджет</th>
                                <th>Отклики / Время</th>
                                <th style="width: 190px; text-align: center;">Действия</th>
                            </tr>
                        </thead>
                        <tbody id="freelanceTableBody">
                            <tr>
                                <td colspan="6" style="text-align: center; color: var(--text-dim); padding: 40px;">
                                    Выберите тематику и нажмите кнопку «Найти заказы на биржах»
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- ================= TAB 3: SETTINGS & MONITORING ================= -->
        <div id="tabContentSettings" class="tab-content">
            <div class="card">
                <h2 style="font-size: 18px; font-weight: 700; margin-bottom: 6px;">🤖 Telegram-бот & Фоновый мониторинг бирж</h2>
                <p style="color: var(--text-dim); font-size: 13px; margin-bottom: 20px;">
                    Настройте мгновенные алерты в ваш личный Telegram или рабочий канал при появлении новых заказов на разработку сайтов (Onliner Услуги, Kwork, FL.ru).
                </p>

                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; margin-bottom: 22px;">
                    <div>
                        <label>Telegram Bot Token</label>
                        <input type="text" id="cfgBotToken" placeholder="например, 7123456789:AAH_..." style="font-family: monospace; font-size: 13px;">
                        <span style="font-size: 11px; color: var(--text-dim); margin-top: 4px; display: block;">Создайте бота у @BotFather в Telegram за 1 минуту</span>
                    </div>
                    <div>
                        <label>Telegram Chat ID (ваш ID или ID канала)</label>
                        <input type="text" id="cfgChatId" placeholder="например, 123456789 или @my_channel" style="font-family: monospace; font-size: 13px;">
                        <span style="font-size: 11px; color: var(--text-dim); margin-top: 4px; display: block;">Узнать свой ID можно через бота @userinfobot</span>
                    </div>
                </div>

                <div style="margin-bottom: 20px;">
                    <button type="button" onclick="testTelegramAlert()" class="btn btn-secondary" style="padding: 8px 16px;">
                        🔔 Отправить тестовое сообщение в Telegram
                    </button>
                    <span id="testTgStatus" style="margin-left: 10px; font-size: 13px; font-weight: 600;"></span>
                </div>

                <hr style="border: none; border-top: 1px solid var(--border); margin: 20px 0;">

                <h3 style="font-size: 15px; font-weight: 700; margin-bottom: 12px;">⚡ Фоновый авто-мониторинг Onliner & бирж</h3>
                
                <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 16px;">
                    <button type="button" id="btnToggleWatcher" onclick="toggleWatcher()" class="btn btn-primary" style="width: auto; padding: 10px 22px;">
                        ▶️ Запустить фоновый мониторинг
                    </button>
                    <span id="watcherStatusText" style="font-size: 13px; color: var(--text-dim);">Статус: Остановлен</span>
                </div>

                <div style="display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 20px;">
                    <label style="display: flex; align-items: center; gap: 8px; font-weight: 500; cursor: pointer;">
                        <input type="checkbox" id="cfgNotifyOnliner" checked style="width: auto;"> 🇧🇾 Onliner Услуги (Беларусь)
                    </label>
                    <label style="display: flex; align-items: center; gap: 8px; font-weight: 500; cursor: pointer;">
                        <input type="checkbox" id="cfgNotifyKwork" checked style="width: auto;"> ⚡ Kwork
                    </label>
                    <label style="display: flex; align-items: center; gap: 8px; font-weight: 500; cursor: pointer;">
                        <input type="checkbox" id="cfgNotifyFl" checked style="width: auto;"> 🌐 FL.ru
                    </label>
                </div>

                <div style="max-width: 250px; margin-bottom: 22px;">
                    <label>Интервал проверки (минут)</label>
                    <input type="number" id="cfgInterval" min="1" max="60" value="3">
                </div>

                <hr style="border: none; border-top: 1px solid var(--border); margin: 20px 0;">

                <h3 style="font-size: 15px; font-weight: 700; margin-bottom: 6px;">🧠 Google Gemini API (Опционально)</h3>
                <p style="color: var(--text-dim); font-size: 12px; margin-bottom: 12px;">
                    По умолчанию парсер использует встроенный умный генератор офферов. Если вы укажете ключ Gemini API, питчи будут генерироваться через нейросеть индивидуально под каждый бизнес.
                </p>
                <div style="max-width: 500px; margin-bottom: 22px;">
                    <label>Gemini API Key</label>
                    <input type="password" id="cfgGeminiKey" placeholder="AIzaSy..." style="font-family: monospace;">
                </div>

                <button type="button" onclick="saveSettingsForm()" class="btn btn-success" style="padding: 10px 24px;">
                    💾 Сохранить настройки
                </button>
            </div>
        </div>

    </div>

    <!-- Modal: AI Pitch & Cold Call Script -->
    <div id="pitchModal" class="modal-overlay" onclick="if(event.target===this)closePitchModal()">
        <div class="modal-card">
            <button type="button" class="modal-close" onclick="closePitchModal()">&times;</button>
            
            <div style="background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 8px; padding: 10px 14px; margin-bottom: 16px; font-size: 13px; color: #34d399; display: flex; align-items: center; gap: 10px;">
                <span style="font-size: 20px;">⚡</span>
                <div>
                    <strong>API подключать не требуется!</strong> Все продающие офферы и скрипты звонков формируются автоматически бесплатно на основе данных об организации.
                </div>
            </div>

            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 14px;">
                <span style="font-size: 26px;">💡</span>
                <div>
                    <h2 id="modalOrgName" style="font-size: 18px; font-weight: 800;">Название компании</h2>
                    <div id="modalOrgMeta" style="font-size: 12px; color: var(--text-dim);">Город • Ниша</div>
                </div>
            </div>

            <!-- Audit badges if present -->
            <div id="modalAuditBadges" style="margin-bottom: 16px;"></div>

            <!-- WhatsApp / Telegram Pitch -->
            <div style="margin-bottom: 20px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <label style="margin: 0; font-weight: 700; color: #38bdf8;">💬 Персональное сообщение в мессенджер (WhatsApp / TG / Viber)</label>
                    <button type="button" onclick="copyModalPitch()" class="btn btn-secondary" style="padding: 3px 10px; font-size: 11px;">
                        📋 Скопировать
                    </button>
                </div>
                <div id="modalPitchText" class="pitch-box"></div>
                <div style="display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap;">
                    <a id="modalBtnWA" href="#" target="_blank" class="btn btn-act-wa" style="text-decoration: none; padding: 7px 14px; font-size: 12px;">🟢 Открыть в WhatsApp с этим текстом</a>
                    <a id="modalBtnTG" href="#" target="_blank" class="btn btn-act-tg" style="text-decoration: none; padding: 7px 14px; font-size: 12px;">💬 Открыть в Telegram</a>
                </div>
            </div>

            <!-- Cold Call Script -->
            <div>
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <label style="margin: 0; font-weight: 700; color: #a855f7;">📞 Скрипт 30-секундного звонка руководителю</label>
                    <button type="button" onclick="copyModalCall()" class="btn btn-secondary" style="padding: 3px 10px; font-size: 11px;">
                        📋 Скопировать
                    </button>
                </div>
                <div id="modalCallText" class="pitch-box"></div>
            </div>
        </div>
    </div>

    <!-- Floating Toast Notification -->
    <div id="toast"></div>

    <script>
        let pollTimer = null;
        let flPollTimer = null;
        let allLeads = [];
        let currentDisplayedLeads = [];
        let allOrders = [];

        function switchTab(tabName) {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            
            if (tabName === 'freelance') {
                document.getElementById('tabBtnFreelance').classList.add('active');
                document.getElementById('tabContentFreelance').classList.add('active');
            } else if (tabName === 'settings') {
                document.getElementById('tabBtnSettings').classList.add('active');
                document.getElementById('tabContentSettings').classList.add('active');
                loadSettings();
                checkWatcherStatus();
            } else {
                document.getElementById('tabBtnMaps').classList.add('active');
                document.getElementById('tabContentMaps').classList.add('active');
            }
            try {
                localStorage.setItem('lead_active_tab', tabName);
            } catch (e) {}
        }

        function setTheme(theme) {
            document.documentElement.setAttribute('data-theme', theme);
            try {
                localStorage.setItem('lead_theme', theme);
            } catch (e) {}
            const sel = document.getElementById('themeSelect');
            if (sel) sel.value = theme;
        }

        let currentRegion = 'us';

        function setRegion(reg) {
            currentRegion = reg;
            const btnUS = document.getElementById('regBtnUS');
            const btnCIS = document.getElementById('regBtnCIS');
            const selUS = document.getElementById('nicheSelectUS');
            const selCIS = document.getElementById('nicheSelectCIS');
            const chipsUS = document.getElementById('nicheChipsUS');
            const chipsCIS = document.getElementById('nicheChipsCIS');
            const cityChipsUS = document.getElementById('cityChipsUS');
            const cityChipsCIS = document.getElementById('cityChipsCIS');
            const queryEl = document.getElementById('query');
            const cityEl = document.getElementById('city');
            const sourceEl = document.getElementById('source');

            if (reg === 'us') {
                if (btnUS) btnUS.className = 'region-toggle-btn active-us';
                if (btnCIS) btnCIS.className = 'region-toggle-btn';
                if (selUS) selUS.style.display = 'block';
                if (selCIS) selCIS.style.display = 'none';
                if (chipsUS) chipsUS.style.display = 'flex';
                if (chipsCIS) chipsCIS.style.display = 'none';
                if (cityChipsUS) cityChipsUS.style.display = 'flex';
                if (cityChipsCIS) cityChipsCIS.style.display = 'none';
                queryEl.setAttribute('list', 'nichesListUS');
                if (sourceEl) sourceEl.value = 'google';
                if (!queryEl.value || queryEl.value === 'Коттеджи на сутки и агроусадьбы') {
                    queryEl.value = 'Roofing Contractors';
                }
                if (!cityEl.value || cityEl.value === 'Минск') {
                    cityEl.value = 'Miami, FL';
                }
                queryEl.placeholder = 'например, Roofing Contractors или Dental Clinic';
                cityEl.placeholder = 'например, Miami, FL или London или New York, NY';
            } else {
                if (btnCIS) btnCIS.className = 'region-toggle-btn active-cis';
                if (btnUS) btnUS.className = 'region-toggle-btn';
                if (selCIS) selCIS.style.display = 'block';
                if (selUS) selUS.style.display = 'none';
                if (chipsCIS) chipsCIS.style.display = 'flex';
                if (chipsUS) chipsUS.style.display = 'none';
                if (cityChipsCIS) cityChipsCIS.style.display = 'flex';
                if (cityChipsUS) cityChipsUS.style.display = 'none';
                queryEl.setAttribute('list', 'nichesListCIS');
                if (sourceEl) sourceEl.value = 'both';
                if (!queryEl.value || queryEl.value === 'Roofing Contractors') {
                    queryEl.value = 'Коттеджи на сутки и агроусадьбы';
                }
                if (!cityEl.value || cityEl.value === 'Miami, FL') {
                    cityEl.value = 'Минск';
                }
                queryEl.placeholder = 'например, Коттеджи на сутки или Стоматология';
                cityEl.placeholder = 'например, Минск или Москва';
            }
            try {
                localStorage.setItem('lead_region', reg);
            } catch (e) {}
        }

        function setNiche(val) {
            document.getElementById('query').value = val;
            const selUS = document.getElementById('nicheSelectUS');
            const selCIS = document.getElementById('nicheSelectCIS');
            if (selUS) selUS.value = val;
            if (selCIS) selCIS.value = val;
        }

        function setCities(citiesStr) {
            document.getElementById('city').value = citiesStr;
        }

        function setFlQuery(query) {
            document.getElementById('flQuery').value = query;
        }

        function showToast(msg) {
            const t = document.getElementById('toast');
            if (!t) return;
            t.innerText = msg;
            t.style.display = 'block';
            setTimeout(() => {
                t.style.display = 'none';
            }, 2500);
        }

        function copyPhone(phone) {
            if (!phone || phone === '—') return;
            navigator.clipboard.writeText(phone).then(() => {
                showToast(`Скопирован номер: ${phone}`);
            }).catch(() => {
                copyFallback(phone, `Скопирован номер: ${phone}`);
            });
        }

        function copyLink(url) {
            if (!url) return;
            navigator.clipboard.writeText(url).then(() => {
                showToast('Ссылка на заказ скопирована в буфер!');
            }).catch(() => {
                copyFallback(url, 'Ссылка на заказ скопирована в буфер!');
            });
        }

        function copyFallback(text, msg) {
            const ta = document.createElement('textarea');
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            showToast(msg);
        }

        function copyAllPhones() {
            if (!allLeads || allLeads.length === 0) return;
            const phones = [];
            allLeads.forEach(l => {
                if (l.phones && l.phones.length > 0) {
                    l.phones.forEach(p => {
                        if (p && !phones.includes(p)) phones.push(p);
                    });
                }
            });
            if (phones.length === 0) {
                alert('В собранных лидах нет номеров телефонов.');
                return;
            }
            const text = phones.join(String.fromCharCode(10));
            navigator.clipboard.writeText(text).then(() => {
                showToast(`Скопировано ${phones.length} номеров в буфер!`);
            }).catch(() => {
                copyFallback(text, `Скопировано ${phones.length} номеров в буфер!`);
            });
        }

        function filterTable() {
            const q = (document.getElementById('tableFilterInput').value || '').toLowerCase().trim();
            if (!q) {
                renderTable(allLeads, false);
                return;
            }
            const filtered = allLeads.filter(l => {
                const name = (l.name || '').toLowerCase();
                const addr = (l.address || '').toLowerCase();
                const city = (l.city || '').toLowerCase();
                const phones = (l.phones || []).join(' ').toLowerCase();
                const site = (l.website || '').toLowerCase();
                const notes = (l.notes || '').toLowerCase();
                return name.includes(q) || addr.includes(q) || city.includes(q) || phones.includes(q) || site.includes(q) || notes.includes(q);
            });
            renderTable(filtered, true);
        }

        function filterFreelanceTable() {
            const q = (document.getElementById('flTableFilterInput').value || '').toLowerCase().trim();
            if (!q) {
                renderFreelanceTable(allOrders, false);
                return;
            }
            const filtered = allOrders.filter(o => {
                const title = (o.title || '').toLowerCase();
                const desc = (o.description || '').toLowerCase();
                const price = (o.price || '').toLowerCase();
                const platform = (o.platform || '').toLowerCase();
                return title.includes(q) || desc.includes(q) || price.includes(q) || platform.includes(q);
            });
            renderFreelanceTable(filtered, true);
        }

        async function fetchMemoryStats() {
            try {
                const res = await fetch('/api/memory/stats');
                const stats = await res.json();
                if (stats && stats.total_checked !== undefined) {
                    document.getElementById('memCountBadge').innerText = stats.total_checked;
                }
            } catch (err) {
                console.error(err);
            }
        }

        async function clearMemory() {
            const current = document.getElementById('memCountBadge').innerText;
            if (current === '0') {
                alert('Память парсера уже пуста.');
                return;
            }
            if (!confirm(`Вы действительно хотите удалить все ${current} проверенных мест из памяти? При следующих поисках парсер будет проверять их заново.`)) {
                return;
            }
            try {
                const res = await fetch('/api/memory/clear', { method: 'POST' });
                const data = await res.json();
                if (data.success) {
                    document.getElementById('memCountBadge').innerText = '0';
                    alert(`Память успешно очищена (удалено записей: ${data.deleted}).`);
                }
            } catch (err) {
                alert('Ошибка при очистке памяти: ' + err);
            }
        }

        // ================= MAP SEARCH LOGIC =================
        async function startSearch(e) {
            e.preventDefault();
            const btn = document.getElementById('startBtn');
            btn.disabled = true;
            btn.innerHTML = '<span>⏳ Сбор запущен...</span>';
            
            document.getElementById('progressBox').classList.add('active');
            document.getElementById('btnExcel').disabled = true;
            document.getElementById('btnCsv').disabled = true;
            document.getElementById('btnCopyPhones').disabled = true;

            const skipCheckedEl = document.getElementById('skipChecked');
            const verifyWebEl = document.getElementById('verifyWeb');
            const payload = {
                query: document.getElementById('query').value,
                city: document.getElementById('city').value,
                source: document.getElementById('source').value,
                filter: document.getElementById('filter').value,
                limit: parseInt(document.getElementById('limit').value, 10) || 50,
                skip_checked: skipCheckedEl ? skipCheckedEl.checked : true,
                verify_web: verifyWebEl ? verifyWebEl.checked : true,
            };

            await fetch('/api/search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (pollTimer) clearInterval(pollTimer);
            pollTimer = setInterval(pollStatus, 1500);
        }

        async function pollStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();

                // Update Progress
                document.getElementById('progressMsg').innerText = data.progress_message;
                const count = data.leads.length;
                const target = data.total_target || 50;
                document.getElementById('progressCount').innerText = `${count} / ${target}`;
                const pct = Math.min(100, Math.round((count / target) * 100));
                document.getElementById('progressBar').style.width = pct + '%';

                if (data.memory_stats && data.memory_stats.total_checked !== undefined) {
                    document.getElementById('memCountBadge').innerText = data.memory_stats.total_checked;
                }

                // Update Stats
                document.getElementById('statTotal').innerText = count;
                const high = data.leads.filter(l => l.lead_priority && l.lead_priority.includes('Высокий')).length;
                const med = data.leads.filter(l => l.lead_priority && l.lead_priority.includes('Средний')).length;
                const phones = data.leads.filter(l => l.phones && l.phones.length > 0).length;

                document.getElementById('statHigh').innerText = high;
                document.getElementById('statMed').innerText = med;
                document.getElementById('statPhones').innerText = phones;

                // Render Table with live leads
                renderTable(data.leads, false);

                if (!data.is_running && count > 0) {
                    clearInterval(pollTimer);
                    document.getElementById('startBtn').disabled = false;
                    document.getElementById('startBtn').innerHTML = '<span>🚀 Начать новый сбор</span>';
                    document.getElementById('btnExcel').disabled = false;
                    document.getElementById('btnCsv').disabled = false;
                    document.getElementById('btnCopyPhones').disabled = false;
                    fetchMemoryStats();
                } else if (!data.is_running && count === 0) {
                    clearInterval(pollTimer);
                    document.getElementById('startBtn').disabled = false;
                    document.getElementById('startBtn').innerHTML = '<span>🚀 Начать новый сбор</span>';
                }
            } catch (err) {
                console.error(err);
            }
        }

        // ================= FREELANCE SEARCH LOGIC =================
        async function startFreelanceSearch(e) {
            e.preventDefault();
            const btn = document.getElementById('flStartBtn');
            btn.disabled = true;
            btn.innerHTML = '<span>⏳ Поиск на биржах...</span>';

            document.getElementById('flProgressBox').classList.add('active');
            document.getElementById('btnFlExcel').disabled = true;
            document.getElementById('btnFlCsv').disabled = true;

            const platforms = [];
            if (document.getElementById('pfOnliner').checked) platforms.push('onliner');
            if (document.getElementById('pfTg').checked) platforms.push('telegram');
            if (document.getElementById('pfKufar').checked) platforms.push('kufar');
            if (document.getElementById('pfKwork').checked) platforms.push('kwork');
            if (document.getElementById('pfFl').checked) platforms.push('fl');
            if (document.getElementById('pfFh').checked) platforms.push('freelancehunt');

            if (platforms.length === 0) {
                alert('Выберите хотя бы одну платформу для поиска!');
                btn.disabled = false;
                btn.innerHTML = '<span>🚀 Найти заказы на биржах</span>';
                return;
            }

            const payload = {
                query: document.getElementById('flQuery').value,
                platforms: platforms,
                limit: parseInt(document.getElementById('flLimit').value, 10) || 50,
            };

            await fetch('/api/freelance/search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (flPollTimer) clearInterval(flPollTimer);
            flPollTimer = setInterval(pollFreelanceStatus, 1500);
        }

        async function pollFreelanceStatus() {
            try {
                const res = await fetch('/api/freelance/status');
                const data = await res.json();

                document.getElementById('flProgressMsg').innerText = data.progress_message;
                const count = data.orders.length;
                const target = data.total_target || 50;
                document.getElementById('flProgressCount').innerText = `${count} / ${target}`;
                const pct = Math.min(100, Math.round((count / target) * 100));
                document.getElementById('flProgressBar').style.width = pct + '%';

                // Stats
                document.getElementById('statFlTotal').innerText = count;
                const priced = data.orders.filter(o => {
                    const p = (o.price || '').toLowerCase();
                    return p && !p.includes('договор') && !p.includes('собеседован');
                }).length;
                const byCount = data.orders.filter(o => o.platform.includes('Onliner') || o.platform.includes('Kufar')).length;
                const tgCount = data.orders.filter(o => o.platform.includes('Telegram') || o.platform.includes('Kwork')).length;

                document.getElementById('statFlPriced').innerText = priced;
                document.getElementById('statFlBy').innerText = byCount;
                document.getElementById('statFlTg').innerText = tgCount;

                renderFreelanceTable(data.orders, false);

                if (!data.is_running && count > 0) {
                    clearInterval(flPollTimer);
                    document.getElementById('flStartBtn').disabled = false;
                    document.getElementById('flStartBtn').innerHTML = '<span>🚀 Новый поиск на биржах</span>';
                    document.getElementById('btnFlExcel').disabled = false;
                    document.getElementById('btnFlCsv').disabled = false;
                } else if (!data.is_running && count === 0) {
                    clearInterval(flPollTimer);
                    document.getElementById('flStartBtn').disabled = false;
                    document.getElementById('flStartBtn').innerHTML = '<span>🚀 Новый поиск на биржах</span>';
                }
            } catch (err) {
                console.error(err);
            }
        }

        window.addEventListener('DOMContentLoaded', () => {
            try {
                const savedTheme = localStorage.getItem('lead_theme') || 'dark';
                setTheme(savedTheme);
                const savedTab = localStorage.getItem('lead_active_tab') || 'maps';
                switchTab(savedTab);
                const savedReg = localStorage.getItem('lead_region') || 'us';
                setRegion(savedReg);
            } catch (e) {}
            fetchMemoryStats();
        });

        function escapeHtml(str) {
            if (!str) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        }

        function renderTable(leads, isFiltered = false) {
            if (!isFiltered) {
                allLeads = leads || [];
            }
            currentDisplayedLeads = leads || allLeads || [];
            const tbody = document.getElementById('leadsTableBody');
            const counter = document.getElementById('tableCounter');
            const btnCopy = document.getElementById('btnCopyPhones');

            if (!leads || leads.length === 0) {
                if (isFiltered) {
                    tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: var(--text-dim); padding: 30px;">По вашему поисковому запросу ничего не найдено</td></tr>';
                    if (counter) counter.innerText = `Показано 0 из ${allLeads.length}`;
                } else {
                    if (counter) counter.innerText = '';
                    if (btnCopy) btnCopy.disabled = true;
                }
                return;
            }

            if (btnCopy) btnCopy.disabled = false;
            if (counter) {
                counter.innerText = isFiltered ? `Показано ${leads.length} из ${allLeads.length}` : `Всего в таблице: ${leads.length}`;
            }

            let html = '';
            leads.forEach((l, idx) => {
                const isInvalidSite = !l.website || ['yandex.', 'ya.ru', 'ya.by', 'google.', '2gis.', 'maps/org', 'clck/'].some(ign => l.website.toLowerCase().includes(ign));
                let siteStr = !isInvalidSite 
                    ? `<a class="site-link" href="${l.website}" target="_blank" title="${escapeHtml(l.website)}">${escapeHtml(l.website)}</a>` 
                    : '<span style="color: #10b981; font-weight: 700;">Отсутствует</span>';

                let badgeClass = 'badge-low';
                let statusVal = l.website_status || '';
                let badgeText = '⚪ Есть свой сайт';

                if (statusVal.includes('Нет сайта') || isInvalidSite) {
                    badgeClass = 'badge-high';
                    badgeText = '🔥 НЕТ САЙТА';
                } else if (statusVal.includes('Taplink') || (l.website && (l.website.includes('dikidi') || l.website.includes('yclients')))) {
                    badgeClass = 'badge-med';
                    badgeText = '⚡ Онлайн-запись / Taplink';
                } else if (statusVal.includes('Конструктор')) {
                    badgeClass = 'badge-med';
                    badgeText = '💡 Конструктор';
                } else if (statusVal.includes('соцсеть')) {
                    badgeClass = 'badge-med';
                    badgeText = '⚡ Только соцсеть';
                } else {
                    badgeClass = 'badge-low';
                    badgeText = '⚪ Есть свой сайт';
                }

                const primaryPhone = (l.phones && l.phones.length > 0) ? l.phones[0] : '';
                const cleanDigits = primaryPhone.replace(/\D/g, '');
                const mobBadge = l.is_mobile 
                    ? '<span class="badge-mob" title="Мобильный номер - доступен в WhatsApp и Telegram">📱 Моб.</span>'
                    : (primaryPhone ? '<span class="badge-land" title="Городской стационарный номер">☎️ Гор.</span>' : '');
                const phoneStr = primaryPhone 
                    ? `<div style="display: flex; align-items: center; white-space: nowrap;">${mobBadge}<a class="tel-link" href="tel:${primaryPhone}" title="Позвонить">${primaryPhone}</a></div>` 
                    : '<span style="color: var(--text-dim);">—</span>';

                // Clickable company name opening map card
                const nameStr = l.map_url 
                    ? `<a href="${l.map_url}" target="_blank" class="org-link" title="Открыть карточку организации на картах">${escapeHtml(l.name)} <span class="link-icon">↗</span></a>`
                    : `<span style="font-weight: 700;">${escapeHtml(l.name)}</span>`;

                if (l.notes && l.notes.includes('100%')) {
                    siteStr += `<div style="font-size: 11px; color: #34d399; margin-top: 2px;">✅ Проверено в сети</div>`;
                }

                if (!isInvalidSite && l.site_audit_summary) {
                    const auditBadges = l.site_audit_summary.split(' | ').map(b => {
                        let cls = 'audit-tag';
                        if (b.includes('НЕТ МОБИЛКИ')) cls += ' audit-no-mobile';
                        else if (b.includes('КРУТЯТ РЕКЛАМУ')) cls += ' audit-ads';
                        else if (b.includes('НЕТ SSL')) cls += ' audit-no-ssl';
                        else if (b.includes('Медленный')) cls += ' audit-slow';
                        else cls += ' audit-cms';
                        return `<span class="${cls}">${escapeHtml(b)}</span>`;
                    }).join('');
                    siteStr += `<div style="margin-top: 3px;">${auditBadges}</div>`;
                }

                const reviews = (l.rating !== null && l.rating !== undefined) 
                    ? `⭐ ${l.rating} (${l.reviews_count || 0})` 
                    : '<span style="color: var(--text-dim);">—</span>';

                const fullAddr = [l.city, l.address].filter(Boolean).join(', ');

                // Determine whether this lead is from CIS or International
                const isCis = (l.is_cis !== undefined) ? l.is_cis : (l.source !== 'Google Maps');
                const primaryDigits = l.clean_phone_digits || cleanDigits;

                // Quick action buttons: AI-Pitch + Viber/WA/TG for CIS, or WhatsApp + Call for US/EU
                let actHtml = `<div class="actions-cell">`;
                actHtml += `<button onclick="openPitchModal(${idx})" class="btn-act btn-act-pitch" style="font-weight: 700; background: linear-gradient(135deg, rgba(245, 158, 11, 0.25), rgba(234, 88, 12, 0.25)); border-color: rgba(245, 158, 11, 0.6); color: #fbbf24;" title="💡 Открыть готовый продающий оффер и скрипт звонка на 30 сек">💡 Текст оффера (AI)</button>`;

                if (l.map_url) {
                    actHtml += `<a href="${l.map_url}" target="_blank" class="btn-act btn-act-map" title="Открыть на карте">🗺️</a>`;
                }
                if (primaryPhone) {
                    if (isCis) {
                        // Belarus / CIS: Viber, WhatsApp with pitch, Telegram
                        const vbLink = l.viber_url || `viber://chat?number=%2B${primaryDigits}`;
                        actHtml += `<a href="${vbLink}" target="_blank" class="btn-act btn-act-vb" title="Написать в Viber">🟣 Viber</a>`;

                        const pitchText = l.ai_pitch || `Здравствуйте! Нашли организацию "${l.name}" на картах. Подскажите, пожалуйста, вы принимаете заказы?`;
                        const waText = encodeURIComponent(pitchText);
                        actHtml += `<a href="https://wa.me/${primaryDigits}?text=${waText}" target="_blank" class="btn-act btn-act-wa" title="Написать в WhatsApp с готовым питчем">🟢 WA</a>`;

                        const tgUrl = l.telegram_url || (l.social_links && l.social_links.telegram) || `https://t.me/+${primaryDigits}`;
                        actHtml += `<a href="${tgUrl}" target="_blank" class="btn-act btn-act-tg" title="Открыть в Telegram">💬 TG</a>`;
                    } else {
                        // US / Europe: WhatsApp with English pitch + Direct Call
                        const enPitch = encodeURIComponent(l.ai_pitch || `Hi! I noticed your business "${l.name}" on Google Maps. We specialize in building high-converting websites. Are you open to new clients?`);
                        actHtml += `<a href="https://wa.me/${primaryDigits}?text=${enPitch}" target="_blank" class="btn-act btn-act-wa" style="font-weight: 700; padding: 4px 10px;" title="Send WhatsApp Message">🟢 WA</a>`;
                        actHtml += `<a href="tel:${primaryPhone}" class="btn-act" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4);" title="Direct Call">📞 Call</a>`;
                    }

                    // Copy Phone
                    actHtml += `<button onclick="copyPhone('${primaryPhone}')" class="btn-act" title="Скопировать номер телефона">📋</button>`;
                }
                actHtml += `</div>`;

                let srcBadge = `<span style="font-size: 11px; padding: 2px 6px; background: var(--surface-hover); border: 1px solid var(--border); border-radius: 4px; white-space: nowrap;">${l.source}</span>`;
                if (l.source === 'Google Maps') {
                    srcBadge = `<span class="badge badge-google">Google Maps</span>`;
                }

                html += `<tr>
                    <td style="color: var(--text-dim); text-align: center;">${idx + 1}</td>
                    <td><span class="badge ${badgeClass}">${badgeText}</span></td>
                    <td>${nameStr}</td>
                    <td>${phoneStr}</td>
                    <td>${siteStr}</td>
                    <td style="text-align: center; white-space: nowrap;">${reviews}</td>
                    <td style="color: var(--text-dim); font-size: 12px; max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(fullAddr)}">${escapeHtml(fullAddr || '—')}</td>
                    <td>${srcBadge}</td>
                    <td>${actHtml}</td>
                </tr>`;
            });
            tbody.innerHTML = html;
        }

        function openPitchModal(idx) {
            const list = (currentDisplayedLeads && currentDisplayedLeads.length > 0) ? currentDisplayedLeads : allLeads;
            const lead = list[idx] || allLeads[idx];
            if (!lead) return;

            document.getElementById('modalOrgName').innerText = lead.name || 'Компания';
            const city = lead.city || 'Город не указан';
            const cat = lead.category || 'Ниша не указана';
            const rating = lead.rating ? `⭐ ${lead.rating} (${lead.reviews_count || 0} отз.)` : '';
            const phoneBadge = lead.is_mobile ? '📱 Мобильный' : (lead.primary_phone ? '☎️ Городской' : '');
            document.getElementById('modalOrgMeta').innerText = [city, cat, rating, phoneBadge].filter(Boolean).join(' • ');

            // Audit badges
            const bCont = document.getElementById('modalAuditBadges');
            if (lead.site_audit_summary) {
                bCont.innerHTML = lead.site_audit_summary.split(' | ').map(b => {
                    let cls = 'audit-tag';
                    if (b.includes('НЕТ МОБИЛКИ')) cls += ' audit-no-mobile';
                    else if (b.includes('КРУТЯТ РЕКЛАМУ')) cls += ' audit-ads';
                    else if (b.includes('НЕТ SSL')) cls += ' audit-no-ssl';
                    else if (b.includes('Медленный')) cls += ' audit-slow';
                    else cls += ' audit-cms';
                    return `<span class="${cls}">${escapeHtml(b)}</span>`;
                }).join('');
            } else if (lead.website_status && lead.website_status.includes('Нет сайта')) {
                bCont.innerHTML = '<span class="audit-tag audit-no-mobile">🔥 САЙТА НЕТ ВООБЩЕ - МАКСИМАЛЬНЫЙ ПОТЕНЦИАЛ СДЕЛКИ</span>';
            } else {
                bCont.innerHTML = '';
            }

            // Pitch & Call script with instant high-converting fallback
            const companyName = lead.name || 'вашу организацию';
            const cityStr = lead.city || 'вашем городе';
            const catStr = lead.category || 'вашей сфере';
            const reviewsMention = (lead.reviews_count && lead.reviews_count >= 5) 
                ? `отличный рейтинг ${lead.rating || ''} и ${lead.reviews_count} отзывов` 
                : 'хорошую репутацию на картах';

            const defaultPitch = `Здравствуйте! Увидел компанию «${companyName}» в г. ${cityStr} на картах — у вас ${reviewsMention}. Но заметил, что у вас еще нет современного продающего сайта / онлайн-записи. Из-за этого до 40% клиентов из поиска Яндекса и Google уходит к конкурентам. Мы разрабатываем быстрые сайты и Telegram Mini Apps для ${catStr} за 3 дня с гарантией заявок. Давайте пришлю короткое демо, как это может выглядеть для вас?`;
            
            const defaultCall = `Здравствуйте! Меня зовут Евгений. Звоню коротко по делу: нашел организацию «${companyName}» на картах в г. ${cityStr}. Обратил внимание, что у вас нет собственного сайта, и клиенты из поисковиков уходят конкурентам. Мы делаем конверсионные сайты под ключ за 3 дня для ${catStr}. Хочу бесплатно прислать вам готовую структуру на оценку. Куда удобнее скинуть ссылку — в WhatsApp или Telegram?`;

            const pitch = lead.ai_pitch || defaultPitch;
            const call = lead.call_script || defaultCall;
            document.getElementById('modalPitchText').innerText = pitch;
            document.getElementById('modalCallText').innerText = call;

            const digits = lead.clean_phone_digits || (lead.primary_phone ? lead.primary_phone.replace(/\D/g, '') : '');
            const btnWA = document.getElementById('modalBtnWA');
            const btnTG = document.getElementById('modalBtnTG');

            if (digits) {
                btnWA.href = `https://wa.me/${digits}?text=${encodeURIComponent(pitch)}`;
                btnWA.style.display = 'inline-flex';
                btnTG.href = lead.telegram_url || `https://t.me/+${digits}`;
                btnTG.style.display = 'inline-flex';
            } else {
                btnWA.style.display = 'none';
                btnTG.style.display = 'none';
            }

            document.getElementById('pitchModal').classList.add('active');
        }

        function closePitchModal() {
            document.getElementById('pitchModal').classList.remove('active');
        }

        function copyModalPitch() {
            const txt = document.getElementById('modalPitchText').innerText;
            navigator.clipboard.writeText(txt).then(() => showToast('💬 Текст для WhatsApp/Telegram скопирован!'));
        }

        function copyModalCall() {
            const txt = document.getElementById('modalCallText').innerText;
            navigator.clipboard.writeText(txt).then(() => showToast('📞 Скрипт звонка скопирован!'));
        }

        // Settings API calls
        async function loadSettings() {
            try {
                const res = await fetch('/api/settings');
                const cfg = await res.json();
                if (cfg) {
                    document.getElementById('cfgBotToken').value = cfg.telegram_bot_token || '';
                    document.getElementById('cfgChatId').value = cfg.telegram_chat_id || '';
                    document.getElementById('cfgNotifyOnliner').checked = cfg.notify_onliner !== false;
                    document.getElementById('cfgNotifyKwork').checked = cfg.notify_kwork !== false;
                    document.getElementById('cfgNotifyFl').checked = cfg.notify_fl !== false;
                    document.getElementById('cfgInterval').value = cfg.monitor_interval_minutes || 3;
                    document.getElementById('cfgGeminiKey').value = cfg.gemini_api_key || '';
                }
            } catch (e) {
                console.error('Error loading settings:', e);
            }
        }

        async function saveSettingsForm() {
            const payload = {
                telegram_bot_token: document.getElementById('cfgBotToken').value.trim(),
                telegram_chat_id: document.getElementById('cfgChatId').value.trim(),
                notify_onliner: document.getElementById('cfgNotifyOnliner').checked,
                notify_kwork: document.getElementById('cfgNotifyKwork').checked,
                notify_fl: document.getElementById('cfgNotifyFl').checked,
                monitor_interval_minutes: parseInt(document.getElementById('cfgInterval').value) || 3,
                gemini_api_key: document.getElementById('cfgGeminiKey').value.trim(),
            };

            try {
                const res = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (data.success) {
                    showToast('✅ Настройки успешно сохранены!');
                    checkWatcherStatus();
                } else {
                    showToast('❌ Ошибка сохранения настроек');
                }
            } catch (e) {
                showToast('❌ Ошибка сети: ' + e);
            }
        }

        async function testTelegramAlert() {
            const st = document.getElementById('testTgStatus');
            st.innerText = 'Отправка...';
            st.style.color = 'var(--text-dim)';
            try {
                const res = await fetch('/api/test-telegram', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bot_token: document.getElementById('cfgBotToken').value.trim(),
                        chat_id: document.getElementById('cfgChatId').value.trim()
                    })
                });
                const data = await res.json();
                if (data.success) {
                    st.innerText = '✅ Сообщение успешно доставлено!';
                    st.style.color = '#10b981';
                    showToast('✅ Проверьте ваш Telegram!');
                } else {
                    st.innerText = '❌ ' + (data.message || 'Ошибка');
                    st.style.color = '#ef4444';
                }
            } catch (e) {
                st.innerText = '❌ Ошибка сети: ' + e;
                st.style.color = '#ef4444';
            }
        }

        async function toggleWatcher() {
            try {
                const res = await fetch('/api/watcher/toggle', { method: 'POST' });
                const data = await res.json();
                checkWatcherStatus();
                if (data.is_running) {
                    showToast('▶️ Фоновый мониторинг Onliner & бирж запущен!');
                } else {
                    showToast('⏹️ Фоновый мониторинг остановлен.');
                }
            } catch (e) {
                showToast('❌ Ошибка: ' + e);
            }
        }

        async function checkWatcherStatus() {
            try {
                const res = await fetch('/api/watcher/status');
                const data = await res.json();
                const btn = document.getElementById('btnToggleWatcher');
                const txt = document.getElementById('watcherStatusText');
                const badge = document.getElementById('watcherActiveBadge');

                if (data.is_running) {
                    if (btn) {
                        btn.className = 'btn btn-secondary';
                        btn.innerText = '⏹️ Остановить мониторинг';
                    }
                    if (txt) txt.innerHTML = `<span style="color:#10b981; font-weight:700;">● Активен</span> (найдено новых: ${data.orders_count || 0})`;
                    if (badge) badge.style.display = 'inline-block';
                } else {
                    if (btn) {
                        btn.className = 'btn btn-primary';
                        btn.innerText = '▶️ Запустить фоновый мониторинг';
                    }
                    if (txt) txt.innerText = 'Статус: Остановлен';
                    if (badge) badge.style.display = 'none';
                }
            } catch (e) {}
        }

        function renderFreelanceTable(orders, isFiltered = false) {
            if (!isFiltered) {
                allOrders = orders || [];
            }
            const tbody = document.getElementById('freelanceTableBody');
            const counter = document.getElementById('flTableCounter');

            if (!orders || orders.length === 0) {
                if (isFiltered) {
                    tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-dim); padding: 30px;">По фильтру ничего не найдено</td></tr>';
                    if (counter) counter.innerText = `Показано 0 из ${allOrders.length}`;
                } else {
                    if (counter) counter.innerText = '';
                }
                return;
            }

            if (counter) {
                counter.innerText = isFiltered ? `Показано ${orders.length} из ${allOrders.length}` : `Всего заказов: ${orders.length}`;
            }

            let html = '';
            orders.forEach((o, idx) => {
                let badgeClass = 'badge-kwork';
                if (o.platform.includes('Onliner')) badgeClass = 'badge-onliner';
                else if (o.platform.includes('Kufar')) badgeClass = 'badge-kufar';
                else if (o.platform.includes('Telegram')) badgeClass = 'badge-tg';
                else if (o.platform === 'FL.ru') badgeClass = 'badge-fl';
                else if (o.platform === 'Freelancehunt') badgeClass = 'badge-fh';
                else if (o.platform === 'Weblancer') badgeClass = 'badge-wl';

                const titleStr = `<a href="${o.url}" target="_blank" style="color: var(--text); text-decoration: none; font-weight: 700;" title="Открыть на площадке">${escapeHtml(o.title)}</a>`;
                const descStr = o.description 
                    ? `<div style="font-size: 12px; color: var(--text-dim); margin-top: 4px; max-width: 500px; line-height: 1.4;">${escapeHtml(o.description.substring(0, 160))}${o.description.length > 160 ? '...' : ''}</div>`
                    : '';

                const meta = [o.proposals_count, o.date_posted].filter(Boolean).join(' • ') || '—';

                html += `<tr>
                    <td style="color: var(--text-dim); text-align: center;">${idx + 1}</td>
                    <td><span class="badge ${badgeClass}">${o.platform}</span></td>
                    <td>${titleStr}${descStr}</td>
                    <td><span class="badge badge-price">${escapeHtml(o.price || 'По договоренности')}</span></td>
                    <td style="color: var(--text-dim); font-size: 12px; white-space: nowrap;">${escapeHtml(meta)}</td>
                    <td style="text-align: center;">
                        <div class="actions-cell" style="justify-content: center;">
                            <a href="${o.url}" target="_blank" class="btn-act btn-act-proj" title="Перейти и оставить отклик / связаться с заказчиком">
                                Открыть заказ ↗
                            </a>
                            <button onclick="copyLink('${o.url}')" class="btn-act" title="Скопировать ссылку на заказ">
                                📋
                            </button>
                        </div>
                    </td>
                </tr>`;
            });
            tbody.innerHTML = html;
        }

        function downloadFile(type) {
            window.location.href = `/api/download?type=${type}`;
        }

        function downloadFreelance(type) {
            window.location.href = `/api/freelance/download?type=${type}`;
        }
    </script>
</body>
</html>
"""


async def run_search_task(
    query: str,
    city: str,
    source: str,
    filter_type: str,
    limit: int,
    skip_checked: bool = True,
    verify_web: bool = True,
):
    """Asynchronous background search runner with multi-city support and web search verification."""
    global CURRENT_STATE
    CURRENT_STATE["is_running"] = True
    CURRENT_STATE["leads"] = []
    CURRENT_STATE["total_target"] = limit
    CURRENT_STATE["skipped_count"] = 0
    CURRENT_STATE["progress_message"] = "Инициализация браузера..."

    # Parse multi-city input: supports "Минск, Брест", "Miami, FL", "Miami, FL, Houston, TX"
    if ";" in city:
        raw_cities = [c.strip() for c in city.split(";") if c.strip()]
    else:
        raw_cities = [c.strip() for c in re.split(r",(?!\s*[A-Za-z]{2}\b)", city) if c.strip()]
    cities = raw_cities if raw_cities else ["Miami, FL"]

    all_leads: List[Lead] = []
    seen = set()
    total_skipped = 0

    per_city_target = max(limit // len(cities), 10) if len(cities) > 1 else limit

    try:
        for city_idx, current_city in enumerate(cities, 1):
            if len(all_leads) >= limit:
                break

            city_label = current_city or "Беларусь"
            prefix = f"[{city_idx}/{len(cities)}] " if len(cities) > 1 else ""
            remaining_needed = limit - len(all_leads)
            curr_limit = min(per_city_target, remaining_needed) if len(cities) > 1 else remaining_needed

            def on_lead(lead: Lead):
                key = (lead.name.lower().strip(), lead.primary_phone)
                if key not in seen:
                    seen.add(key)
                    if not lead.ai_pitch:
                        enrich_lead_with_pitch(lead)
                    all_leads.append(lead)
                    CURRENT_STATE["leads"].append(lead.model_dump())
                    skip_text = f" (пропущено: {total_skipped})" if total_skipped > 0 else ""
                    CURRENT_STATE["progress_message"] = f"{prefix}{city_label}: собрано {len(CURRENT_STATE['leads'])} из {limit}{skip_text}..."

            def on_progress(msg: str):
                CURRENT_STATE["progress_message"] = f"{prefix}{city_label}: {msg}"

            # 1. Google Maps (USA / Europe / Worldwide)
            if source in ("google", "all") and len(all_leads) < limit:
                CURRENT_STATE["progress_message"] = f"{prefix}Поиск в Google Maps ({city_label})..."
                gmaps_scraper = GoogleMapsScraper(headless=True, on_lead_found=on_lead, on_progress=on_progress)
                try:
                    gmaps_leads = await gmaps_scraper.search(
                        query=query,
                        city=current_city,
                        limit=curr_limit,
                        filter_type=filter_type,
                        skip_checked=skip_checked,
                        verify_web=False,
                    )
                    total_skipped += getattr(gmaps_scraper, "skipped_checked_count", 0)
                    for l in gmaps_leads:
                        key = (l.name.lower().strip(), l.primary_phone)
                        if key not in seen:
                            seen.add(key)
                            if not l.ai_pitch:
                                enrich_lead_with_pitch(l)
                            all_leads.append(l)
                            CURRENT_STATE["leads"].append(l.model_dump())
                except Exception as e:
                    print(f"[WebUI] Google Maps error for {current_city}: {e}")

            # 2. Yandex Maps
            if source in ("yandex", "both", "all") and len(all_leads) < limit:
                CURRENT_STATE["progress_message"] = f"{prefix}Поиск в Яндекс Картах ({city_label})..."
                y_scraper = YandexScraper(headless=True, on_lead_found=on_lead, on_progress=on_progress)
                try:
                    y_leads = await y_scraper.search(
                        query=query,
                        city=current_city,
                        limit=curr_limit,
                        filter_type=filter_type,
                        skip_checked=skip_checked,
                    )
                    total_skipped += getattr(y_scraper, "skipped_checked_count", 0)
                    for l in y_leads:
                        key = (l.name.lower().strip(), l.primary_phone)
                        if key not in seen:
                            seen.add(key)
                            if not l.ai_pitch:
                                enrich_lead_with_pitch(l)
                            all_leads.append(l)
                            CURRENT_STATE["leads"].append(l.model_dump())
                except Exception as e:
                    print(f"[WebUI] Yandex error for {current_city}: {e}")

            # 3. 2GIS
            if source in ("2gis", "both", "all") and len(all_leads) < limit:
                g_limit = curr_limit if source == "2gis" else max(10, curr_limit - len([l for l in all_leads if l.city == current_city]))
                CURRENT_STATE["progress_message"] = f"{prefix}Поиск в 2ГИС ({city_label})..."
                g_scraper = TwoGisScraper(headless=True, on_lead_found=on_lead, on_progress=on_progress)
                try:
                    g_leads = await g_scraper.search(
                        query=query,
                        city=current_city,
                        limit=g_limit,
                        filter_no_website_only=(filter_type == "hot_only"),
                        skip_checked=skip_checked,
                    )
                    total_skipped += getattr(g_scraper, "skipped_checked_count", 0)
                    for l in g_leads:
                        key = (l.name.lower().strip(), l.primary_phone)
                        if key not in seen:
                            seen.add(key)
                            if not l.ai_pitch:
                                enrich_lead_with_pitch(l)
                            all_leads.append(l)
                            CURRENT_STATE["leads"].append(l.model_dump())
                except Exception as e:
                    print(f"[WebUI] 2GIS error for {current_city}: {e}")

        # Web Search Verification if requested by user
        if verify_web and all_leads:
            CURRENT_STATE["progress_message"] = f"🌐 Проверка наличия сайтов в сети ({len(all_leads)} компаний)..."
            for idx, lead in enumerate(all_leads, 1):
                if lead.source != "Google Maps" and (not lead.website or lead.website_status in (WebsiteStatus.NO_WEBSITE, WebsiteStatus.TAPLINK)):
                    try:
                        has_site, detected_site = await verify_company_website(lead.name, lead.city)
                        if has_site and detected_site:
                            status, priority = classify_website(detected_site)
                            if status != WebsiteStatus.NO_WEBSITE:
                                lead.website = detected_site
                                lead.website_status = status
                                lead.lead_priority = priority
                                lead.notes = f"🌐 Найден сайт в поиске: {detected_site}"
                        else:
                            lead.notes = "✅ 100% подтверждено поиском: сайта в интернете нет"
                    except Exception:
                        pass
                if idx % 5 == 0:
                    CURRENT_STATE["progress_message"] = f"🌐 Проверено в сети: {idx}/{len(all_leads)} компаний..."

        # Express Website Audit & AI Pitch Enrichment
        if all_leads:
            CURRENT_STATE["progress_message"] = f"🔍 Экспресс-аудит сайтов и подготовка AI-питчей ({len(all_leads)} компаний)..."
            cfg = load_settings()
            gemini_key = cfg.get("gemini_api_key", "")
            for idx, lead in enumerate(all_leads, 1):
                try:
                    if lead.website and lead.website_status not in (WebsiteStatus.NO_WEBSITE, WebsiteStatus.SOCIAL, WebsiteStatus.TAPLINK):
                        await audit_lead_website(lead)
                    enrich_lead_with_pitch(lead, gemini_api_key=gemini_key)
                except Exception:
                    pass
                if idx % 5 == 0:
                    CURRENT_STATE["progress_message"] = f"💡 Аудит и AI-питчи: {idx}/{len(all_leads)}..."

        # Strict Filtering logic
        if filter_type == "hot_only":
            filtered = [l for l in all_leads if l.lead_priority == LeadPriority.HIGH and (not l.website or l.website_status == WebsiteStatus.NO_WEBSITE)]
        elif filter_type == "social_only":
            filtered = [l for l in all_leads if l.lead_priority == LeadPriority.MEDIUM]
        elif filter_type == "hot_warm":
            filtered = [l for l in all_leads if l.lead_priority in (LeadPriority.HIGH, LeadPriority.MEDIUM)]
        else:
            filtered = all_leads

        # Sort priority
        order = {LeadPriority.HIGH: 0, LeadPriority.MEDIUM: 1, LeadPriority.LOW: 2}
        filtered.sort(key=lambda x: (order.get(x.lead_priority, 3), -(x.reviews_count or 0)))

        # Update global state
        final_export_list = filtered[:limit]
        CURRENT_STATE["leads"] = [l.model_dump() for l in final_export_list]

        # Auto-export
        ts = datetime.now().strftime("%Y-%m-%d_%H%M")
        safe_q = "".join(c for c in query if c.isalnum() or c in (" ", "_")).strip().replace(" ", "_")
        excel_name = f"leads_{safe_q}_{ts}.xlsx"
        csv_name = f"leads_{safe_q}_{ts}.csv"

        CURRENT_STATE["last_excel_path"] = export_to_excel(final_export_list, excel_name)
        CURRENT_STATE["last_csv_path"] = export_to_csv(final_export_list, csv_name)

        CURRENT_STATE["skipped_count"] = total_skipped
        CURRENT_STATE["memory_stats"] = memory_db.get_stats()
        skip_msg = f" (пропущено ранее проверенных: {total_skipped})" if total_skipped > 0 else ""
        if len(final_export_list) > 0:
            CURRENT_STATE["progress_message"] = f"Сбор успешно завершен! Найдено {len(final_export_list)} лидов{skip_msg}."
        elif len(all_leads) > 0:
            CURRENT_STATE["progress_message"] = f"Собрано {len(all_leads)} компаний, но у всех есть свои сайты (не подошли под строгий фильтр без сайта). Выберите фильтр 'Все организации'."
        elif total_skipped > 0:
            CURRENT_STATE["progress_message"] = f"Все компании ({total_skipped}) уже были проверены ранее. Снимите галочку 'Не парсить проверенные' или очистите память."
        else:
            CURRENT_STATE["progress_message"] = "Организаций по данному запросу не найдено. Попробуйте изменить нишу или город."

    except Exception as e:
        CURRENT_STATE["progress_message"] = f"Ошибка сбора: {e}"
    finally:
        CURRENT_STATE["is_running"] = False


def start_async_task(
    query: str,
    city: str,
    source: str,
    filter_type: str,
    limit: int,
    skip_checked: bool = True,
    verify_web: bool = True,
):
    """Launches map async task in a dedicated background event loop."""
    def worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_search_task(query, city, source, filter_type, limit, skip_checked, verify_web))
        loop.close()

    t = threading.Thread(target=worker, daemon=True)
    t.start()


# ================= FREELANCE TASK RUNNER =================
async def run_freelance_task(query: str, platforms: List[str], limit: int):
    """Asynchronous background runner for scraping freelance exchanges, Onliner, and Telegram."""
    global FREELANCE_STATE
    FREELANCE_STATE["is_running"] = True
    FREELANCE_STATE["orders"] = []
    FREELANCE_STATE["total_target"] = limit
    FREELANCE_STATE["progress_message"] = "Подключение к биржам и Telegram..."

    def on_order(order: FreelanceOrder):
        FREELANCE_STATE["orders"].append(order.model_dump())
        FREELANCE_STATE["progress_message"] = f"Собрано {len(FREELANCE_STATE['orders'])} из {limit} заказов..."

    def on_progress(msg: str):
        FREELANCE_STATE["progress_message"] = msg

    aggregator = FreelanceAggregator(
        headless=True,
        on_order_found=on_order,
        on_progress=on_progress
    )

    try:
        final_orders = await aggregator.search(query=query, platforms=platforms, limit=limit)
        FREELANCE_STATE["orders"] = [o.model_dump() for o in final_orders]

        # Auto-export
        ts = datetime.now().strftime("%Y-%m-%d_%H%M")
        safe_q = "".join(c for c in query if c.isalnum() or c in (" ", "_")).strip().replace(" ", "_")
        excel_name = f"freelance_{safe_q}_{ts}.xlsx"
        csv_name = f"freelance_{safe_q}_{ts}.csv"

        FREELANCE_STATE["last_excel_path"] = export_freelance_to_excel(final_orders, excel_name)
        FREELANCE_STATE["last_csv_path"] = export_freelance_to_csv(final_orders, csv_name)
        FREELANCE_STATE["progress_message"] = f"Сбор завершен! Найдено {len(final_orders)} актуальных заказов."
    except Exception as e:
        FREELANCE_STATE["progress_message"] = f"Ошибка поиска заказов: {e}"
    finally:
        FREELANCE_STATE["is_running"] = False


def start_freelance_async_task(query: str, platforms: List[str], limit: int):
    """Launches freelance async task in background thread."""
    def worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_freelance_task(query, platforms, limit))
        loop.close()

    t = threading.Thread(target=worker, daemon=True)
    t.start()


def render_html_page() -> str:
    """Dynamically generates HTML with categorized niche options, datalists, and quick chips for both US/EU and CIS."""
    # 1. CIS Niches
    cis_categories: Dict[str, List[Dict[str, str]]] = {}
    for it in POPULAR_NICHES:
        if it.get("category", "").startswith("🇺🇸/🇪🇺"):
            continue
        cat = it["category"]
        if cat not in cis_categories:
            cis_categories[cat] = []
        cis_categories[cat].append(it)

    cis_opt_lines = []
    cis_dl_lines = []
    for cat, items in cis_categories.items():
        cis_opt_lines.append(f'  <optgroup label="{cat}">')
        for it in items:
            name = it["name"]
            icon = it["icon"]
            cis_opt_lines.append(f'    <option value="{name}">{icon} {name}</option>')
            cis_dl_lines.append(f'  <option value="{name}">')
        cis_opt_lines.append('  </optgroup>')

    cis_chip_lines = []
    for q in QUICK_NICHES:
        icon = next((it["icon"] for it in POPULAR_NICHES if it["name"] == q), "💼")
        cis_chip_lines.append(f'<button type="button" class="chip" onclick="setNiche(\'{q}\')">{icon} {q}</button>')

    # 2. US/EU High-Ticket Niches
    us_categories: Dict[str, List[Dict[str, str]]] = {}
    for it in US_EU_HIGH_TICKET_NICHES:
        cat = it.get("category", "🇺🇸/🇪🇺 High-Ticket")
        if cat not in us_categories:
            us_categories[cat] = []
        us_categories[cat].append(it)

    us_opt_lines = []
    us_dl_lines = []
    for cat, items in us_categories.items():
        us_opt_lines.append(f'  <optgroup label="{cat}">')
        for it in items:
            name = it["name"]
            icon = it.get("icon", "💼")
            us_opt_lines.append(f'    <option value="{name}">{icon} {name}</option>')
            us_dl_lines.append(f'  <option value="{name}">')
        us_opt_lines.append('  </optgroup>')

    us_chip_lines = []
    for q in QUICK_INTL_NICHES:
        icon = next((it.get("icon", "💼") for it in US_EU_HIGH_TICKET_NICHES if it["name"] == q), "💼")
        us_chip_lines.append(f'<button type="button" class="chip" onclick="setNiche(\'{q}\')">{icon} {q}</button>')

    us_city_lines = []
    for city in INTL_CITIES:
        flag = "🇺🇸" if any(s in city for s in ["FL", "NY", "CA", "TX", "IL"]) else ("🇬🇧" if "London" in city else "🇪🇺")
        us_city_lines.append(f'<button type="button" class="chip chip-city" onclick="setCities(\'{city}\')">{flag} {city}</button>')

    by_city_lines = [
        '<button type="button" class="chip chip-city" onclick="setCities(\'Минск\')">🇧🇾 Минск</button>',
        '<button type="button" class="chip chip-city" onclick="setCities(\'Минск, Брест, Гродно, Гомель, Витебск, Могилев\')">🇧🇾 Областные РБ</button>',
        '<button type="button" class="chip chip-city" onclick="setCities(\'Минск, Заславль, Фаниполь, Дзержинск, Смолевичи, Борисов\')">🇧🇾 Минский р-н</button>',
    ]
    for c in BY_CITIES:
        if c != "Минск":
            by_city_lines.append(f'<button type="button" class="chip chip-city" onclick="setCities(\'{c}\')">{c}</button>')
    by_city_lines.append('<button type="button" class="chip chip-city" onclick="setCities(\'Москва, Санкт-Петербург\')">🏙️ Мск + СПб</button>')

    html = HTML_TEMPLATE.replace("__NICHE_OPTIONS__", "\n".join(cis_opt_lines))
    html = html.replace("__NICHE_DATALIST__", "\n".join(cis_dl_lines))
    html = html.replace("__NICHE_CHIPS__", "\n".join(cis_chip_lines))
    html = html.replace("__BY_CITY_CHIPS__", "\n".join(by_city_lines))

    html = html.replace("__US_NICHE_OPTIONS__", "\n".join(us_opt_lines))
    html = html.replace("__US_NICHE_DATALIST__", "\n".join(us_dl_lines))
    html = html.replace("__US_NICHE_CHIPS__", "\n".join(us_chip_lines))
    html = html.replace("__US_CITY_CHIPS__", "\n".join(us_city_lines))
    return html


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(render_html_page().encode("utf-8"))

        elif path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(CURRENT_STATE, ensure_ascii=False).encode("utf-8"))

        elif path == "/api/freelance/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(FREELANCE_STATE, ensure_ascii=False).encode("utf-8"))

        elif path == "/api/memory/stats":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(memory_db.get_stats(), ensure_ascii=False).encode("utf-8"))

        elif path == "/api/download":
            query_params = urllib.parse.parse_qs(parsed.query)
            file_type = query_params.get("type", ["excel"])[0]

            filepath = (
                CURRENT_STATE["last_excel_path"]
                if file_type == "excel"
                else CURRENT_STATE["last_csv_path"]
            )

            if filepath and os.path.exists(filepath):
                filename = os.path.basename(filepath)
                self.send_response(200)
                content_type = (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    if file_type == "excel"
                    else "text/csv"
                )
                self.send_header("Content-Type", content_type)
                encoded_name = urllib.parse.quote(filename)
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{encoded_name}")
                self.end_headers()
                with open(filepath, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"File not found")

        elif path == "/api/freelance/download":
            query_params = urllib.parse.parse_qs(parsed.query)
            file_type = query_params.get("type", ["excel"])[0]

            filepath = (
                FREELANCE_STATE["last_excel_path"]
                if file_type == "excel"
                else FREELANCE_STATE["last_csv_path"]
            )

            if filepath and os.path.exists(filepath):
                filename = os.path.basename(filepath)
                self.send_response(200)
                content_type = (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    if file_type == "excel"
                    else "text/csv"
                )
                self.send_header("Content-Type", content_type)
                encoded_name = urllib.parse.quote(filename)
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{encoded_name}")
                self.end_headers()
                with open(filepath, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"File not found")

        elif path == "/api/settings":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(load_settings(), ensure_ascii=False).encode("utf-8"))

        elif path == "/api/watcher/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            status = {
                "is_running": freelance_watcher.is_running,
                "orders_count": freelance_watcher.orders_found_count,
                "last_check": freelance_watcher.last_check_time,
            }
            self.wfile.write(json.dumps(status, ensure_ascii=False).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""

        if path == "/api/search":
            try:
                data = json.loads(body) if body else {}
                query = data.get("query", "")
                city = data.get("city", "Минск")
                source = data.get("source", "both")
                filter_type = data.get("filter", "hot_warm")
                limit = int(data.get("limit", 50))
                skip_checked = bool(data.get("skip_checked", True))
                verify_web = bool(data.get("verify_web", True))

                start_async_task(query, city, source, filter_type, limit, skip_checked, verify_web)

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "started"}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif path == "/api/freelance/search":
            try:
                data = json.loads(body) if body else {}
                query = data.get("query", "разработка сайта")
                platforms = data.get("platforms", ["onliner", "telegram", "kwork", "fl", "freelancehunt", "kufar"])
                limit = int(data.get("limit", 50))

                start_freelance_async_task(query, platforms, limit)

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "started"}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif path == "/api/settings":
            try:
                data = json.loads(body) if body else {}
                saved = save_settings(data)
                if data.get("auto_monitor_enabled"):
                    if not freelance_watcher.is_running:
                        freelance_watcher.start()
                else:
                    if freelance_watcher.is_running:
                        freelance_watcher.stop()

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": saved}).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif path == "/api/test-telegram":
            try:
                data = json.loads(body) if body else {}
                token = data.get("bot_token")
                cid = data.get("chat_id")
                test_msg = (
                    "🚀 <b>Лид-Парсер: Тестовое уведомление!</b>\n\n"
                    "Связь с вашим Telegram успешно настроена. "
                    "Сюда будут мгновенно приходить новые заказы на разработку сайтов с Onliner и бирж фриланса."
                )
                ok, msg = send_telegram_alert(test_msg, bot_token=token, chat_id=cid)
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": ok, "message": msg}, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif path == "/api/watcher/toggle":
            try:
                cfg = load_settings()
                new_state = not freelance_watcher.is_running
                cfg["auto_monitor_enabled"] = new_state
                save_settings(cfg)
                if new_state:
                    freelance_watcher.start()
                else:
                    freelance_watcher.stop()

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"is_running": freelance_watcher.is_running}).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        elif path == "/api/memory/clear":
            try:
                deleted = memory_db.clear_memory()
                CURRENT_STATE["memory_stats"] = memory_db.get_stats()
                CURRENT_STATE["skipped_count"] = 0
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "deleted": deleted}, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not Found")

    def log_message(self, format, *args):
        # Suppress standard HTTP logs for clean console
        pass


def run_web(port: int = 8080):
    host = os.environ.get("HOST", "0.0.0.0")
    env_port = int(os.environ.get("PORT", port))
    server = HTTPServer((host, env_port), RequestHandler)
    print(f"\n=======================================================")
    print(f"🚀 Веб-интерфейс лид-парсера запущен на {host}:{env_port}!")
    print(f"👉 Откройте в браузере: http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{env_port}")
    print(f"=======================================================\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен.")


if __name__ == "__main__":
    run_web()
