"""Launcher for sharing Lead Parser online via secure tunnel."""
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def copy_to_clipboard(text: str):
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value '{text}'"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def start_tunnel(port: int = 8080):
    tunnel_url = None
    proc = None

    # Method 1: Built-in OpenSSH to localhost.run (instant, no password required)
    try:
        cmd = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ServerAliveInterval=30",
            "-R",
            f"80:localhost:{port}",
            "nokey@localhost.run",
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )

        for _ in range(40):
            line = proc.stdout.readline()
            if not line:
                break
            if "lhr.life" in line:
                urls = re.findall(r"https://[a-zA-Z0-9\.\-_]+\.lhr\.life", line)
                if urls:
                    tunnel_url = urls[0]
                    break
            time.sleep(0.1)
    except Exception:
        pass

    # Method 2: Fallback to localtunnel if ssh did not connect
    if not tunnel_url:
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass
        try:
            cmd = ["npx", "--yes", "localtunnel", "--port", str(port)]
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                shell=True,
            )
            for _ in range(40):
                line = proc.stdout.readline()
                if not line:
                    break
                if "loca.lt" in line:
                    urls = re.findall(r"https://[a-zA-Z0-9\.\-_]+\.loca\.lt", line)
                    if urls:
                        tunnel_url = urls[0]
                        break
                time.sleep(0.1)
        except Exception:
            pass

    return tunnel_url, proc


def main():
    port = int(os.environ.get("PORT", 8080))
    os.environ["HOST"] = "0.0.0.0"

    print("=======================================================")
    print("  Запуск сервера и генерация онлайн-ссылки...")
    print("=======================================================")

    # Import web_ui and start server in background thread
    from web_ui import run_web

    server_thread = threading.Thread(target=run_web, kwargs={"port": port}, daemon=True)
    server_thread.start()

    # Wait for server to bind
    time.sleep(1.2)

    # Establish tunnel
    tunnel_url, tunnel_proc = start_tunnel(port=port)

    print("\n" + "=" * 65)
    if tunnel_url:
        print("  🚀 ПАРСЕР УСПЕШНО ДОСТУПЕН В ИНТЕРНЕТЕ!")
        print("=" * 65)
        print(f"\n  👉 ССЫЛКА ДЛЯ ДРУГА (ОТПРАВЬТЕ ЕМУ):")
        print(f"     {tunnel_url}\n")
        print("  (Ссылка уже скопирована в буфер обмена - просто нажмите Ctrl+V в чате)")
        copy_to_clipboard(tunnel_url)
        webbrowser.open(tunnel_url)
    else:
        print("  ⚠️ Не удалось создать онлайн-туннель.")
        print(f"  Сервер работает локально: http://localhost:{port}")

    print("\n" + "=" * 65)
    print(f"  👉 Локальный адрес на вашем компьютере: http://localhost:{port}")
    print("  Для завершения работы и закрытия доступа нажмите Ctrl + C")
    print("=" * 65 + "\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nОстановка сервера и туннеля...")
        if tunnel_proc:
            try:
                tunnel_proc.terminate()
            except Exception:
                pass
        print("Готово. Работа завершена.")


if __name__ == "__main__":
    main()
