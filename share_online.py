"""Launcher for sharing Lead Parser online via secure Cloudflare tunnel."""
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def copy_to_clipboard(text: str):
    """Copy given text to Windows clipboard."""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value '{text}'"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        pass


def ensure_cloudflared(bin_path: str) -> bool:
    """Download cloudflared.exe automatically if it doesn't exist."""
    if os.path.exists(bin_path) and os.path.getsize(bin_path) > 10000000:
        return True
    try:
        print("  [*] Загрузка модуля Cloudflare Tunnel (~50 МБ, только при первом запуске)...", flush=True)
        res = subprocess.run(
            [
                "curl.exe",
                "-s",
                "-L",
                "-o",
                bin_path,
                "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
            ],
            check=False,
            timeout=90,
        )
        return os.path.exists(bin_path) and os.path.getsize(bin_path) > 10000000
    except Exception:
        return False


def start_cloudflare_tunnel(port: int = 8080):
    """Start Cloudflare Tunnel using local cloudflared.exe or PATH."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    bin_path = os.path.join(current_dir, "cloudflared.exe")
    ensure_cloudflared(bin_path)
    if not os.path.exists(bin_path):
        bin_path = "cloudflared.exe"

    try:
        proc = subprocess.Popen(
            [bin_path, "tunnel", "--url", f"http://127.0.0.1:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
    except Exception:
        return None, None

    url_holder = []
    stop_event = threading.Event()

    def reader(stream):
        for line in iter(stream.readline, ""):
            if stop_event.is_set():
                break
            if not line:
                break
            if not url_holder and "trycloudflare.com" in line:
                m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                if m:
                    url_holder.append(m.group(0))

    t_err = threading.Thread(target=reader, args=(proc.stderr,), daemon=True)
    t_out = threading.Thread(target=reader, args=(proc.stdout,), daemon=True)
    t_err.start()
    t_out.start()

    # Wait up to 15 seconds for tunnel URL
    start_t = time.time()
    while time.time() - start_t < 15.0:
        if url_holder:
            return url_holder[0], proc
        if proc.poll() is not None:
            break
        time.sleep(0.2)

    stop_event.set()
    if proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass
    return None, None


def start_ssh_tunnel(port: int = 8080):
    """Fallback: localhost.run via SSH."""
    try:
        cmd = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=3",
            "-R",
            f"80:127.0.0.1:{port}",
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
                if not url_holder and "lhr.life" in line:
                    urls = re.findall(r"https://[a-zA-Z0-9\.\-_]+\.lhr\.life", line)
                    if urls:
                        url_holder.append(urls[0])

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        t.join(timeout=8.0)

        if url_holder:
            return url_holder[0], proc
        if proc:
            proc.terminate()
    except Exception:
        pass
    return None, None


def start_tunnel(port: int = 8080):
    """Start best available tunnel: Cloudflare (primary) -> SSH -> Localtunnel."""
    # 1. Cloudflare Tunnel (fast, reliable 24/7, never drops out)
    url, proc = start_cloudflare_tunnel(port=port)
    if url:
        return url, proc

    # 2. SSH localhost.run fallback
    url, proc = start_ssh_tunnel(port=port)
    if url:
        return url, proc

    # 3. Localtunnel fallback
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
        url_holder = []

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

    print("===================================================================", flush=True)
    print("  [1/2] Запуск сервера лид-парсера...", flush=True)
    print("===================================================================", flush=True)

    from web_ui import run_web

    server_thread = threading.Thread(target=run_web, kwargs={"port": port}, daemon=True)
    server_thread.start()

    time.sleep(1.5)

    print("  [2/2] Подключение Cloudflare Tunnel (быстро, надежно, 24/7)...", flush=True)
    tunnel_url, tunnel_proc = start_tunnel(port=port)

    print("\n" + "=" * 67, flush=True)
    if tunnel_url:
        print("  [+] ПАРСЕР УСПЕШНО ДОСТУПЕН В ИНТЕРНЕТЕ!", flush=True)
        print("=" * 67, flush=True)
        print("\n  [>>>] ССЫЛКА ДЛЯ ДРУГА (СКОПИРОВАНА В БУФЕР ОБМЕНА):", flush=True)
        print(f"        {tunnel_url}\n", flush=True)
        print("  Отправьте эту ссылку другу — она работает стабильно без лимита по времени.", flush=True)
        print("  (Ссылка уже в буфере обмена — нажмите Ctrl+V в чате/Telegram)", flush=True)
        copy_to_clipboard(tunnel_url)
        webbrowser.open(tunnel_url)
    else:
        print("  [!] Не удалось подключить онлайн-туннель.", flush=True)
        print(f"  Сервер работает локально: http://localhost:{port}", flush=True)

    print("\n" + "=" * 67, flush=True)
    print(f"  Локально на вашем ПК: http://localhost:{port}", flush=True)
    print("  Чтобы закрыть доступ, закройте это окно или нажмите Ctrl+C", flush=True)
    print("=" * 67 + "\n", flush=True)

    try:
        while True:
            time.sleep(1)
            if tunnel_proc and tunnel_proc.poll() is not None:
                print("  [!] Туннель был закрыт.", flush=True)
                break
    except KeyboardInterrupt:
        pass
    finally:
        print("\nОстановка сервера и туннеля...", flush=True)
        if tunnel_proc:
            try:
                tunnel_proc.terminate()
            except Exception:
                pass
        print("Работа завершена.", flush=True)


if __name__ == "__main__":
    main()
