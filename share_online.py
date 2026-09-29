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

    url_holder = []

    def reader():
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            if "lhr.life" in line:
                urls = re.findall(r"https://[a-zA-Z0-9\.\-_]+\.lhr\.life", line)
                if urls:
                    url_holder.append(urls[0])
                    break

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t.join(timeout=8.0)

    if url_holder:
        return url_holder[0], proc

    # Fallback to localtunnel if ssh tunnel didn't report URL within 8s
    if proc:
        try:
            proc.terminate()
        except Exception:
            pass

    try:
        lt_proc = subprocess.Popen(
            ["npx", "--yes", "localtunnel", "--port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            shell=True,
        )

        def lt_reader():
            for line in iter(lt_proc.stdout.readline, ""):
                if not line:
                    break
                if "loca.lt" in line:
                    urls = re.findall(r"https://[a-zA-Z0-9\.\-_]+\.loca\.lt", line)
                    if urls:
                        url_holder.append(urls[0])
                        break

        t2 = threading.Thread(target=lt_reader, daemon=True)
        t2.start()
        t2.join(timeout=10.0)

        if url_holder:
            return url_holder[0], lt_proc
    except Exception:
        pass

    return None, None


def main():
    port = int(os.environ.get("PORT", 8080))
    os.environ["HOST"] = "0.0.0.0"

    print("===================================================================")
    print("  [1/2] Запуск сервера лид-парсера...")
    print("===================================================================")

    from web_ui import run_web

    server_thread = threading.Thread(target=run_web, kwargs={"port": port}, daemon=True)
    server_thread.start()

    time.sleep(1.5)

    print("  [2/2] Создание защищенной публичной ссылки...")
    tunnel_url, tunnel_proc = start_tunnel(port=port)

    print("\n" + "=" * 67)
    if tunnel_url:
        print("  🚀 ПАРСЕР УСПЕШНО ДОСТУПЕН В ИНТЕРНЕТЕ!")
        print("=" * 67)
        print(f"\n  👉 ССЫЛКА ДЛЯ ДРУГА (ОТПРАВЬТЕ ЕМУ):")
        print(f"     {tunnel_url}\n")
        print("  (Ссылка уже скопирована в буфер обмена - просто нажми Ctrl+V в чате)")
        copy_to_clipboard(tunnel_url)
        webbrowser.open(tunnel_url)
    else:
        print("  ⚠️ Не удалось создать онлайн-туннель.")
        print(f"  Сервер работает локально: http://localhost:{port}")

    print("\n" + "=" * 67)
    print(f"  👉 Локально на вашем ПК: http://localhost:{port}")
    print("  Чтобы закрыть доступ, просто закройте это окно или нажмите Ctrl+C")
    print("=" * 67 + "\n")

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
        print("Работа завершена.")


if __name__ == "__main__":
    main()
