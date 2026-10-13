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
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from typing import List, Dict, Any, Optional

from core.models import (
    Lead, LeadPriority, WebsiteStatus, FreelanceOrder,
    classify_website, unwrap_and_clean_url
)
from core.exporter import export_to_excel, export_to_csv, export_freelance_to_excel, export_freelance_to_csv
from core.niches import (
    POPULAR_NICHES, QUICK_NICHES,
    US_EU_HIGH_TICKET_NICHES, QUICK_INTL_NICHES, INTL_CITIES, BY_CITIES,
    clean_map_query
)
from core.memory import memory_db
from core.web_verifier import verify_company_website, verify_company_website_sync
from core.site_auditor import audit_lead_website
from core.ai_pitcher import enrich_lead_with_pitch
from core.notifier import load_settings, save_settings, send_telegram_alert
from scrapers.twogis import TwoGisScraper
from scrapers.yandex import YandexScraper
from scrapers.google import GoogleMapsScraper
from scrapers.freelance import FreelanceAggregator, freelance_watcher

STATE_LOCK = threading.Lock()

# Global state for Maps Lead Search
CURRENT_STATE = {
    "is_running": False,
    "cancel_requested": False,
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
<html lang="ru" data-theme="obsidian">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LeadParser — Поиск клиентов и заказов</title>
    <style>
        /* ==================== MINIMALIST COLOR THEMES ==================== */
        :root, [data-theme="mono-dark"], [data-theme="dark"], [data-theme="graphite"] {
            --bg: #000000;
            --surface: #0a0a0a;
            --surface-hover: #141414;
            --surface-subtle: #101012;
            --primary: #ffffff;
            --primary-hover: #e4e4e7;
            --primary-fg: #000000;
            --accent-subtle: rgba(255, 255, 255, 0.08);
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --text: #f4f4f5;
            --text-dim: #a1a1aa;
            --text-muted: #71717a;
            --border: #222225;
            --border-hover: #35353a;
            --input-bg: #050505;
            --row-hover: rgba(255, 255, 255, 0.02);
            --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.5);
            --shadow-lg: 0 16px 36px -8px rgba(0, 0, 0, 0.8);
        }

        [data-theme="mono-light"], [data-theme="light"], [data-theme="paper"] {
            --bg: #ffffff;
            --surface: #fafafa;
            --surface-hover: #f4f4f5;
            --surface-subtle: #f4f4f5;
            --primary: #09090b;
            --primary-hover: #18181b;
            --primary-fg: #ffffff;
            --accent-subtle: rgba(0, 0, 0, 0.06);
            --success: #059669;
            --warning: #d97706;
            --danger: #dc2626;
            --text: #09090b;
            --text-dim: #52525b;
            --text-muted: #a1a1aa;
            --border: #e4e4e7;
            --border-hover: #d4d4d8;
            --input-bg: #ffffff;
            --row-hover: rgba(0, 0, 0, 0.015);
            --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.04);
            --shadow-lg: 0 16px 36px -8px rgba(0, 0, 0, 0.1);
        }

        [data-theme="slate"] {
            --bg: #0b0f17;
            --surface: #111827;
            --surface-hover: #1e293b;
            --surface-subtle: #162032;
            --primary: #38bdf8;
            --primary-hover: #0ea5e9;
            --primary-fg: #082f49;
            --accent-subtle: rgba(56, 189, 248, 0.12);
            --success: #34d399;
            --warning: #fbbf24;
            --danger: #f87171;
            --text: #f8fafc;
            --text-dim: #94a3b8;
            --text-muted: #64748b;
            --border: #1e293b;
            --border-hover: #334155;
            --input-bg: #0b0f17;
            --row-hover: rgba(56, 189, 248, 0.025);
            --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.45);
            --shadow-lg: 0 16px 36px -8px rgba(0, 0, 0, 0.7);
        }

        [data-theme="sand"] {
            --bg: #f8f6f0;
            --surface: #ffffff;
            --surface-hover: #f1ede4;
            --surface-subtle: #f4f0e8;
            --primary: #78350f;
            --primary-hover: #92400e;
            --primary-fg: #ffffff;
            --accent-subtle: rgba(120, 53, 15, 0.08);
            --success: #047857;
            --warning: #b45309;
            --danger: #b91c1c;
            --text: #1c1917;
            --text-dim: #57534e;
            --text-muted: #a8a29e;
            --border: #e6e0d4;
            --border-hover: #d5cebf;
            --input-bg: #ffffff;
            --row-hover: rgba(28, 25, 23, 0.02);
            --shadow-sm: 0 1px 2px rgba(28, 25, 23, 0.04);
            --shadow-lg: 0 16px 36px -8px rgba(28, 25, 23, 0.12);
        }

        [data-theme="nordic"], [data-theme="nord"], [data-theme="tokyo"] {
            --bg: #0d1117;
            --surface: #161b22;
            --surface-hover: #21262d;
            --surface-subtle: #1c2128;
            --primary: #58a6ff;
            --primary-hover: #388bfd;
            --primary-fg: #0d1117;
            --accent-subtle: rgba(88, 166, 255, 0.12);
            --success: #3fb950;
            --warning: #d29922;
            --danger: #f85149;
            --text: #e6edf3;
            --text-dim: #8b949e;
            --text-muted: #6e7681;
            --border: #30363d;
            --border-hover: #484f58;
            --input-bg: #0d1117;
            --row-hover: rgba(88, 166, 255, 0.025);
            --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.45);
            --shadow-lg: 0 16px 36px -8px rgba(0, 0, 0, 0.7);
        }

        [data-theme="forest"], [data-theme="emerald"] {
            --bg: #070e0a;
            --surface: #0d1712;
            --surface-hover: #15241d;
            --surface-subtle: #101d16;
            --primary: #10b981;
            --primary-hover: #059669;
            --primary-fg: #022c22;
            --accent-subtle: rgba(16, 185, 129, 0.12);
            --success: #34d399;
            --warning: #fbbf24;
            --danger: #f87171;
            --text: #ecfdf5;
            --text-dim: #86efac;
            --text-muted: #4ade80;
            --border: #182e22;
            --border-hover: #264a37;
            --input-bg: #070e0a;
            --row-hover: rgba(16, 185, 129, 0.025);
            --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.5);
            --shadow-lg: 0 16px 36px -8px rgba(0, 0, 0, 0.75);
        }

        [data-theme="obsidian"] {
            --bg: #09090b;
            --surface: #121215;
            --surface-hover: #1c1c21;
            --surface-subtle: #16161a;
            --primary: #6366f1;
            --primary-hover: #4f46e5;
            --primary-fg: #ffffff;
            --accent-subtle: rgba(99, 102, 241, 0.12);
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --text: #fafafa;
            --text-dim: #a1a1aa;
            --text-muted: #71717a;
            --border: #27272a;
            --border-hover: #3f3f46;
            --input-bg: #09090b;
            --row-hover: rgba(255, 255, 255, 0.025);
            --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.4);
            --shadow-lg: 0 16px 36px -8px rgba(0, 0, 0, 0.7);
        }

        [data-theme="amber-void"], [data-theme="cyberpunk"] {
            --bg: #080808;
            --surface: #121212;
            --surface-hover: #1a1a1a;
            --surface-subtle: #161616;
            --primary: #f59e0b;
            --primary-hover: #d97706;
            --primary-fg: #1c1917;
            --accent-subtle: rgba(245, 158, 11, 0.12);
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --text: #f5f5f4;
            --text-dim: #a8a29e;
            --text-muted: #78716c;
            --border: #242424;
            --border-hover: #383838;
            --input-bg: #080808;
            --row-hover: rgba(245, 158, 11, 0.025);
            --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.5);
            --shadow-lg: 0 16px 36px -8px rgba(0, 0, 0, 0.75);
        }

        /* ==================== BASE & TYPOGRAPHY ==================== */
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            -webkit-font-smoothing: antialiased;
        }
        body {
            background-color: var(--bg);
            color: var(--text);
            padding: 24px 28px;
            min-height: 100vh;
            line-height: 1.45;
            transition: background-color 180ms ease-out, color 180ms ease-out;
        }
        .container {
            max-width: 1420px;
            margin: 0 auto;
        }

        /* ==================== TOPBAR / HEADER ==================== */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
            padding-bottom: 18px;
            margin-bottom: 20px;
            border-bottom: 1px solid var(--border);
        }
        .brand-wrap {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .brand-mark {
            width: 32px;
            height: 32px;
            border-radius: 8px;
            background: var(--primary);
            color: var(--primary-fg);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
            font-size: 14px;
            letter-spacing: -0.03em;
        }
        header h1 {
            font-size: 18px;
            font-weight: 700;
            letter-spacing: -0.025em;
            color: var(--text);
        }
        header p {
            color: var(--text-dim);
            font-size: 12px;
            margin-top: 2px;
        }
        .header-controls {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }
        .control-pill {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: var(--surface);
            padding: 5px 10px;
            border-radius: 8px;
            border: 1px solid var(--border);
            font-size: 12px;
            color: var(--text-dim);
        }
        .theme-swatches {
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }
        .theme-dot {
            width: 14px;
            height: 14px;
            border-radius: 50%;
            border: 1px solid rgba(128, 128, 128, 0.4);
            cursor: pointer;
            padding: 0;
            transition: transform 140ms ease-out, border-color 140ms ease-out;
        }
        .theme-dot:hover {
            transform: scale(1.18);
            border-color: var(--text);
        }
        .theme-dot:active {
            transform: scale(0.95);
        }

        /* ==================== NAVIGATION TABS ==================== */
        .tabs-nav {
            display: inline-flex;
            gap: 4px;
            margin-bottom: 20px;
            background: var(--surface);
            padding: 4px;
            border-radius: 10px;
            border: 1px solid var(--border);
            flex-wrap: wrap;
        }
        .tab-btn {
            background: transparent;
            color: var(--text-dim);
            border: 1px solid transparent;
            padding: 8px 16px;
            border-radius: 7px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            transition: background-color 150ms ease-out, color 150ms ease-out, border-color 150ms ease-out, transform 120ms ease-out;
        }
        .tab-btn:hover {
            color: var(--text);
            background: var(--surface-hover);
        }
        .tab-btn:active {
            transform: scale(0.98);
        }
        .tab-btn.active {
            background: var(--bg);
            color: var(--text);
            border-color: var(--border);
            box-shadow: var(--shadow-sm);
        }
        .tab-badge {
            background: var(--surface-hover);
            color: var(--text-dim);
            border: 1px solid var(--border);
            padding: 1px 7px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 500;
        }
        .tab-btn.active .tab-badge {
            background: var(--accent-subtle);
            color: var(--primary);
            border-color: transparent;
        }

        .tab-content { display: none; }
        .tab-content.active { display: block; }

        /* ==================== SURFACES & FORMS ==================== */
        .card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 16px;
            box-shadow: var(--shadow-sm);
            transition: background-color 180ms ease-out, border-color 180ms ease-out;
        }
        .grid-form {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
            align-items: end;
        }
        label {
            display: block;
            font-size: 12px;
            font-weight: 500;
            margin-bottom: 6px;
            color: var(--text-dim);
        }
        input, select {
            width: 100%;
            padding: 9px 12px;
            background: var(--input-bg);
            border: 1px solid var(--border);
            border-radius: 7px;
            color: var(--text);
            font-size: 13px;
            outline: none;
            transition: border-color 150ms ease-out, background-color 150ms ease-out;
        }
        input:hover, select:hover {
            border-color: var(--border-hover);
        }
        input:focus, select:focus {
            border-color: var(--primary);
        }

        /* ==================== BUTTONS & CHIPS ==================== */
        .btn {
            padding: 9px 16px;
            border-radius: 7px;
            font-size: 13px;
            font-weight: 600;
            border: 1px solid transparent;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            text-decoration: none;
            transition: background-color 150ms ease-out, border-color 150ms ease-out, color 150ms ease-out, transform 120ms ease-out, opacity 150ms ease-out;
        }
        .btn:active:not(:disabled) {
            transform: scale(0.98);
        }
        .btn:disabled {
            opacity: 0.45;
            cursor: not-allowed;
        }
        .btn-primary {
            background: var(--primary);
            color: var(--primary-fg);
            width: 100%;
        }
        .btn-primary:hover:not(:disabled) {
            background: var(--primary-hover);
        }
        .btn-success {
            background: var(--success);
            color: #ffffff;
        }
        .btn-success:hover:not(:disabled) {
            opacity: 0.92;
        }
        .btn-secondary {
            background: var(--surface-subtle);
            color: var(--text);
            border-color: var(--border);
        }
        .btn-secondary:hover:not(:disabled) {
            background: var(--surface-hover);
            border-color: var(--border-hover);
        }

        .chip {
            background: var(--input-bg);
            border: 1px solid var(--border);
            color: var(--text-dim);
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 500;
            cursor: pointer;
            user-select: none;
            transition: background-color 140ms ease-out, border-color 140ms ease-out, color 140ms ease-out, transform 120ms ease-out;
        }
        .chip:hover {
            background: var(--surface-hover);
            border-color: var(--border-hover);
            color: var(--text);
        }
        .chip:active {
            transform: scale(0.97);
        }
        .chip-city {
            font-size: 11px;
            padding: 3px 8px;
        }

        /* ==================== REGION SEGMENTED TOGGLE ==================== */
        .region-toggle-wrap {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 10px;
            margin-bottom: 16px;
        }
        .region-toggle-btn {
            padding: 10px 14px;
            border-radius: 8px;
            border: 1px solid var(--border);
            background: var(--input-bg);
            color: var(--text-dim);
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 10px;
            text-align: left;
            transition: background-color 150ms ease-out, border-color 150ms ease-out, color 150ms ease-out, transform 120ms ease-out;
        }
        .region-toggle-btn:hover {
            border-color: var(--border-hover);
            color: var(--text);
        }
        .region-toggle-btn:active {
            transform: scale(0.99);
        }
        .region-toggle-btn.active-us,
        .region-toggle-btn.active-cis {
            border-color: var(--primary);
            background: var(--accent-subtle);
            color: var(--text);
        }

        /* ==================== STATS & PROGRESS ==================== */
        .stats-bar {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 12px;
            margin-bottom: 16px;
        }
        .stat-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 14px 16px;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .stat-label {
            font-size: 11px;
            font-weight: 500;
            color: var(--text-dim);
        }
        .stat-val {
            font-size: 22px;
            font-weight: 700;
            letter-spacing: -0.02em;
            font-variant-numeric: tabular-nums;
        }

        .progress-box { margin-bottom: 16px; display: none; }
        .progress-box.active { display: block; }
        .progress-bar-bg {
            width: 100%;
            height: 6px;
            background: var(--border);
            border-radius: 999px;
            overflow: hidden;
            margin-top: 8px;
        }
        .progress-bar-fill {
            height: 100%;
            width: 0%;
            background: var(--primary);
            transition: width 250ms ease-out;
        }

        /* ==================== DATA TABLE ==================== */
        .table-wrap {
            overflow-x: auto;
            max-height: 640px;
            border: 1px solid var(--border);
            border-radius: 8px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 13px;
            font-variant-numeric: tabular-nums;
        }
        th {
            background: var(--surface-subtle);
            padding: 10px 14px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: var(--text-dim);
            position: sticky;
            top: 0;
            z-index: 10;
            border-bottom: 1px solid var(--border);
        }
        td {
            padding: 10px 14px;
            border-bottom: 1px solid var(--border);
            vertical-align: middle;
        }
        tr:last-child td { border-bottom: none; }
        tr:hover { background: var(--row-hover); }

        /* ==================== BADGES & LINKS ==================== */
        .badge {
            display: inline-flex;
            align-items: center;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            white-space: nowrap;
            border: 1px solid transparent;
        }
        .badge-high { background: rgba(16, 185, 129, 0.12); color: var(--success); border-color: rgba(16, 185, 129, 0.28); }
        .badge-med { background: rgba(245, 158, 11, 0.12); color: var(--warning); border-color: rgba(245, 158, 11, 0.28); }
        .badge-low { background: var(--surface-subtle); color: var(--text-dim); border-color: var(--border); }

        .badge-onliner { background: rgba(234, 179, 8, 0.12); color: #eab308; border-color: rgba(234, 179, 8, 0.3); }
        .badge-kufar { background: rgba(20, 184, 166, 0.12); color: #14b8a6; border-color: rgba(20, 184, 166, 0.3); }
        .badge-tg { background: rgba(56, 189, 248, 0.12); color: #0ea5e9; border-color: rgba(56, 189, 248, 0.3); }
        .badge-kwork { background: rgba(168, 85, 247, 0.12); color: #a855f7; border-color: rgba(168, 85, 247, 0.3); }
        .badge-fl { background: rgba(59, 130, 246, 0.12); color: #3b82f6; border-color: rgba(59, 130, 246, 0.3); }
        .badge-fh { background: rgba(16, 185, 129, 0.12); color: #10b981; border-color: rgba(16, 185, 129, 0.3); }
        .badge-wl { background: rgba(249, 115, 22, 0.12); color: #f97316; border-color: rgba(249, 115, 22, 0.3); }
        .badge-price { background: rgba(16, 185, 129, 0.12); color: var(--success); border-color: rgba(16, 185, 129, 0.3); font-weight: 700; }
        .badge-google { background: var(--accent-subtle); color: var(--primary); border-color: var(--border); }

        a.org-link {
            color: var(--text);
            text-decoration: none;
            font-weight: 600;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            transition: color 140ms ease-out;
        }
        a.org-link:hover {
            color: var(--primary);
        }
        a.org-link .link-icon {
            font-size: 11px;
            color: var(--text-dim);
        }
        a.tel-link {
            color: var(--text);
            text-decoration: none;
            font-weight: 500;
            white-space: nowrap;
        }
        a.tel-link:hover { color: var(--primary); }
        a.site-link {
            color: var(--text-dim);
            text-decoration: none;
            max-width: 170px;
            display: inline-block;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        a.site-link:hover { color: var(--text); text-decoration: underline; }

        /* ==================== ROW ACTIONS ==================== */
        .actions-cell {
            display: flex;
            gap: 4px;
            align-items: center;
            white-space: nowrap;
        }
        .btn-act {
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 500;
            text-decoration: none;
            cursor: pointer;
            border: 1px solid var(--border);
            background: var(--surface-subtle);
            color: var(--text);
            display: inline-flex;
            align-items: center;
            gap: 4px;
            transition: background-color 140ms ease-out, border-color 140ms ease-out, color 140ms ease-out, transform 120ms ease-out;
        }
        .btn-act:hover {
            background: var(--surface-hover);
            border-color: var(--border-hover);
        }
        .btn-act:active {
            transform: scale(0.97);
        }
        .btn-act-vb { color: #a855f7; border-color: rgba(168, 85, 247, 0.3); }
        .btn-act-wa { color: var(--success); border-color: rgba(16, 185, 129, 0.3); }
        .btn-act-tg { color: #38bdf8; border-color: rgba(56, 189, 248, 0.3); }
        .btn-act-map { color: var(--text-dim); }
        .btn-act-proj { color: var(--primary); border-color: var(--border); font-weight: 600; }
        .btn-act-pitch {
            background: var(--accent-subtle);
            border-color: var(--border);
            color: var(--text);
            font-weight: 600;
        }

        .badge-mob {
            background: rgba(16, 185, 129, 0.12);
            color: var(--success);
            border: 1px solid rgba(16, 185, 129, 0.25);
            border-radius: 4px;
            padding: 1px 5px;
            font-size: 10px;
            font-weight: 600;
            margin-right: 5px;
        }
        .badge-land {
            background: var(--surface-subtle);
            color: var(--text-dim);
            border: 1px solid var(--border);
            border-radius: 4px;
            padding: 1px 5px;
            font-size: 10px;
            font-weight: 500;
            margin-right: 5px;
        }
        .audit-tag {
            display: inline-block;
            font-size: 10px;
            font-weight: 600;
            padding: 1px 6px;
            border-radius: 4px;
            margin-top: 3px;
            margin-right: 3px;
        }
        .audit-no-mobile { background: rgba(239, 68, 68, 0.14); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.3); }
        .audit-ads { background: rgba(245, 158, 11, 0.14); color: var(--warning); border: 1px solid rgba(245, 158, 11, 0.3); }
        .audit-no-ssl { background: rgba(244, 63, 94, 0.14); color: var(--danger); border: 1px solid rgba(244, 63, 94, 0.3); }
        .audit-slow { background: rgba(168, 85, 247, 0.14); color: #a855f7; border: 1px solid rgba(168, 85, 247, 0.3); }
        .audit-cms { background: var(--surface-subtle); color: var(--text-dim); border: 1px solid var(--border); }

        /* ==================== MODAL & TOAST ==================== */
        .modal-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.65);
            backdrop-filter: blur(3px);
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
            border-radius: 12px;
            max-width: 640px;
            width: 100%;
            max-height: 90vh;
            overflow-y: auto;
            padding: 24px;
            box-shadow: var(--shadow-lg);
            position: relative;
            animation: modalIn 180ms cubic-bezier(0.22, 1, 0.36, 1);
        }
        @keyframes modalIn {
            from { opacity: 0; transform: scale(0.96) translateY(4px); }
            to { opacity: 1; transform: scale(1) translateY(0); }
        }
        .modal-close {
            position: absolute;
            top: 16px;
            right: 16px;
            background: var(--surface-subtle);
            border: 1px solid var(--border);
            border-radius: 6px;
            width: 28px;
            height: 28px;
            color: var(--text-dim);
            font-size: 16px;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            transition: background-color 140ms ease-out, color 140ms ease-out;
        }
        .modal-close:hover {
            background: var(--surface-hover);
            color: var(--text);
        }
        .pitch-box {
            background: var(--input-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 12px 14px;
            margin-top: 6px;
            font-size: 13px;
            line-height: 1.55;
            white-space: pre-wrap;
            color: var(--text);
            user-select: all;
        }

        #toast {
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: var(--surface);
            color: var(--text);
            border: 1px solid var(--border);
            padding: 10px 16px;
            border-radius: 8px;
            font-weight: 500;
            font-size: 13px;
            box-shadow: var(--shadow-lg);
            z-index: 1000;
            display: none;
            animation: toastIn 160ms cubic-bezier(0.22, 1, 0.36, 1);
        }
        @keyframes toastIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="brand-wrap">
                <div class="brand-mark">LP</div>
                <div>
                    <h1>LeadParser</h1>
                    <p>Поиск бизнеса без сайтов (Google Maps, Яндекс, 2ГИС) и заказов с бирж</p>
                </div>
            </div>
            <div class="header-controls">
                <!-- Quick Theme Swatches + Select -->
                <div class="control-pill">
                    <div class="theme-swatches" title="Минималистичные темы оформления">
                        <button type="button" class="theme-dot" data-t="mono-dark" style="background:#000000; border-color:#555;" onclick="setTheme('mono-dark')" title="Mono Dark (OLED)"></button>
                        <button type="button" class="theme-dot" data-t="mono-light" style="background:#ffffff; border-color:#bbb;" onclick="setTheme('mono-light')" title="Mono Light (Studio)"></button>
                        <button type="button" class="theme-dot" data-t="slate" style="background:#0b0f17; border-color:#38bdf8;" onclick="setTheme('slate')" title="Slate Minimal"></button>
                        <button type="button" class="theme-dot" data-t="sand" style="background:#f8f6f0; border-color:#78350f;" onclick="setTheme('sand')" title="Warm Linen"></button>
                        <button type="button" class="theme-dot" data-t="nordic" style="background:#0d1117; border-color:#58a6ff;" onclick="setTheme('nordic')" title="Nordic Clean"></button>
                        <button type="button" class="theme-dot" data-t="forest" style="background:#070e0a; border-color:#10b981;" onclick="setTheme('forest')" title="Forest Zen"></button>
                        <button type="button" class="theme-dot" data-t="obsidian" style="background:#09090b; border-color:#6366f1;" onclick="setTheme('obsidian')" title="Obsidian Violet"></button>
                        <button type="button" class="theme-dot" data-t="amber-void" style="background:#080808; border-color:#f59e0b;" onclick="setTheme('amber-void')" title="Amber Void"></button>
                    </div>
                    <select id="themeSelect" onchange="setTheme(this.value)" style="width: auto; padding: 2px 6px; font-size: 12px; border: none; background: transparent; cursor: pointer; color: var(--text);">
                        <option value="mono-dark">Mono Dark (OLED)</option>
                        <option value="mono-light">Mono Light (Studio)</option>
                        <option value="slate">Slate Minimal</option>
                        <option value="sand">Warm Linen</option>
                        <option value="nordic">Nordic Clean</option>
                        <option value="forest">Forest Zen</option>
                        <option value="obsidian">Obsidian Violet</option>
                        <option value="amber-void">Amber Void</option>
                    </select>
                </div>

                <!-- Memory Counter -->
                <div class="control-pill">
                    <span>Память:</span>
                    <strong id="memCountBadge" style="color: var(--text); font-variant-numeric: tabular-nums;">0</strong>
                    <button type="button" onclick="clearMemory()" class="btn btn-secondary" style="padding: 2px 8px; font-size: 11px;" title="Очистить историю проверенных мест">
                        Сброс
                    </button>
                </div>
            </div>
        </header>

        <!-- Mode Switcher Tabs -->
        <div class="tabs-nav">
            <button type="button" class="tab-btn active" id="tabBtnMaps" onclick="switchTab('maps')">
                <span>Карты и организации</span>
                <span class="tab-badge">Google • Яндекс • 2ГИС</span>
            </button>
            <button type="button" class="tab-btn" id="tabBtnFreelance" onclick="switchTab('freelance')">
                <span>Биржи и Telegram</span>
                <span class="tab-badge">Onliner • Kufar • Kwork</span>
            </button>
            <button type="button" class="tab-btn" id="tabBtnSettings" onclick="switchTab('settings')">
                <span>Настройки</span>
                <span id="watcherActiveBadge" class="tab-badge" style="display:none; color: var(--success);">● Активен</span>
            </button>
        </div>

        <!-- ================= TAB 1: MAPS SEARCH ================= -->
        <div id="tabContentMaps" class="tab-content active">
            <div class="card">
                <!-- Region Switcher -->
                <div class="region-toggle-wrap">
                    <button type="button" id="regBtnUS" class="region-toggle-btn active-us" onclick="setRegion('us')">
                        <span style="font-size: 18px;">🇺🇸</span>
                        <div>
                            <div style="font-size: 13px; font-weight: 600; color: var(--text);">США и Европа (Google Maps)</div>
                            <div style="font-size: 11px; color: var(--text-dim);">High-Ticket ниши • WhatsApp и прямые звонки</div>
                        </div>
                    </button>
                    <button type="button" id="regBtnCIS" class="region-toggle-btn" onclick="setRegion('cis')">
                        <span style="font-size: 18px;">🇧🇾</span>
                        <div>
                            <div style="font-size: 13px; font-weight: 600; color: var(--text);">Беларусь и СНГ (Яндекс + 2ГИС)</div>
                            <div style="font-size: 11px; color: var(--text-dim);">Локальный бизнес • Viber, WhatsApp, Telegram</div>
                        </div>
                    </button>
                </div>

                <form id="searchForm" onsubmit="startSearch(event)">
                    <div class="grid-form">
                        <div style="grid-column: span 2;">
                            <label>Ниша или поисковый запрос</label>
                            <div style="display: flex; gap: 8px;">
                                <input type="text" id="query" list="nichesListUS" placeholder="например, Roofing Contractors или Стоматология" required value="Roofing Contractors">
                                <select id="nicheSelectUS" onchange="if(this.value){setNiche(this.value);}" style="width: auto; max-width: 240px;">
                                    <option value="">Каталог ниш США/ЕС...</option>
                                    __US_NICHE_OPTIONS__
                                </select>
                                <select id="nicheSelectCIS" onchange="if(this.value){setNiche(this.value);}" style="width: auto; max-width: 240px; display: none;">
                                    <option value="">Каталог ниш РБ/СНГ...</option>
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
                            <label>Город (или несколько через запятую)</label>
                            <input type="text" id="city" placeholder="например, Miami, FL или Минск" value="Miami, FL">
                            <div id="cityChipsUS" style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px;">
                                __US_CITY_CHIPS__
                            </div>
                            <div id="cityChipsCIS" style="display: none; flex-wrap: wrap; gap: 4px; margin-top: 6px;">
                                __BY_CITY_CHIPS__
                            </div>
                        </div>
                        <div>
                            <label>Источник</label>
                            <select id="source">
                                <option value="all" selected>Все источники (Google + Яндекс + 2ГИС)</option>
                                <option value="google">Google Maps</option>
                                <option value="both">Яндекс Карты + 2ГИС</option>
                                <option value="yandex">Яндекс Карты</option>
                                <option value="2gis">2ГИС</option>
                            </select>
                        </div>
                        <div>
                            <label>Фильтр сайтов</label>
                            <select id="filter">
                                <option value="hot_warm" selected>Без сайта + Соцсети / Taplink</option>
                                <option value="hot_only">Строго без сайта (100% чистые)</option>
                                <option value="social_only">Только соцсети / Taplink / Конструктор</option>
                                <option value="all">Все организации</option>
                            </select>
                        </div>
                        <div>
                            <label>Лимит</label>
                            <input type="number" id="limit" min="5" max="500" value="50">
                        </div>
                        <div>
                            <button type="submit" id="startBtn" class="btn btn-primary">
                                <span>Начать сбор</span>
                            </button>
                        </div>
                    </div>

                    <div style="margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); display: flex; flex-wrap: wrap; gap: 18px;">
                        <label style="display: inline-flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; font-size: 12px; color: var(--text-dim); margin: 0;">
                            <input type="checkbox" id="skipChecked" checked style="width: 15px; height: 15px; cursor: pointer; accent-color: var(--primary);">
                            <span>Пропускать ранее проверенные компании</span>
                        </label>
                        <label style="display: inline-flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; font-size: 12px; color: var(--text-dim); margin: 0;">
                            <input type="checkbox" id="verifyWeb" checked style="width: 15px; height: 15px; cursor: pointer; accent-color: var(--primary);">
                            <span>Проверять скрытые домены и поисковую выдачу (100% фильтр сайтов)</span>
                        </label>
                    </div>

                    <!-- US Niche Chips -->
                    <div id="nicheChipsUS" style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; align-items: center;">
                        <span style="font-size: 11px; color: var(--text-dim); font-weight: 500;">Быстрый выбор:</span>
                        __US_NICHE_CHIPS__
                    </div>

                    <!-- CIS Niche Chips -->
                    <div id="nicheChipsCIS" style="display: none; flex-wrap: wrap; gap: 6px; margin-top: 12px; align-items: center;">
                        <span style="font-size: 11px; color: var(--text-dim); font-weight: 500;">Быстрый выбор:</span>
                        __NICHE_CHIPS__
                    </div>
                </form>
            </div>

            <div class="progress-box" id="progressBox">
                <div style="display: flex; justify-content: space-between; font-size: 13px;">
                    <span id="progressMsg" style="color: var(--text); font-weight: 500;">Сбор данных...</span>
                    <span id="progressCount" style="color: var(--text-dim); font-variant-numeric: tabular-nums;">0 / 50</span>
                </div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill" id="progressBar"></div>
                </div>
            </div>

            <div class="stats-bar">
                <div class="stat-card">
                    <div class="stat-label">Найдено компаний</div>
                    <div class="stat-val" id="statTotal">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Без сайта (Горячие)</div>
                    <div class="stat-val" id="statHigh" style="color: var(--success);">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Соцсети / Taplink</div>
                    <div class="stat-val" id="statMed" style="color: var(--warning);">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">С телефоном</div>
                    <div class="stat-val" id="statPhones">0</div>
                </div>
            </div>

            <div class="card" style="padding: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 10px;">
                    <div>
                        <h2 style="font-size: 15px; font-weight: 600;">Результаты поиска</h2>
                        <div id="tableCounter" style="font-size: 12px; color: var(--text-dim); margin-top: 2px;"></div>
                    </div>
                    <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                        <input type="text" id="tableFilterInput" placeholder="Фильтр по таблице..." oninput="filterTable()" style="width: 220px; padding: 7px 11px; font-size: 12px;">
                        <button onclick="copyAllPhones()" class="btn btn-secondary" id="btnCopyPhones" disabled title="Скопировать все телефоны">
                            Копировать номера
                        </button>
                        <button onclick="downloadFile('excel')" class="btn btn-success" id="btnExcel" disabled>
                            Excel (.xlsx)
                        </button>
                        <button onclick="downloadFile('csv')" class="btn btn-secondary" id="btnCsv" disabled>
                            CSV
                        </button>
                    </div>
                </div>

                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th style="width: 42px;">#</th>
                                <th style="width: 145px;">Статус</th>
                                <th>Организация</th>
                                <th>Телефон</th>
                                <th>Сайт / Профиль</th>
                                <th>Рейтинг</th>
                                <th>Адрес</th>
                                <th>Источник</th>
                                <th style="width: 200px; text-align: right;">Действия</th>
                            </tr>
                        </thead>
                        <tbody id="leadsTableBody">
                            <tr>
                                <td colspan="9" style="text-align: center; color: var(--text-dim); padding: 40px;">
                                    Выберите нишу, город и нажмите «Начать сбор»
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
                            <label>Лимит заказов</label>
                            <input type="number" id="flLimit" min="10" max="200" value="50">
                        </div>
                        <div>
                            <button type="submit" id="flStartBtn" class="btn btn-primary">
                                <span>Найти заказы</span>
                            </button>
                        </div>
                    </div>

                    <!-- Platform Checkboxes -->
                    <div style="margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); display: flex; align-items: center; flex-wrap: wrap; gap: 14px;">
                        <span style="font-size: 12px; font-weight: 500; color: var(--text-dim);">Площадки:</span>
                        <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; font-size: 12px; margin: 0;">
                            <input type="checkbox" id="pfOnliner" checked style="width: 15px; height: 15px; accent-color: var(--primary);">
                            <span class="badge badge-onliner">Onliner Услуги</span>
                        </label>
                        <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; font-size: 12px; margin: 0;">
                            <input type="checkbox" id="pfTg" checked style="width: 15px; height: 15px; accent-color: var(--primary);">
                            <span class="badge badge-tg">Telegram</span>
                        </label>
                        <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; font-size: 12px; margin: 0;">
                            <input type="checkbox" id="pfKufar" style="width: 15px; height: 15px; accent-color: var(--primary);">
                            <span class="badge badge-kufar">Kufar</span>
                        </label>
                        <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; font-size: 12px; margin: 0;">
                            <input type="checkbox" id="pfKwork" checked style="width: 15px; height: 15px; accent-color: var(--primary);">
                            <span class="badge badge-kwork">Kwork</span>
                        </label>
                        <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; font-size: 12px; margin: 0;">
                            <input type="checkbox" id="pfFl" checked style="width: 15px; height: 15px; accent-color: var(--primary);">
                            <span class="badge badge-fl">FL.ru</span>
                        </label>
                        <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer; user-select: none; font-size: 12px; margin: 0;">
                            <input type="checkbox" id="pfFh" checked style="width: 15px; height: 15px; accent-color: var(--primary);">
                            <span class="badge badge-fh">Freelancehunt</span>
                        </label>
                    </div>

                    <!-- Keyword Presets Chips -->
                    <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; align-items: center;">
                        <span style="font-size: 11px; color: var(--text-dim); font-weight: 500;">Тематики:</span>
                        <button type="button" class="chip" onclick="setFlQuery('разработка сайта под ключ')">Сайт под ключ</button>
                        <button type="button" class="chip" onclick="setFlQuery('лендинг')">Лендинг</button>
                        <button type="button" class="chip" onclick="setFlQuery('интернет-магазин')">Интернет-магазин</button>
                        <button type="button" class="chip" onclick="setFlQuery('tilda')">Tilda / No-Code</button>
                        <button type="button" class="chip" onclick="setFlQuery('доработка сайта')">Доработка сайта</button>
                        <button type="button" class="chip" onclick="setFlQuery('верстка')">Верстка / Frontend</button>
                        <button type="button" class="chip" onclick="setFlQuery('wordpress')">WordPress</button>
                    </div>
                </form>
            </div>

            <!-- Freelance Progress Box -->
            <div class="progress-box" id="flProgressBox">
                <div style="display: flex; justify-content: space-between; font-size: 13px;">
                    <span id="flProgressMsg" style="color: var(--text); font-weight: 500;">Поиск заказов...</span>
                    <span id="flProgressCount" style="color: var(--text-dim);">0 / 50</span>
                </div>
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill" id="flProgressBar"></div>
                </div>
            </div>

            <!-- Freelance Stats Bar -->
            <div class="stats-bar">
                <div class="stat-card">
                    <div class="stat-label">Всего заказов</div>
                    <div class="stat-val" id="statFlTotal">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">С указанным бюджетом</div>
                    <div class="stat-val" id="statFlPriced" style="color: var(--success);">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Беларусь (Onliner / Kufar)</div>
                    <div class="stat-val" id="statFlBy" style="color: var(--warning);">0</div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">Telegram и биржи</div>
                    <div class="stat-val" id="statFlTg">0</div>
                </div>
            </div>

            <!-- Freelance Table Card -->
            <div class="card" style="padding: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 10px;">
                    <div>
                        <h2 style="font-size: 15px; font-weight: 600;">Свежие заказы</h2>
                        <div id="flTableCounter" style="font-size: 12px; color: var(--text-dim); margin-top: 2px;"></div>
                    </div>
                    <div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap;">
                        <input type="text" id="flTableFilterInput" placeholder="Фильтр по заказам..." oninput="filterFreelanceTable()" style="width: 220px; padding: 7px 11px; font-size: 12px;">
                        <button onclick="downloadFreelance('excel')" class="btn btn-success" id="btnFlExcel" disabled>
                            Excel (.xlsx)
                        </button>
                        <button onclick="downloadFreelance('csv')" class="btn btn-secondary" id="btnFlCsv" disabled>
                            CSV
                        </button>
                    </div>
                </div>

                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th style="width: 42px;">#</th>
                                <th style="width: 140px;">Площадка</th>
                                <th>Заказ</th>
                                <th style="width: 160px;">Бюджет</th>
                                <th>Инфо</th>
                                <th style="width: 170px; text-align: right;">Действия</th>
                            </tr>
                        </thead>
                        <tbody id="freelanceTableBody">
                            <tr>
                                <td colspan="6" style="text-align: center; color: var(--text-dim); padding: 40px;">
                                    Выберите тематику и нажмите «Найти заказы»
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
                <h2 style="font-size: 16px; font-weight: 600; margin-bottom: 4px;">Telegram-уведомления и мониторинг</h2>
                <p style="color: var(--text-dim); font-size: 12px; margin-bottom: 18px;">
                    Мгновенные уведомления в Telegram при появлении новых заказов на разработку сайтов.
                </p>

                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; margin-bottom: 16px;">
                    <div>
                        <label>Telegram Bot Token</label>
                        <input type="text" id="cfgBotToken" placeholder="7123456789:AAH_..." style="font-family: monospace; font-size: 12px;">
                    </div>
                    <div>
                        <label>Telegram Chat ID</label>
                        <input type="text" id="cfgChatId" placeholder="123456789 или @channel" style="font-family: monospace; font-size: 12px;">
                    </div>
                </div>

                <div style="margin-bottom: 18px;">
                    <button type="button" onclick="testTelegramAlert()" class="btn btn-secondary">
                        Отправить тестовое сообщение
                    </button>
                    <span id="testTgStatus" style="margin-left: 10px; font-size: 12px; font-weight: 500;"></span>
                </div>

                <hr style="border: none; border-top: 1px solid var(--border); margin: 18px 0;">

                <h3 style="font-size: 14px; font-weight: 600; margin-bottom: 10px;">Фоновый авто-мониторинг</h3>
                
                <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 14px;">
                    <button type="button" id="btnToggleWatcher" onclick="toggleWatcher()" class="btn btn-primary" style="width: auto;">
                        Запустить мониторинг
                    </button>
                    <span id="watcherStatusText" style="font-size: 12px; color: var(--text-dim);">Статус: Остановлен</span>
                </div>

                <div style="display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 16px;">
                    <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer; margin: 0;">
                        <input type="checkbox" id="cfgNotifyOnliner" checked style="width: auto;"> Onliner Услуги
                    </label>
                    <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer; margin: 0;">
                        <input type="checkbox" id="cfgNotifyKwork" checked style="width: auto;"> Kwork
                    </label>
                    <label style="display: inline-flex; align-items: center; gap: 6px; cursor: pointer; margin: 0;">
                        <input type="checkbox" id="cfgNotifyFl" checked style="width: auto;"> FL.ru
                    </label>
                </div>

                <div style="max-width: 220px; margin-bottom: 18px;">
                    <label>Интервал проверки (мин)</label>
                    <input type="number" id="cfgInterval" min="1" max="60" value="3">
                </div>

                <hr style="border: none; border-top: 1px solid var(--border); margin: 18px 0;">

                <h3 style="font-size: 14px; font-weight: 600; margin-bottom: 4px;">Google Gemini API (Опционально)</h3>
                <p style="color: var(--text-dim); font-size: 12px; margin-bottom: 10px;">
                    Офферы формируются автоматически встроенным генератором. Укажите ключ Gemini, если нужна генерация через LLM.
                </p>
                <div style="max-width: 420px; margin-bottom: 18px;">
                    <label>Gemini API Key</label>
                    <input type="password" id="cfgGeminiKey" placeholder="AIzaSy..." style="font-family: monospace;">
                </div>

                <button type="button" onclick="saveSettingsForm()" class="btn btn-success">
                    Сохранить настройки
                </button>
            </div>
        </div>

    </div>

    <!-- Modal: AI Pitch & Cold Call Script -->
    <div id="pitchModal" class="modal-overlay" onclick="if(event.target===this)closePitchModal()">
        <div class="modal-card">
            <button type="button" class="modal-close" onclick="closePitchModal()">&times;</button>

            <div style="margin-bottom: 14px;">
                <h2 id="modalOrgName" style="font-size: 16px; font-weight: 600;">Название компании</h2>
                <div id="modalOrgMeta" style="font-size: 12px; color: var(--text-dim); margin-top: 2px;">Город • Ниша</div>
            </div>

            <div id="modalAuditBadges" style="margin-bottom: 14px;"></div>

            <!-- WhatsApp / Telegram Pitch -->
            <div style="margin-bottom: 18px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <label style="margin: 0; font-weight: 600; color: var(--text);">Персональный оффер (WhatsApp / Telegram / Viber)</label>
                    <button type="button" onclick="copyModalPitch()" class="btn btn-secondary" style="padding: 3px 10px; font-size: 11px;">
                        Копировать
                    </button>
                </div>
                <div id="modalPitchText" class="pitch-box"></div>
                <div style="display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap;">
                    <a id="modalBtnWA" href="#" target="_blank" class="btn btn-act-wa" style="text-decoration: none; padding: 6px 12px; font-size: 12px;">Открыть в WhatsApp</a>
                    <a id="modalBtnTG" href="#" target="_blank" class="btn btn-act-tg" style="text-decoration: none; padding: 6px 12px; font-size: 12px;">Открыть в Telegram</a>
                </div>
            </div>

            <!-- Cold Call Script -->
            <div>
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <label style="margin: 0; font-weight: 600; color: var(--text);">Скрипт звонка (30 сек)</label>
                    <button type="button" onclick="copyModalCall()" class="btn btn-secondary" style="padding: 3px 10px; font-size: 11px;">
                        Копировать
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
            document.querySelectorAll('.theme-dot').forEach(dot => {
                dot.style.boxShadow = dot.getAttribute('data-t') === theme ? '0 0 0 2px var(--primary)' : 'none';
            });
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
                if (sourceEl) sourceEl.value = 'all';
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
            btn.innerHTML = '<span>Сбор запущен...</span>';
            
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
                    document.getElementById('startBtn').innerHTML = '<span>Начать сбор</span>';
                    document.getElementById('btnExcel').disabled = false;
                    document.getElementById('btnCsv').disabled = false;
                    document.getElementById('btnCopyPhones').disabled = false;
                    fetchMemoryStats();
                } else if (!data.is_running && count === 0) {
                    clearInterval(pollTimer);
                    document.getElementById('startBtn').disabled = false;
                    document.getElementById('startBtn').innerHTML = '<span>Начать сбор</span>';
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
            btn.innerHTML = '<span>Поиск на биржах...</span>';

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
                btn.innerHTML = '<span>Найти заказы</span>';
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
                    document.getElementById('flStartBtn').innerHTML = '<span>Найти заказы</span>';
                    document.getElementById('btnFlExcel').disabled = false;
                    document.getElementById('btnFlCsv').disabled = false;
                } else if (!data.is_running && count === 0) {
                    clearInterval(flPollTimer);
                    document.getElementById('flStartBtn').disabled = false;
                    document.getElementById('flStartBtn').innerHTML = '<span>Найти заказы</span>';
                }
            } catch (err) {
                console.error(err);
            }
        }

        window.addEventListener('DOMContentLoaded', () => {
            try {
                const legacyMap = { dark: 'obsidian', light: 'paper', midnight: 'nord', cyberpunk: 'tokyo' };
                const rawTheme = localStorage.getItem('lead_theme') || 'obsidian';
                setTheme(legacyMap[rawTheme] || rawTheme);
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
                counter.innerText = isFiltered ? `Показано ${leads.length} из ${allLeads.length}` : `Всего: ${leads.length}`;
            }

            let html = '';
            leads.forEach((l, idx) => {
                const isInvalidSite = !l.website || ['yandex.', 'ya.ru', 'ya.by', 'google.', '2gis.', 'maps/org', 'clck/'].some(ign => l.website.toLowerCase().includes(ign));
                let siteStr = !isInvalidSite 
                    ? `<a class="site-link" href="${l.website}" target="_blank" title="${escapeHtml(l.website)}">${escapeHtml(l.website)}</a>` 
                    : '<span style="color: var(--success); font-weight: 500; font-size: 12px;">Нет сайта</span>';

                let badgeClass = 'badge-low';
                let statusVal = l.website_status || '';
                let badgeText = 'Есть сайт';

                if (statusVal.includes('Нет сайта') || isInvalidSite) {
                    badgeClass = 'badge-high';
                    badgeText = 'Нет сайта';
                } else if (statusVal.includes('Taplink') || (l.website && (l.website.includes('dikidi') || l.website.includes('yclients')))) {
                    badgeClass = 'badge-med';
                    badgeText = 'Taplink / Запись';
                } else if (statusVal.includes('Конструктор')) {
                    badgeClass = 'badge-med';
                    badgeText = 'Конструктор';
                } else if (statusVal.includes('соцсеть')) {
                    badgeClass = 'badge-med';
                    badgeText = 'Соцсеть';
                }

                const primaryPhone = (l.phones && l.phones.length > 0) ? l.phones[0] : '';
                const cleanDigits = primaryPhone.replace(/\D/g, '');
                const mobBadge = l.is_mobile 
                    ? '<span class="badge-mob" title="Мобильный номер">Моб</span>'
                    : (primaryPhone ? '<span class="badge-land" title="Городской номер">Гор</span>' : '');
                const phoneStr = primaryPhone 
                    ? `<div style="display: flex; align-items: center; white-space: nowrap;">${mobBadge}<a class="tel-link" href="tel:${primaryPhone}" title="Позвонить">${primaryPhone}</a></div>` 
                    : '<span style="color: var(--text-dim);">—</span>';

                const nameStr = l.map_url 
                    ? `<a href="${l.map_url}" target="_blank" class="org-link" title="Открыть карточку на карте">${escapeHtml(l.name)} <span class="link-icon">↗</span></a>`
                    : `<span style="font-weight: 600;">${escapeHtml(l.name)}</span>`;

                if (l.notes && l.notes.includes('100%')) {
                    siteStr += `<div style="font-size: 10px; color: var(--text-dim); margin-top: 2px;">Проверено в поиске</div>`;
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
                    ? `${l.rating} <span style="color: var(--text-dim);">(${l.reviews_count || 0})</span>` 
                    : '<span style="color: var(--text-dim);">—</span>';

                const fullAddr = [l.city, l.address].filter(Boolean).join(', ');

                const isCis = (l.is_cis !== undefined) ? l.is_cis : (l.source !== 'Google Maps');
                const primaryDigits = l.clean_phone_digits || cleanDigits;

                let actHtml = `<div class="actions-cell" style="justify-content: flex-end;">`;
                actHtml += `<button onclick="openPitchModal(${idx})" class="btn-act btn-act-pitch" title="Открыть оффер и скрипт звонка">Оффер</button>`;

                if (primaryPhone) {
                    if (isCis) {
                        const vbLink = l.viber_url || `viber://chat?number=%2B${primaryDigits}`;
                        actHtml += `<a href="${vbLink}" target="_blank" class="btn-act btn-act-vb" title="Viber">Viber</a>`;

                        const pitchText = l.ai_pitch || `Здравствуйте! Нашли организацию "${l.name}" на картах. Подскажите, пожалуйста, вы принимаете заказы?`;
                        const waText = encodeURIComponent(pitchText);
                        actHtml += `<a href="https://wa.me/${primaryDigits}?text=${waText}" target="_blank" class="btn-act btn-act-wa" title="WhatsApp">WA</a>`;

                        const tgUrl = l.telegram_url || (l.social_links && l.social_links.telegram) || `https://t.me/+${primaryDigits}`;
                        actHtml += `<a href="${tgUrl}" target="_blank" class="btn-act btn-act-tg" title="Telegram">TG</a>`;
                    } else {
                        const enPitch = encodeURIComponent(l.ai_pitch || `Hi! I noticed your business "${l.name}" on Google Maps. We specialize in building high-converting websites. Are you open to new clients?`);
                        actHtml += `<a href="https://wa.me/${primaryDigits}?text=${enPitch}" target="_blank" class="btn-act btn-act-wa" title="Send WhatsApp Message">WA</a>`;
                        actHtml += `<a href="tel:${primaryPhone}" class="btn-act" title="Direct Call">Call</a>`;
                    }

                    actHtml += `<button onclick="copyPhone('${primaryPhone}')" class="btn-act" title="Скопировать номер">Копия</button>`;
                }
                actHtml += `</div>`;

                let srcBadge = `<span class="badge badge-low">${l.source}</span>`;
                if (l.source === 'Google Maps') {
                    srcBadge = `<span class="badge badge-google">Google</span>`;
                }

                html += `<tr>
                    <td style="color: var(--text-dim);">${idx + 1}</td>
                    <td><span class="badge ${badgeClass}">${badgeText}</span></td>
                    <td>${nameStr}</td>
                    <td>${phoneStr}</td>
                    <td>${siteStr}</td>
                    <td style="white-space: nowrap;">${reviews}</td>
                    <td style="color: var(--text-dim); font-size: 12px; max-width: 230px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(fullAddr)}">${escapeHtml(fullAddr || '—')}</td>
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

        window.addEventListener('DOMContentLoaded', () => {
            try {
                const savedTheme = localStorage.getItem('lead_theme') || 'mono-dark';
                setTheme(savedTheme);
                const savedTab = localStorage.getItem('lead_active_tab') || 'maps';
                switchTab(savedTab);
                const savedRegion = localStorage.getItem('lead_region') || 'cis';
                setRegion(savedRegion);
            } catch (e) {}
            pollStatus();
            pollFreelanceStatus();
            fetch('/api/memory/stats').then(r => r.json()).then(d => {
                const b = document.getElementById('memCountBadge');
                if (b && d) b.innerText = d.total_leads || 0;
            }).catch(() => {});
        });
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

    # Normalize compound marketing niche queries for map engines
    map_query = clean_map_query(query)

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

            def is_qualifying_lead(l: Lead) -> bool:
                if filter_type == "hot_only":
                    return l.lead_priority == LeadPriority.HIGH and (not l.website or l.website_status == WebsiteStatus.NO_WEBSITE)
                elif filter_type == "social_only":
                    return l.lead_priority == LeadPriority.MEDIUM
                elif filter_type == "hot_warm":
                    return l.lead_priority in (LeadPriority.HIGH, LeadPriority.MEDIUM) and l.website_status != WebsiteStatus.HAS_WEBSITE
                return True

            def on_lead(lead: Lead):
                if CURRENT_STATE.get("cancel_requested"):
                    return
                if not is_qualifying_lead(lead):
                    return
                key = (lead.name.lower().strip(), lead.primary_phone)
                if key not in seen:
                    seen.add(key)
                    if not lead.ai_pitch:
                        enrich_lead_with_pitch(lead)
                    all_leads.append(lead)
                    lead_dict = lead.model_dump()
                    with STATE_LOCK:
                        CURRENT_STATE["leads"].append(lead_dict)
                        skip_text = f" (пропущено: {total_skipped})" if total_skipped > 0 else ""
                        CURRENT_STATE["progress_message"] = f"{prefix}{city_label}: собрано {len(CURRENT_STATE['leads'])} из {limit}{skip_text}..."

            def on_progress(msg: str):
                with STATE_LOCK:
                    CURRENT_STATE["progress_message"] = f"{prefix}{city_label}: {msg}"

            city_lower = (current_city or "").lower()
            is_cis_city = any(w in city_lower for w in [
                "минск", "брест", "гродно", "витебск", "могилев", "гомель",
                "москва", "санкт", "питер", "спб", "казань", "новосибирск",
                "екатеринбург", "краснодар", "самара", "ростов", "сочи",
                "алматы", "астана", "беларусь", "россия", "казахстан"
            ]) or not any(w in city_lower for w in [
                "miami", "new york", "los angeles", "houston", "dallas", "chicago",
                "london", "berlin", "warsaw", "prague", "paris", "madrid", "rome"
            ])

            # CIS preferred ordering: Yandex Maps -> 2GIS -> Google Maps
            # International preferred ordering: Google Maps -> Yandex -> 2GIS
            if is_cis_city:
                # 1. Yandex Maps
                if source in ("yandex", "both", "all") and len(all_leads) < limit:
                    CURRENT_STATE["progress_message"] = f"{prefix}Поиск в Яндекс Картах ({city_label})..."
                    y_scraper = YandexScraper(headless=True, on_lead_found=on_lead, on_progress=on_progress)
                    try:
                        y_leads = await y_scraper.search(
                            query=map_query,
                            city=current_city,
                            limit=curr_limit,
                            filter_type=filter_type,
                            skip_checked=skip_checked,
                        )
                        total_skipped += getattr(y_scraper, "skipped_checked_count", 0)
                        for l in y_leads:
                            if not is_qualifying_lead(l):
                                continue
                            key = (l.name.lower().strip(), l.primary_phone)
                            if key not in seen:
                                seen.add(key)
                                if not l.ai_pitch:
                                    enrich_lead_with_pitch(l)
                                all_leads.append(l)
                                with STATE_LOCK:
                                    CURRENT_STATE["leads"].append(l.model_dump())
                    except Exception as e:
                        print(f"[WebUI] Yandex error for {current_city}: {e}")

                # 2. 2GIS
                if source in ("2gis", "both", "all") and len(all_leads) < limit:
                    g_limit = curr_limit if source == "2gis" else max(10, curr_limit - len([l for l in all_leads if l.city == current_city]))
                    CURRENT_STATE["progress_message"] = f"{prefix}Поиск в 2ГИС ({city_label})..."
                    g_scraper = TwoGisScraper(headless=True, on_lead_found=on_lead, on_progress=on_progress)
                    try:
                        g_leads = await g_scraper.search(
                            query=map_query,
                            city=current_city,
                            limit=g_limit,
                            filter_type=filter_type,
                            skip_checked=skip_checked,
                        )
                        total_skipped += getattr(g_scraper, "skipped_checked_count", 0)
                        for l in g_leads:
                            if not is_qualifying_lead(l):
                                continue
                            key = (l.name.lower().strip(), l.primary_phone)
                            if key not in seen:
                                seen.add(key)
                                if not l.ai_pitch:
                                    enrich_lead_with_pitch(l)
                                all_leads.append(l)
                                with STATE_LOCK:
                                    CURRENT_STATE["leads"].append(l.model_dump())
                    except Exception as e:
                        print(f"[WebUI] 2GIS error for {current_city}: {e}")

                # 3. Google Maps (fallback for CIS)
                if source in ("google", "all") and len(all_leads) < limit:
                    CURRENT_STATE["progress_message"] = f"{prefix}Поиск в Google Maps ({city_label})..."
                    gmaps_scraper = GoogleMapsScraper(headless=True, on_lead_found=on_lead, on_progress=on_progress)
                    try:
                        gmaps_leads = await gmaps_scraper.search(
                            query=map_query,
                            city=current_city,
                            limit=curr_limit,
                            filter_type=filter_type,
                            skip_checked=skip_checked,
                            verify_web=False,
                        )
                        total_skipped += getattr(gmaps_scraper, "skipped_checked_count", 0)
                        for l in gmaps_leads:
                            if not is_qualifying_lead(l):
                                continue
                            key = (l.name.lower().strip(), l.primary_phone)
                            if key not in seen:
                                seen.add(key)
                                if not l.ai_pitch:
                                    enrich_lead_with_pitch(l)
                                all_leads.append(l)
                                with STATE_LOCK:
                                    CURRENT_STATE["leads"].append(l.model_dump())
                    except Exception as e:
                        print(f"[WebUI] Google Maps error for {current_city}: {e}")

            else:
                # International / US / Europe: Google Maps first
                if source in ("google", "all") and len(all_leads) < limit:
                    CURRENT_STATE["progress_message"] = f"{prefix}Поиск в Google Maps ({city_label})..."
                    gmaps_scraper = GoogleMapsScraper(headless=True, on_lead_found=on_lead, on_progress=on_progress)
                    try:
                        gmaps_leads = await gmaps_scraper.search(
                            query=map_query,
                            city=current_city,
                            limit=curr_limit,
                            filter_type=filter_type,
                            skip_checked=skip_checked,
                            verify_web=False,
                        )
                        total_skipped += getattr(gmaps_scraper, "skipped_checked_count", 0)
                        for l in gmaps_leads:
                            if not is_qualifying_lead(l):
                                continue
                            key = (l.name.lower().strip(), l.primary_phone)
                            if key not in seen:
                                seen.add(key)
                                if not l.ai_pitch:
                                    enrich_lead_with_pitch(l)
                                all_leads.append(l)
                                with STATE_LOCK:
                                    CURRENT_STATE["leads"].append(l.model_dump())
                    except Exception as e:
                        print(f"[WebUI] Google Maps error for {current_city}: {e}")

                if source in ("yandex", "both", "all") and len(all_leads) < limit:
                    CURRENT_STATE["progress_message"] = f"{prefix}Поиск в Яндекс Картах ({city_label})..."
                    y_scraper = YandexScraper(headless=True, on_lead_found=on_lead, on_progress=on_progress)
                    try:
                        y_leads = await y_scraper.search(
                            query=map_query,
                            city=current_city,
                            limit=curr_limit,
                            filter_type=filter_type,
                            skip_checked=skip_checked,
                        )
                        total_skipped += getattr(y_scraper, "skipped_checked_count", 0)
                        for l in y_leads:
                            if not is_qualifying_lead(l):
                                continue
                            key = (l.name.lower().strip(), l.primary_phone)
                            if key not in seen:
                                seen.add(key)
                                if not l.ai_pitch:
                                    enrich_lead_with_pitch(l)
                                all_leads.append(l)
                                with STATE_LOCK:
                                    CURRENT_STATE["leads"].append(l.model_dump())
                    except Exception as e:
                        print(f"[WebUI] Yandex error for {current_city}: {e}")

                if source in ("2gis", "both", "all") and len(all_leads) < limit:
                    g_limit = curr_limit if source == "2gis" else max(10, curr_limit - len([l for l in all_leads if l.city == current_city]))
                    CURRENT_STATE["progress_message"] = f"{prefix}Поиск в 2ГИС ({city_label})..."
                    g_scraper = TwoGisScraper(headless=True, on_lead_found=on_lead, on_progress=on_progress)
                    try:
                        g_leads = await g_scraper.search(
                            query=map_query,
                            city=current_city,
                            limit=g_limit,
                            filter_type=filter_type,
                            skip_checked=skip_checked,
                        )
                        total_skipped += getattr(g_scraper, "skipped_checked_count", 0)
                        for l in g_leads:
                            if not is_qualifying_lead(l):
                                continue
                            key = (l.name.lower().strip(), l.primary_phone)
                            if key not in seen:
                                seen.add(key)
                                if not l.ai_pitch:
                                    enrich_lead_with_pitch(l)
                                all_leads.append(l)
                                with STATE_LOCK:
                                    CURRENT_STATE["leads"].append(l.model_dump())
                    except Exception as e:
                        print(f"[WebUI] 2GIS error for {current_city}: {e}")

            # Fallback: if regional maps yielded 0 leads (cloud datacenter IP blocking), auto-fallback to Google Maps
            if len(all_leads) == 0 and source in ("both", "yandex", "2gis"):
                CURRENT_STATE["progress_message"] = f"{prefix}Подключение Google Maps для {city_label}..."
                try:
                    fb_scraper = GoogleMapsScraper(headless=True, on_lead_found=on_lead, on_progress=on_progress)
                    fb_leads = await fb_scraper.search(
                        query=map_query,
                        city=current_city,
                        limit=curr_limit,
                        filter_type=filter_type,
                        skip_checked=skip_checked,
                        verify_web=False,
                    )
                    for l in fb_leads:
                        if not is_qualifying_lead(l):
                            continue
                        key = (l.name.lower().strip(), l.primary_phone)
                        if key not in seen:
                            seen.add(key)
                            if not l.ai_pitch:
                                enrich_lead_with_pitch(l)
                            all_leads.append(l)
                            with STATE_LOCK:
                                CURRENT_STATE["leads"].append(l.model_dump())
                except Exception as e:
                    print(f"[WebUI] Google Maps fallback error: {e}")

        # Web Search Verification if requested by user
        if verify_web and all_leads:
            check_candidates = [l for l in all_leads if not l.website or l.website_status in (WebsiteStatus.NO_WEBSITE, WebsiteStatus.TAPLINK)]
            if check_candidates:
                CURRENT_STATE["progress_message"] = f"🌐 Онлайн-верификация сайтов ({len(check_candidates)} компаний)..."
                for idx, lead in enumerate(check_candidates, 1):
                    try:
                        has_site, detected_site = await verify_company_website(lead.name, lead.city)
                        if has_site and detected_site:
                            status, priority = classify_website(detected_site)
                            if status != WebsiteStatus.NO_WEBSITE:
                                lead.website = detected_site
                                lead.website_status = status
                                lead.lead_priority = priority
                                lead.notes = f"🌐 Найден сайт в поиске: {detected_site}"
                                memory_db.save_lead(lead)
                        else:
                            lead.notes = "✅ Подтверждено: сайта в интернете нет"
                    except Exception:
                        pass
                    if idx % 5 == 0 or idx == len(check_candidates):
                        CURRENT_STATE["progress_message"] = f"🌐 Проверено в сети: {idx}/{len(check_candidates)} компаний..."

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
        filtered = [l for l in all_leads if is_qualifying_lead(l)]

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
            with STATE_LOCK:
                payload = {
                    "is_running": CURRENT_STATE["is_running"],
                    "progress_message": CURRENT_STATE["progress_message"],
                    "total_target": CURRENT_STATE["total_target"],
                    "leads": list(CURRENT_STATE["leads"]),
                    "last_excel_path": CURRENT_STATE["last_excel_path"],
                    "last_csv_path": CURRENT_STATE["last_csv_path"],
                    "skipped_count": CURRENT_STATE.get("skipped_count", 0),
                    "memory_stats": memory_db.get_stats(),
                }
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

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

            with STATE_LOCK:
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
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
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
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
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

                with STATE_LOCK:
                    CURRENT_STATE["cancel_requested"] = False

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

        elif path == "/api/stop":
            with STATE_LOCK:
                CURRENT_STATE["is_running"] = False
                CURRENT_STATE["cancel_requested"] = True
                CURRENT_STATE["progress_message"] = "Остановлено пользователем."
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "stopped"}).encode("utf-8"))

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
    server = ThreadingHTTPServer((host, env_port), RequestHandler)
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
