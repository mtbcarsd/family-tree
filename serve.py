"""
serve.py — запускает локальный HTTP-сервер для папки output/.

Любое устройство в той же Wi-Fi/LAN сети сможет открыть
диаграмму в браузере или скачать HTML-файл по показанным ссылкам.

Использование:
    python serve.py            # порт 8080 по умолчанию
    python serve.py 9000       # указать другой порт
"""

import http.server
import socket
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
TARGET_FILE = "final_sunburst.html"


def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def main() -> None:
    if not OUTPUT_DIR.exists():
        print(f"[ОШИБКА] Папка не найдена: {OUTPUT_DIR}")
        sys.exit(1)

    html_file = OUTPUT_DIR / TARGET_FILE
    if not html_file.exists():
        print(f"[ОШИБКА] Файл не найден: {html_file}")
        print("Сначала запустите: python build_sunburst.py")
        sys.exit(1)

    local_ip = get_local_ip()
    size_mb = html_file.stat().st_size / 1_048_576

    handler = http.server.SimpleHTTPRequestHandler
    handler.extensions_map[".html"] = "text/html; charset=utf-8"

    print("=" * 55)
    print("  Локальный сервер запущен")
    print("=" * 55)
    print(f"\n  Файл:  {TARGET_FILE}  ({size_mb:.1f} MB)\n")
    print(f"  На этом компьютере:")
    print(f"    http://localhost:{PORT}/{TARGET_FILE}")
    print(f"\n  С телефона / другого устройства в сети:")
    print(f"    http://{local_ip}:{PORT}/{TARGET_FILE}")
    print(f"\n  Для скачивания — откройте ссылку и нажмите Ctrl+S")
    print(f"\n  Остановить: Ctrl+C")
    print("=" * 55)

    import os
    os.chdir(OUTPUT_DIR)

    with http.server.HTTPServer(("", PORT), handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\n  Сервер остановлен.")


if __name__ == "__main__":
    main()
