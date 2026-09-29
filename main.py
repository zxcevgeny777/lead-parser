"""Main entry point for Map Leads Scraper."""
import argparse
import asyncio
import sys
import webbrowser

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Парсер Яндекс Карт и 2ГИС для поиска лидов на разработку сайтов."
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Запустить локальный веб-интерфейс в браузере (по умолчанию)",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Запустить интерактивный консольный интерфейс (терминал)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Порт для веб-интерфейса (по умолчанию 8080)",
    )

    args = parser.parse_args()

    # If --cli specified, run CLI
    if args.cli:
        from cli import run_cli
        asyncio.run(run_cli())
        return

    # Otherwise default to Web UI or prompt
    from web_ui import run_web
    # Try opening browser automatically after launch
    def open_browser():
        import time
        time.sleep(1.0)
        webbrowser.open(f"http://localhost:{args.port}")

    import threading
    threading.Thread(target=open_browser, daemon=True).start()
    run_web(port=args.port)


if __name__ == "__main__":
    main()
