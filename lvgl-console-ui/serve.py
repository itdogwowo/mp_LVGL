#!/usr/bin/env python3
"""LVGL Console UI · Simulator — Python 啟動器（零相依，只用標準庫）

    python serve.py               → http://127.0.0.1:8610/ 並自動開瀏覽器
    python serve.py 9000          → 換 port
    python serve.py 9000 --no-open→ 不開瀏覽器

■ 這個資料夾就是根：index.html / projects.json / packages / projects 全在它下面。
  repo 裡其他東西（tools/simlab、ESP32 demo …）跟這套系統無關，不需要被 serve。

■ 為什麼有一個 Python 版：這台機器/這個專案的習慣是「PY 啟動、BAT 執行」。
  前端本身不需要 Node（靜態檔 + import map + 瀏覽器），只有 CLI 盤點/驗證
  那幾支工具是 Node；Python 這支自己實作了 /api/assets-report（見 cli/assets.py）。

API（跟 Node 版同一個形狀，面板兩種 server 都能用）：
    GET /api/assets-report?project=<id>   字元/圖示盤點
    GET /api/projects                     專案索引
"""

import json
import os
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from cli.assets import build_report  # noqa: E402  (path 要先設好)

# 主控台輸出固定 UTF-8（start.bat 會先 chcp 65001；這兩邊要一致才不會變亂碼）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_PORT = 8610
ARGS = sys.argv[1:]
PORT = next((int(a) for a in ARGS if a.isdigit()), DEFAULT_PORT)
OPEN = "--no-open" not in ARGS  # 預設開瀏覽器（雙擊/零參數的直覺）


class Handler(SimpleHTTPRequestHandler):
    """靜態檔（以工具資料夾為 root）+ 兩個 API。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    # ---- API ----
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/projects":
            return self._json_file(os.path.join(HERE, "projects.json"))
        if parsed.path == "/api/assets-report":
            project = parse_qs(parsed.query).get("project", [None])[0]
            try:
                return self._json(build_report(project))
            except Exception as e:  # 單一專案壞掉不該讓整個 server 掛
                return self._json({"error": str(e)}, status=500)
        return super().do_GET()

    def _json_file(self, path):
        with open(path, encoding="utf-8") as f:
            self._json(json.load(f))

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- 開發台：永遠拿最新的檔案 ----
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # 靜音；要除錯再打開


def main():
    os.chdir(HERE)
    url = "http://127.0.0.1:%d/" % PORT
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        print("[serve] cannot listen on port %d: %s" % (PORT, e))
        print("[serve] maybe it is already running -> " + url)
        print("[serve] or try another port: python serve.py %d" % (PORT + 1))
        return 1

    print("[serve] LVGL Console UI - Simulator", flush=True)
    print("[serve] root = " + HERE)
    print("[serve] " + url, flush=True)
    print("[serve] Ctrl+C to stop")
    if OPEN:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[serve] stopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

