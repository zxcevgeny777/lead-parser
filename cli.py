"""Interactive command-line interface for the Map Leads Scraper."""
import asyncio
import os
import re
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
from datetime import datetime
from typing import List

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, IntPrompt, Confirm
from rich import box

from core.models import Lead, LeadPriority, WebsiteStatus
from core.exporter import export_to_excel, export_to_csv
from core.memory import memory_db
from core.site_auditor import audit_lead_website
from core.ai_pitcher import enrich_lead_with_pitch
from core.notifier import load_settings
from scrapers.twogis import TwoGisScraper
from scrapers.yandex import YandexScraper

console = Console()


def print_banner():
    banner_text = """[bold cyan]╔═══════════════════════════════════════════════════════════════════╗
║     🚀 ПАРСЕР ЯНДЕКС КАРТ И 2ГИС ДЛЯ ПОИСКА ЛИДОВ НА САЙТЫ 🚀     ║
║             Специализированный сбор горячей базы клиентов         ║
╚═══════════════════════════════════════════════════════════════════╝[/bold cyan]"""
    console.print(banner_text)
    stats = memory_db.get_stats()
    mem_count = stats.get("total_checked", 0)
    console.print(
        f"[dim]Парсер находит компании, у которых [bold green]НЕТ САЙТА[/bold green] или указан только "
        f"[bold yellow]Taplink / VK / Telegram[/bold yellow].[/dim]\n"
        f"[dim]🧠 [bold]Память парсера:[/bold] [bold cyan]{mem_count}[/bold cyan] ранее проверенных мест в базе данных.[/dim]\n"
    )


def display_leads_summary(leads: List[Lead]):
    """Displays a summary table of the parsed leads."""
    if not leads:
        console.print("[bold red]Ни одной организации не найдено по данному запросу.[/bold red]")
        return

    high_count = sum(1 for l in leads if l.lead_priority == LeadPriority.HIGH)
    med_count = sum(1 for l in leads if l.lead_priority == LeadPriority.MEDIUM)
    low_count = sum(1 for l in leads if l.lead_priority == LeadPriority.LOW)
    with_phone = sum(1 for l in leads if l.phones)

    table = Table(
        title="📊 Результаты сбора лидов",
        box=box.ROUNDED,
        header_style="bold magenta",
        show_lines=True,
    )

    table.add_column("№", style="dim", width=4)
    table.add_column("Приоритет", justify="center", width=22)
    table.add_column("Компания", style="bold white", width=28)
    table.add_column("Телефон", style="green", width=20)
    table.add_column("Сайт / Ссылка", style="blue", width=24)
    table.add_column("Отзывы", justify="center", width=8)
    table.add_column("Город / Адрес", style="dim", width=28)

    for i, lead in enumerate(leads[:20], start=1):
        if lead.lead_priority == LeadPriority.HIGH:
            priority_str = "[bold green]🔥 НЕТ САЙТА[/bold green]"
        elif lead.lead_priority == LeadPriority.MEDIUM:
            priority_str = f"[bold yellow]{lead.website_status.value}[/bold yellow]"
        else:
            priority_str = "[dim]Есть свой сайт[/dim]"

        site_display = lead.website if lead.website else "[dim]—[/dim]"
        if len(site_display) > 24:
            site_display = site_display[:21] + "..."

        name_display = lead.name[:27] + "..." if len(lead.name) > 27 else lead.name
        phone_display = lead.primary_phone or "[dim red]Нет тел.[/dim red]"
        addr_display = lead.address[:27] + "..." if len(lead.address) > 27 else lead.address

        table.add_row(
            str(i),
            priority_str,
            name_display,
            phone_display,
            site_display,
            str(lead.reviews_count or 0),
            addr_display,
        )

    console.print(table)
    if len(leads) > 20:
        console.print(f"[dim]... и еще {len(leads) - 20} организаций сохранены в файл.[/dim]")

    stats_panel = Panel(
        f"[bold white]Всего собрано:[/bold white] {len(leads)} компаний\n"
        f"[bold green]🔥 Горячих лидов (СОВСЕМ НЕТ САЙТА):[/bold green] {high_count}\n"
        f"[bold yellow]⚡ Теплых лидов (только соцсеть / Taplink / конструктор):[/bold yellow] {med_count}\n"
        f"[dim]⚪ Компаний со своим сайтом:[/dim] {low_count}\n"
        f"[bold cyan]📞 С прямыми номерами телефонов:[/bold cyan] {with_phone}",
        title="📈 Статистика базы",
        border_style="cyan",
        box=box.ROUNDED,
    )
    console.print(stats_panel)


async def run_cli():
    print_banner()

    # 1. Source selection
    console.print("[bold yellow]1. Выберите источник данных:[/bold yellow]")
    console.print("  [bold]1[/bold] — Яндекс Карты")
    console.print("  [bold]2[/bold] — 2ГИС")
    console.print("  [bold]3[/bold] — Оба сервиса (объединить и удалить дубли)")
    source_choice = Prompt.ask("Ваш выбор", choices=["1", "2", "3"], default="3")

    # 2. Query / Niche selection
    console.print("\n[bold yellow]2. Выберите популярную нишу или введите свою:[/bold yellow]")

    top_niches = [
        ("1", "🦷 Стоматология", "Стоматология"),
        ("2", "🚗 Автосервис / СТО", "Автосервис"),
        ("3", "🏠 Ремонт квартир", "Ремонт квартир"),
        ("4", "🏗️ Строительство домов", "Строительство домов"),
        ("5", "💆 Косметология", "Косметология"),
        ("6", "🏢 Натяжные потолки", "Натяжные потолки"),
        ("7", "🪟 Пластиковые окна", "Пластиковые окна"),
        ("8", "⚖️  Юрист / Банкротство", "Юрист"),
        ("9", "🧹 Клининг", "Клининг"),
        ("10", "✨ Детейлинг", "Детейлинг"),
        ("11", "💅 Салон красоты", "Салон красоты"),
        ("12", "🚿 Автомойка", "Автомойка"),
    ]
    niche_map = {code: q_val for code, _, q_val in top_niches}

    niche_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
    niche_table.add_column("Код", style="bold cyan", width=6)
    niche_table.add_column("Ниша", style="white", width=28)
    niche_table.add_column("Код", style="bold cyan", width=6)
    niche_table.add_column("Ниша", style="white", width=28)

    for i in range(0, len(top_niches), 2):
        c1, d1, _ = top_niches[i]
        if i + 1 < len(top_niches):
            c2, d2, _ = top_niches[i + 1]
            niche_table.add_row(f"[{c1}]", d1, f"[{c2}]", d2)
        else:
            niche_table.add_row(f"[{c1}]", d1, "", "")

    console.print(niche_table)
    console.print("[dim]Введите номер из списка (1-12) или напишите свою нишу вручную:[/dim]")

    raw_query = Prompt.ask("Ниша / Поисковый запрос", default="1").strip()
    while not raw_query:
        raw_query = Prompt.ask("[red]Запрос не может быть пустым. Введите нишу:[/red]").strip()

    query = niche_map.get(raw_query, raw_query)
    console.print(f"[green]✔ Выбрана ниша:[/green] [bold white]{query}[/bold white]")

    # 3. City
    city_input = Prompt.ask(
        "\n[bold yellow]3. Введите город(а)[/bold yellow] (можно несколько через запятую, например: Москва, СПб, Казань, или оставьте пустым)",
        default="",
    ).strip()
    raw_cities = [c.strip() for c in re.split(r"[,;]+", city_input) if c.strip()]
    cities = raw_cities if raw_cities else [""]

    # 4. Limit
    limit = IntPrompt.ask(
        "\n[bold yellow]4. Сколько организаций собрать?[/bold yellow]",
        default=50,
    )

    # 5. Lead filter
    console.print("\n[bold yellow]5. Фильтрация лидов:[/bold yellow]")
    console.print("  [bold]1[/bold] — 🔥 Только без сайта (100% строгий — без сайтов)")
    console.print("  [bold]2[/bold] — ⚡ Только соцсети / Taplink / Конструкторы")
    console.print("  [bold]3[/bold] — 🔥 Без сайта + ⚡ Соцсети / Taplink")
    console.print("  [bold]4[/bold] — ⚪ Все найденные компании")
    filter_choice = Prompt.ask("Фильтр", choices=["1", "2", "3", "4"], default="1")

    # 6. Headless
    headless = Confirm.ask(
        "\n[bold yellow]6. Запустить браузер в фоновом режиме (Headless)?[/bold yellow]",
        default=True,
    )

    # 7. Skip already checked
    skip_checked = Confirm.ask(
        "\n[bold yellow]7. Исключать ранее проверенные компании (память парсера)?[/bold yellow]",
        default=True,
    )

    console.print("\n[bold green]Начинаем сбор лидов... Пожалуйста, подождите.[/bold green]\n")

    all_leads: List[Lead] = []

    def on_lead(lead: Lead):
        badge = (
            "[bold green]🔥 НЕТ САЙТА[/bold green]"
            if lead.lead_priority == LeadPriority.HIGH
            else f"[yellow]{lead.website_status.value}[/yellow]"
        )
        phone = lead.primary_phone or "[dim]нет телефона[/dim]"
        console.print(f"  [cyan][{lead.source}][/cyan] {badge} [bold]{lead.name}[/bold] | Тел: {phone}")

    # Map filter choice
    filter_mode_map = {
        "1": "hot_only",
        "2": "social_only",
        "3": "hot_warm",
        "4": "all",
    }
    filter_mode = filter_mode_map.get(filter_choice, "hot_only")

    per_city_target = max(limit // len(cities), 10) if len(cities) > 1 else limit

    for city_idx, current_city in enumerate(cities, 1):
        if len(all_leads) >= limit:
            break

        city_label = current_city or "Россия"
        if len(cities) > 1:
            console.print(f"\n[bold blue]=== [{city_idx}/{len(cities)}] Поиск по городу: {city_label} ===[/bold blue]")

        remaining_needed = limit - len(all_leads)
        curr_limit = min(per_city_target, remaining_needed) if len(cities) > 1 else remaining_needed

        # Yandex Scraper
        if source_choice in ("1", "3") and len(all_leads) < limit:
            console.print(f"[bold cyan]>>> Запуск сбора с Яндекс Карт ({city_label})...[/bold cyan]")
            y_scraper = YandexScraper(headless=headless, on_lead_found=on_lead)
            try:
                y_leads = await y_scraper.search(
                    query=query,
                    city=current_city,
                    limit=curr_limit,
                    filter_type=filter_mode,
                    skip_checked=skip_checked,
                )
                all_leads.extend(y_leads)
            except Exception as e:
                console.print(f"[red]Ошибка при сборе с Яндекс Карт: {e}[/red]")

        # 2GIS Scraper
        if source_choice in ("2", "3") and len(all_leads) < limit:
            console.print(f"\n[bold cyan]>>> Запуск сбора с 2ГИС ({city_label})...[/bold cyan]")
            g_scraper = TwoGisScraper(headless=headless, on_lead_found=on_lead)
            sub_limit = curr_limit if source_choice == "2" else max(10, curr_limit - len([l for l in all_leads if l.city == current_city]))
            try:
                g_leads = await g_scraper.search(
                    query=query,
                    city=current_city,
                    limit=sub_limit,
                    filter_type=filter_mode,
                    filter_no_website_only=(filter_choice == "1"),
                    skip_checked=skip_checked,
                )
                all_leads.extend(g_leads)
            except Exception as e:
                console.print(f"[red]Ошибка при сборе с 2ГИС: {e}[/red]")

    # Deduplicate by name and phone
    seen_keys = set()
    unique_leads: List[Lead] = []
    for lead in all_leads:
        key = (lead.name.lower().strip(), lead.primary_phone)
        if key not in seen_keys:
            seen_keys.add(key)
            unique_leads.append(lead)

    # Apply user filter
    if filter_choice == "1":
        filtered_leads = [l for l in unique_leads if l.lead_priority == LeadPriority.HIGH and (not l.website or l.website_status == WebsiteStatus.NO_WEBSITE)]
    elif filter_choice == "2":
        filtered_leads = [l for l in unique_leads if l.lead_priority == LeadPriority.MEDIUM]
    elif filter_choice == "3":
        filtered_leads = [
            l for l in unique_leads if l.lead_priority in (LeadPriority.HIGH, LeadPriority.MEDIUM) and l.website_status != WebsiteStatus.HAS_WEBSITE
        ]
    else:
        filtered_leads = unique_leads

    # Sort so High priority (no website) comes first!
    priority_order = {LeadPriority.HIGH: 0, LeadPriority.MEDIUM: 1, LeadPriority.LOW: 2}
    filtered_leads.sort(key=lambda x: (priority_order.get(x.lead_priority, 3), -(x.reviews_count or 0)))

    console.print("\n")
    display_leads_summary(filtered_leads)

    total_skipped = (getattr(y_scraper, "skipped_checked_count", 0) if y_scraper else 0) + (
        getattr(g_scraper, "skipped_checked_count", 0) if g_scraper else 0
    )
    if total_skipped > 0:
        console.print(f"[dim]🧠 Пропущено организаций, уже проверенных ранее: [bold yellow]{total_skipped}[/bold yellow][/dim]\n")

    if filtered_leads:
        console.print("[dim]🔍 Проводим аудит сайтов и генерируем персонализированные AI-питчи...[/dim]")
        cfg = load_settings()
        gemini_key = cfg.get("gemini_api_key", "")
        for l in filtered_leads:
            try:
                if l.website and l.website_status not in (WebsiteStatus.NO_WEBSITE, WebsiteStatus.SOCIAL):
                    await audit_lead_website(l)
                enrich_lead_with_pitch(l, gemini_api_key=gemini_key)
            except Exception:
                pass

        # Export files
        safe_query = "".join(c for c in query if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        safe_city = f"_{city.strip()}" if city else ""
        date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
        filename_base = f"leads_{safe_query}{safe_city}_{date_str}"

        excel_path = f"{filename_base}.xlsx"
        csv_path = f"{filename_base}.csv"

        saved_excel = export_to_excel(filtered_leads, excel_path)
        saved_csv = export_to_csv(filtered_leads, csv_path)

        console.print(
            Panel(
                f"[bold green]✔ Файлы базы лидов успешно созданы![/bold green]\n\n"
                f"📗 [bold]Excel (.xlsx):[/bold] [cyan]{saved_excel}[/cyan]\n"
                f"📄 [bold]CSV (.csv):[/bold]   [cyan]{saved_csv}[/cyan]\n\n"
                f"[dim]В Excel настроены автофильтры, кликабельные ссылки на карты и подсветка горячих лидов.[/dim]",
                title="💾 Экспорт завершен",
                border_style="green",
                box=box.ROUNDED,
            )
        )


if __name__ == "__main__":
    try:
        asyncio.run(run_cli())
    except KeyboardInterrupt:
        console.print("\n[yellow]Сбор остановлен пользователем.[/yellow]")
