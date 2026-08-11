#!/usr/bin/env python3
# ui_assets_server.py — LVGL UI Asset Studio（Web GUI）
#
# 完全自包含的 LVGL UI 資產工具:
#   - 零參數啟動（可選 --port / --no-browser）
#   - 自動建立 workspace/{design,cache,out}
#   - 網頁介面:上傳設計稿 → 掃描 → 生成 icon / 中文字體 / 動效 helper
#   - 產物全部在 tools/workspace/out/
#
# 用法:
#   cd /Users/user/Documents/code/git/mp_LVGL
#   python3 tools/ui_assets_server.py
from __future__ import annotations

import argparse
import datetime
import io
import json
import re
import shutil
import tempfile
import threading
import urllib.parse
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from assets import (
    CACHE_DIR,
    CONFIG_FILE,
    DESIGN_DIR,
    OUT_DIR,
    TOOLS_DIR,
    WEB_DIR,
    WORKSPACE,
    ensure_workspace,
    load_config,
    save_config,
)
from assets import designlib, fxgen, icons, scanner, tokengen, uiframe, vendor, zhfont

# ============ 背景執行緒:log 緩衝 + 生成佇列 ============

class Studio:
    """全域狀態:log 緩衝、scan 結果、生成佇列。"""

    def __init__(self):
        self._logs: list[tuple[int, str]] = []
        self._lock = threading.Lock()
        self._seq = 0
        self._q: list[dict] = []
        self._q_lock = threading.Lock()
        self._q_cond = threading.Condition(self._q_lock)
        self.scan_cache = None
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    # ---- log ----
    def log(self, msg: str) -> None:
        with self._lock:
            self._seq += 1
            self._logs.append((self._seq, str(msg)))
            if len(self._logs) > 5000:
                self._logs = self._logs[-3000:]

    def logs_since(self, after: int) -> tuple[list[str], int]:
        with self._lock:
            out = [t for i, t in self._logs if i > after]
            last = self._logs[-1][0] if self._logs else after
        return out, last

    # ---- scan ----
    def scan(self, design_name: str | None = None) -> dict:
        """掃指定 design（預設第一個有 html 的）的設計稿。"""
        self._migrate_if_needed()
        if design_name:
            meta = designlib.read_design(design_name)
        else:
            designs = designlib.list_designs()
            meta = designs[0] if designs else None
        if not meta or not meta.get("pages"):
            self.log("掃描設計稿 … (無)")
            self.scan_cache = {"icons": [], "chars": "", "char_count": 0,
                               "fx": {"animations": [], "transitions": [],
                                      "hover": []}}
            return self.scan_cache
        self.log("掃描設計稿 …")
        self.scan_cache = scanner.scan(Path(meta["dir"]))
        s = self.scan_cache
        self.log(
            f"掃描完成: {len(s['icons'])} 個 lucide 圖示, "
            f"{s['char_count']} 個非 ASCII 字符, "
            f"{len(s['fx']['animations'])} 個動畫, "
            f"{len(s['fx']['hover'])} 個 hover 狀態"
        )
        return self.scan_cache

    def _migrate_if_needed(self) -> None:
        """design 庫空 + 舊 workspace/design 有檔 → 遷移成第一個 design。"""
        if designlib.list_designs():
            return
        if DESIGN_DIR.exists() and any(DESIGN_DIR.iterdir()):
            m = designlib.migrate_legacy(DESIGN_DIR)
            if m:
                self.log(f"已遷移舊設計稿 → design/{Path(m['dir']).name} "
                         f"({len(m['pages'])} 頁, {len(m['interactions'])} 互動)")

    # ---- generate 佇列 ----
    def enqueue(self, task: str, mapping: dict[str, str], extra_chars: str,
                design: str | None = None) -> None:
        with self._q_cond:
            self._q.append({"task": task, "mapping": mapping,
                            "extra_chars": extra_chars, "design": design})
            self._q_cond.notify()

    def _design_dir(self, design: str | None = None) -> Path:
        """回傳指定 design（或第一個有設計稿的）資料夾（供 zh 字體掃描）。"""
        self._migrate_if_needed()
        if design:
            d = designlib.DESIGN_LIB / design
            if d.exists():
                return d
        for meta in designlib.list_designs():
            d = Path(meta["dir"])
            if any(d.glob("*.html")):
                return d
        return Path(meta["dir"]) if designlib.list_designs() else DESIGN_DIR

    def _worker_loop(self) -> None:
        while True:
            with self._q_cond:
                while not self._q:
                    self._q_cond.wait()
                item = self._q.pop(0)
            try:
                self._run(item)
            except Exception as e:
                self.log(f"✗ 生成失敗: {e}")

    def _run(self, item: dict) -> None:
        task = item["task"]
        mapping = item["mapping"] or dict(icons.LUCIDE_TO_MS)
        extra = item["extra_chars"] or ""
        design = item.get("design")
        self.log(f"── 開始生成: {task}"
                 + (f"（design: {design}）" if design else "") + " ──")
        # 輸出目標:design 模式下真相寫 assets/{fonts,icons,tokens}/，
        # 再複本一份到 lvgl/ui/src/ 給板子部署；否則 workspace/out
        if design:
            ui_out = designlib.lvgl_path(design)
            src_out = designlib.lvgl_src_path(design)        # 部署複本（lvgl/ui/src/）
            assets_fonts = designlib.assets_subpath(design, "fonts")
            assets_icons = designlib.assets_subpath(design, "icons")
            assets_tokens = designlib.assets_subpath(design, "tokens")
            design_dir = designlib.DESIGN_LIB / design
        else:
            ui_out = OUT_DIR
            src_out = OUT_DIR
            assets_fonts = assets_icons = assets_tokens = OUT_DIR
            design_dir = self._design_dir(design)

        def _copy_to_src(names: list[str], from_dir: Path) -> None:
            """把 assets/ 產出複本到 lvgl/ui/src/（板子部署用）。"""
            if not design or not src_out.exists():
                return
            for n in names:
                src_file = from_dir / n
                if src_file.exists():
                    shutil.copy2(src_file, src_out / n)

        if task in ("icons", "all"):
            # 真相寫 assets/icons/，複本到 lvgl/ui/src/
            r = icons.generate_icons(mapping, self.log, out_root=assets_icons)
            _copy_to_src(["icons_16.bin", "lv_icons.py"], assets_icons)
            self.log(f"✓ icons: {r['count']} 個圖示, 缺碼點 {r['missing_codepoints']}")
        if task in ("zh", "all"):
            r = zhfont.generate_zh(design_dir, extra, log=self.log, out_root=assets_fonts)
            _copy_to_src(["zh_hant_16.bin"], assets_fonts)
            self.log(f"✓ zh: {r['char_count']} 個字符, 缺 {r['missing']}")
        if task in ("fx", "all"):
            if not self.scan_cache or design != getattr(self, "_scan_design", None):
                self.scan_cache = self.scan(design)
                self._scan_design = design
            # fx 只有 .py + .md，直接寫 src（無獨立 assets 區）
            r = fxgen.generate_fx(self.scan_cache, self.log, out_root=src_out)
            self.log(f"✓ fx: {r['animations']} 動畫, {r['hover_states']} hover 狀態")
        if task in ("tokens", "all"):
            # 真相寫 assets/tokens/，py 複本到 lvgl/ui/src/
            r = tokengen.generate_tokens(design_dir, log=self.log, out_root=assets_tokens)
            if r.get("ok"):
                _copy_to_src(["design-tokens.py"], assets_tokens)
                self.log(f"✓ tokens: {r['counts']}")
        if task in ("ui", "all"):
            # project_root = tools 的上一層 = mp_LVGL（工具內部推定,不需外部輸入）
            project_root = TOOLS_DIR.parent
            r = uiframe.generate(project_root, ui_out, self.log)
            self.log(f"✓ ui 框架: {r['pages']} 頁 + {len(r['files'])} 個檔案")
        self.log(f"── 完成: {task} ──")


# ============ HTTP Handler ============

class Handler(BaseHTTPRequestHandler):
    studio: Studio  # 由 make_handler 注入
    web_dir: Path

    # ---- 工具 ----
    def _json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")  # 跨源模擬器 iframe
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _err(self, msg: str, code: int = 400) -> None:
        self._json({"ok": False, "error": str(msg)}, code)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(n) if n else b""

    # ---- GET / HEAD（HEAD 給模擬器 wasm_file_api 檢查檔案存在用） ----
    def do_GET(self) -> None:  # noqa: N802
        url = urllib.parse.urlparse(self.path)
        if url.path == "/":
            return self._serve_file(WEB_DIR / "index.html", "text/html")
        if url.path == "/api/state":
            return self._state()
        if url.path == "/api/log":
            return self._log()
        if url.path == "/api/msnames":
            return self._msnames()
        if url.path == "/api/ui_state":
            return self._ui_state()
        if url.path == "/api/designs":
            return self._designs()
        if url.path == "/api/design/exportzip":
            return self._design_export_zip()
        if url.path == "/api/design/render":
            return self._design_render()
        if url.path == "/api/design/simcode":
            return self._design_simcode()
        if url.path == "/api/design/savecode":
            return self._design_savecode()
        if url.path == "/api/design/files":
            return self._design_files()
        if url.path == "/api/design/simfiles":
            return self._design_simfiles()
        if url.path == "/api/design/file":
            return self._design_file_get()
        if url.path.startswith("/preview/"):
            return self._serve_preview(url.path)
        if url.path.startswith("/dlib/"):
            return self._serve_dlib(url.path)
        if url.path.startswith("/cache/vendor/"):
            return self._serve_vendor(url.path)
        if url.path == "/sim" or url.path.startswith("/sim/"):
            return self._serve_sim(url.path)
        if url.path.startswith("/cache/"):
            return self._serve_cache(url.path)
        self._err("not found", 404)

    def _serve_file(self, path: Path, ctype: str) -> None:
        if not path.exists():
            return self._err("not found", 404)
        st = path.stat()
        # 條件式請求:Last-Modified + ETag → 304,避免每次按 ▶ 重載模擬器 iframe
        # 都把 micropython.js / firmware.wasm(5.5MB) 重新下載一遍。
        lm = datetime.datetime.fromtimestamp(
            st.st_mtime, datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        etag = '"%x-%x"' % (st.st_mtime_ns & 0xFFFFFFFF, st.st_size)
        inm = self.headers.get("If-None-Match")
        ims = self.headers.get("If-Modified-Since")
        if (inm is not None and inm == etag) or \
           (ims is not None and ims == lm):
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Last-Modified", lm)
            self.end_headers()
            return
        body = path.read_bytes()
        self.send_response(200)
        is_text = ctype.startswith("text/") or ctype in (
            "application/javascript", "application/json")
        self.send_header("Content-Type",
                         ctype + ("; charset=utf-8" if is_text else ""))
        self.send_header("Content-Length", str(len(body)))
        # 模擬器/離線資源是靜態檔:允許瀏覽器快取,但每次重新驗證(304)
        # 開發時改檔仍能生效(Last-Modified 變了就會 200)。
        self.send_header("Cache-Control", "no-cache")
        self.send_header("ETag", etag)
        self.send_header("Last-Modified", lm)
        self.send_header("Access-Control-Allow-Origin", "*")  # 跨源模擬器 iframe
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _serve_cache(self, path: str) -> None:
        name = Path(path[len("/cache/"):]).name  # 只取檔名,防穿越
        p = CACHE_DIR / name
        if not p.exists():
            return self._err("not found", 404)
        ctype = "font/ttf" if p.suffix == ".ttf" else "application/octet-stream"
        self._serve_file(p, ctype)

    def _state(self) -> None:
        cfg = load_config()
        design = [
            {"name": p.name, "size": p.stat().st_size}
            for p in sorted(DESIGN_DIR.iterdir()) if p.is_file()
        ] if DESIGN_DIR.exists() else []
        out = [
            {"name": p.name, "size": p.stat().st_size}
            for p in sorted(OUT_DIR.iterdir()) if p.is_file()
        ] if OUT_DIR.exists() else []
        self._json({
            "ok": True,
            "workspace": str(WORKSPACE),
            "design": design,
            "out": out,
            "icons_mapping": cfg.get("icons", {}),
            "icons_default": icons.LUCIDE_TO_MS,
            "extra_chars": cfg.get("extra_chars", ""),
            "has_scan": self.studio.scan_cache is not None,
        })

    def _log(self) -> None:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        after = int(q.get("after", ["0"])[0])
        lines, last = self.studio.logs_since(after)
        self._json({"ok": True, "lines": lines, "last": last})

    def _serve_preview(self, path: str) -> None:
        """提供「離線完整 HTML」版設計稿（script 指本地 vendor,iframe 直接開）。

        page 路徑可以是多段（如 html/page/control_panel.html），把 design 後的
        所有段 join 成相對路徑再交給 render_full_html（其內部 _resolve_html_path
        會做 html/ 與 html/page/ 的解析 + 防穿越）。
        """
        parts = path[len("/preview/"):].split("/")
        if len(parts) < 2:
            return self._err("not found", 404)
        design_name = urllib.parse.unquote(parts[0])
        # join 剩餘段成相對頁面路徑（保留 html/page/ 子目錄），逐段 unquote
        page_file = "/".join(urllib.parse.unquote(p) for p in parts[1:] if p)
        if not page_file:
            return self._err("not found", 404)
        html = designlib.render_full_html(design_name, page_file)
        if not html:
            return self._err("not found", 404)
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_dlib(self, path: str) -> None:
        """提供 design 庫內的檔（/dlib/{design}/{file}）。

        目录 URL（結尾有/無斜線皆可）→ Apache-style HTML 目錄列表，
        让模擬器 framework shim 的 _preload_dir 能解析 <a href="xxx.py"> 抓檔。
        基於安全：只對三個規範化區（lvgl/、html/、assets/）下的目錄放行列表，
        design 根與其他子目錄仍回 403，避免暴露結構。
        """
        parts = path[len("/dlib/"):].split("/")
        if len(parts) < 2:
            return self._err("not found", 404)
        design_name = parts[0]
        fname = "/".join(parts[1:])
        base = designlib.DESIGN_LIB / design_name
        p = (base / fname).resolve()
        # 防穿越:必須在該 design 目錄內
        if not str(p).startswith(str(base.resolve())):
            return self._err("forbidden", 403)
        # 目錄 → Apache-style 列表（僅限三個規範化區，避免暴露其他結構）
        if p.is_dir():
            rel = p.relative_to(base.resolve()).as_posix()
            head = rel.split("/", 1)[0] if rel and rel != "." else ""
            if head not in designlib.PROTECTED_DIRS:
                return self._err("forbidden", 403)
            return self._serve_dlib_dir(design_name, p)
        if not p.is_file():
            return self._err("not found", 404)
        ctype = ("text/html" if p.suffix == ".html" else
                 "text/css" if p.suffix == ".css" else
                 "application/json" if p.suffix == ".json" else
                 "application/octet-stream")
        self._serve_file(p, ctype)

    def _serve_dlib_dir(self, design_name: str, dir_path: Path) -> None:
        """Apache-style HTML 目錄列表（給 _preload_dir 解析用）。

        列出的副檔名依目錄所屬區域決定：
          - lvgl/、ui/、assets/tokens  → .py（程式碼 + token helper）
          - html/                      → .html（網頁設計稿）
          - assets/fonts、assets/icons → .bin + .py（字體/圖示資源 + helper）
        href 用絕對路徑 /dlib/{design}/{rel}，與 _preload_dir 的 href 解析邏輯相容。
        """
        rel_base = dir_path.relative_to(designlib.DESIGN_LIB).as_posix()
        # rel_base 形如 "{design}/{region}/..."，取 region（第二段）與其後路徑
        parts = rel_base.split("/", 2)
        # parts[0] = design, parts[1] = region (html/lvgl/assets 等), parts[2] = 子路徑
        region = parts[1] if len(parts) >= 2 else ""
        sub = parts[2] if len(parts) >= 3 else ""
        if region == "html":
            exts = {".html"}
        elif region == designlib.ASSETS_DIR and sub.split("/", 1)[0] in ("fonts", "icons"):
            exts = {".bin", ".py"}
        else:  # lvgl / ui / assets/tokens 等
            exts = {".py"}
        rows = []
        for child in sorted(dir_path.iterdir()):
            if not child.is_file() or child.suffix.lower() not in exts:
                continue
            href = "/dlib/{}/{}".format(rel_base, child.name)
            rows.append('<a href="{}">{}</a>'.format(href, child.name))
        html = ("<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
                "<title>Index of {}</title></head><body>"
                "<h1>Index of /{}</h1><ul><li>{}</li></ul></body></html>").format(
            rel_base, rel_base, "</li><li>".join(rows))
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _designs(self) -> None:
        """design 庫清單（含每 design 的 meta + 互動 API 數 + lvgl 產出狀態 + 資產種類）。"""
        self.studio._migrate_if_needed()
        out = []
        for meta in designlib.list_designs():
            name = Path(meta["dir"]).name
            out.append({
                "name": name,
                "title": meta.get("name", name),
                "width": meta.get("width", 320),
                "height": meta.get("height", 240),
                "pages": len(meta.get("pages", [])),
                "interactions": meta.get("interactions", []),
                "has_meta": meta.get("has_meta", False),
                "kind": meta.get("kind") or designlib.design_kind(name),
                "lvgl": designlib.lvgl_status(name),
            })
        self._json({"ok": True, "designs": out})

    def _design_pages(self, design_name: str | None = None
                      ) -> tuple[list[dict], dict, dict]:
        """依 design 組 PAGES + ROUTES + META。

        routes 委派給 designlib.compute_routes（與 render_full_html 注入的
        postMessage 橋接同一份邏輯，避免兩處 drift）。
        """
        self.studio._migrate_if_needed()
        if design_name:
            meta = designlib.read_design(design_name)
        else:
            designs = designlib.list_designs()
            meta = designs[0] if designs else None
        if not meta or not meta.get("pages"):
            return [], {}, {}
        pages = []
        for p in meta["pages"]:
            pages.append({
                "id": p["id"],
                "file": "dlib/{}/{}".format(Path(meta["dir"]).name, p["file"]),
                "title": p["title"],
                "tag": p.get("tag", "feature"),
            })
        routes = designlib.compute_routes(Path(meta["dir"]).name)
        return pages, routes, meta

    def _design_simcode(self) -> None:
        """生成模擬器代碼:單頁展示碼 或 ui 框架模式。"""
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        design_name = q.get("design", [None])[0]
        page_file = q.get("page", [None])[0]
        mode = q.get("mode", [None])[0]
        if not design_name:
            return self._err("需要 design")
        if mode == "framework":
            origin = "http://localhost:{}".format(self.server.server_port)
            meta = designlib.read_design(design_name) or {}
            W = int(meta.get("width", 320))
            H = int(meta.get("height", 240))
            lv, ui = designlib._ui_candidates(design_name)
            if ui is not None:
                d_path = ui.relative_to(designlib.DESIGN_LIB).as_posix()
            else:
                d_path = design_name + "/lvgl/ui"
            # lvgl 根 = ui 的 parent（如果 ui 是 lvgl/ui 則 lvgl 根 = lvgl/；如果 ui 就是 design 根或 ui/ 平鋪，則 lvgl 根 = design 根或 ui/）
            try:
                lvgl_rel = lv.relative_to(designlib.DESIGN_LIB).as_posix()
            except Exception:
                lvgl_rel = design_name

            code = designlib.render_framework_code(
                origin=origin,
                design=design_name,
                width=W,
                height=H,
                dlib_ui=f"{origin}/dlib/{d_path}",
                dlib_src=f"{origin}/dlib/{d_path}/src",
                dlib_page=f"{origin}/dlib/{d_path}/page",
                dlib_lvgl_root=f"{origin}/dlib/{lvgl_rel}",
            )
        else:
            code = designlib.simcode(design_name, page_file or "launcher.html")
        self._json({"ok": True, "code": code})

    def _design_savecode(self) -> None:
        """把代碼儲存到 design/lvgl/ui/ 下（跟 design 走）。"""
        data = json.loads(self._body() or b"{}")
        design_name = data.get("design", "")
        filename = data.get("filename", "sim_demo.py")
        code = data.get("code", "")
        if not design_name or not code:
            return self._err("需要 design 與 code")
        safe = Path(filename).name
        ui_dir = designlib.lvgl_path(design_name) / "ui"
        ui_dir.mkdir(parents=True, exist_ok=True)
        (ui_dir / safe).write_text(code, encoding="utf-8")
        self.studio.log(f"💾 代碼已存: design/{design_name}/lvgl/ui/{safe}")
        self._json({"ok": True, "saved": safe})

    def _design_render(self) -> None:
        """回傳指定 design 某頁的可原生嵌入片段(限域 CSS + body + 本地 script)。"""
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        design_name = q.get("design", [None])[0]
        page_file = q.get("page", [None])[0]
        if not design_name or not page_file:
            return self._err("需要 design 與 page 參數")
        # 防穿越:page_file 只取檔名
        page_file = Path(page_file).name
        r = designlib.extract_render(design_name, page_file)
        if not r:
            return self._err("設計稿不存在")
        # 附頁面清單(供原生頁面按鈕列)。
        # 規範化結構下 page 有 web_file/lvgl_file 雙欄位；為了向後相容前端讀 p.file，
        # 補一個 file 別名（優先 web_file，否則 lvgl_file），讓既有 JS 不用改。
        meta = designlib.read_design(design_name) or {}
        pages_out = []
        for p in meta.get("pages", []):
            pp = dict(p)  # 淺拷貝避免改到原 meta
            if "file" not in pp:
                pp["file"] = pp.get("web_file") or pp.get("lvgl_file") or ""
            pages_out.append(pp)
        r["pages"] = pages_out
        r["ok"] = True
        self._json(r)

    def _serve_vendor(self, path: str) -> None:
        """提供離線 vendor 資源(/cache/vendor/lucide.min.js 或子目錄檔)。"""
        rel = path[len("/cache/vendor/"):]
        p = (vendor.VENDOR_DIR / rel).resolve()
        base = vendor.VENDOR_DIR.resolve()
        if not str(p).startswith(str(base)):
            return self._err("forbidden", 403)
        if not p.exists() or not p.is_file():
            return self._err("not found", 404)
        ctype = "application/javascript" if p.suffix == ".js" else (
            "text/css" if p.suffix == ".css" else "application/octet-stream")
        self._serve_file(p, ctype)

    def _serve_sim(self, path: str) -> None:
        """提供離線模擬器(/sim → index.html,/sim/xxx → 資源)。"""
        idx = vendor.SIM_DIR / "index.html"
        if not idx.exists():
            return self._err("模擬器未下載(離線資源),請連網啟動一次", 404)
        if path == "/sim" or path == "/sim/":
            return self._serve_file(idx, "text/html")
        rel = path[len("/sim/"):]
        p = (vendor.SIM_DIR / rel).resolve()
        base = vendor.SIM_DIR.resolve()
        if not str(p).startswith(str(base)):
            return self._err("forbidden", 403)
        if not p.exists() or not p.is_file():
            return self._err("not found", 404)
        ctype = ("text/html" if p.suffix == ".html" else
                 "application/javascript" if p.suffix == ".js" else
                 "text/css" if p.suffix == ".css" else
                 "application/wasm" if p.suffix == ".wasm" else
                 "application/octet-stream")
        self._serve_file(p, ctype)

    # ---- design 庫 POST ----
    def _design_new(self) -> None:
        data = json.loads(self._body() or b"{}")
        name = data.get("name", "")
        if not name:
            return self._err("缺少 name")
        meta = designlib.create_design(
            name, title=data.get("title", ""),
            width=int(data.get("width", 320)),
            height=int(data.get("height", 240)))
        self.studio.log(f"＋ 新增 design: {Path(meta['dir']).name} "
                        f"({meta['width']}×{meta['height']})")
        self._json({"ok": True, "design": Path(meta["dir"]).name})

    def _design_scan(self) -> None:
        data = json.loads(self._body() or b"{}")
        name = data.get("name", "")
        if not name or not (designlib.DESIGN_LIB / name).exists():
            return self._err("design 不存在")
        meta = designlib.scan_design(name)
        self.studio.log(f"🔍 重新掃描 {name}: "
                        f"{len(meta['pages'])} 頁, {len(meta['interactions'])} 互動")
        self._json({"ok": True, "pages": len(meta["pages"]),
                    "interactions": len(meta["interactions"])})

    # ---- 編輯器：列出/讀取/儲存 design 檔案（html/、lvgl/、assets/ 三區） ----
    _EDITABLE_EXTS = (".py", ".html", ".htm", ".css", ".js", ".mjs",
                      ".json", ".md", ".txt")

    def _design_files(self) -> None:
        """列出 design 的可編輯檔案（相對路徑 + 大小）。"""
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        design_name = (q.get("design", [None])[0] or "").strip()
        d = designlib.DESIGN_LIB / design_name
        if not d.is_dir():
            return self._err("design 不存在")
        files = []
        for region in ("html", "lvgl", "assets"):
            rd = d / region
            if not rd.is_dir():
                continue
            for p in sorted(rd.rglob("*")):
                if p.is_file() and p.suffix.lower() in self._EDITABLE_EXTS:
                    files.append({
                        "path": p.relative_to(d).as_posix(),
                        "size": p.stat().st_size,
                        "region": region,
                    })
        self._json({"ok": True, "design": design_name, "files": files})

    def _design_simfiles(self) -> None:
        """一次回傳 design 的 lvgl ui .py 內容（模擬器 JS 預載用）。

        路徑相對 ui 根（如 registry.py / page/control_panel.py / src/lv_icons.py），
        讓 lvgl.html 一次請求就寫完整個 /_wsp/{design}/，省掉逐檔 XHR。
        """
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        design_name = (q.get("design", [None])[0] or "").strip()
        if not design_name:
            return self._err("需要 design 參數")
        _lv, ui = designlib._ui_candidates(design_name)
        if ui is None or not ui.is_dir():
            return self._err("design 不存在")
        files: dict[str, str] = {}
        for p in sorted(ui.rglob("*.py")):
            rel = p.relative_to(ui).as_posix()
            files[rel] = p.read_text(encoding="utf-8", errors="replace")
        self._json({"ok": True, "design": design_name, "files": files})

    def _design_file_get(self) -> None:
        """讀取 design 內單一文字檔內容（編輯器用）。"""
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        design_name = (q.get("design", [None])[0] or "").strip()
        path = (q.get("path", [None])[0] or "").strip()
        p = (designlib.DESIGN_LIB / design_name / path).resolve()
        base = (designlib.DESIGN_LIB / design_name).resolve()
        if not str(p).startswith(str(base)):
            return self._err("forbidden", 403)
        if not p.is_file() or p.suffix.lower() not in self._EDITABLE_EXTS:
            return self._err("not found", 404)
        self._json({"ok": True, "design": design_name,
                    "path": p.relative_to(base).as_posix(),
                    "content": p.read_text(encoding="utf-8", errors="replace")})

    def _design_file_save(self) -> None:
        """儲存 design 內單一文字檔（編輯器用）。

        只允許 html/、lvgl/、assets/（PROTECTED_DIRS）下的文字檔；
        儲存後自動重新掃描（頁面/導航可能變動）。
        """
        data = json.loads(self._body() or b"{}")
        design_name = data.get("design", "")
        path = data.get("path", "")
        content = data.get("content", "")
        if not design_name or not path:
            return self._err("需要 design 與 path")
        d = designlib.DESIGN_LIB / design_name
        p = (d / path).resolve()
        base = d.resolve()
        if not str(p).startswith(str(base)):
            return self._err("forbidden", 403)
        rel = p.relative_to(base).as_posix()
        head = rel.split("/", 1)[0]
        if head not in designlib.PROTECTED_DIRS:
            return self._err("forbidden: 只允許 html/ lvgl/ assets/ 下的檔案")
        if p.suffix.lower() not in self._EDITABLE_EXTS:
            return self._err(f"不支援編輯副檔名: {p.suffix}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        # 儲存後重新掃描（HTML 頁面 / LVGL @register 可能變動）
        try:
            designlib.scan_design(design_name)
        except Exception as e:
            self.studio.log(f"⚠ 儲存後掃描失敗: {e}")
        self.studio.log(f"💾 儲存: {design_name}/{rel} ({len(content)} chars)")
        self._json({"ok": True, "saved": rel})

    def _design_upload(self) -> None:
        ctype = self.headers.get("Content-Type", "")
        m = re.search(r"boundary=([^;]+)", ctype)
        if not m:
            return self._err("multipart 格式錯誤")
        boundary = m.group(1).strip().strip('"').encode()
        body = self._body()
        # 目標 design:query ?design=NAME > filename 前綴 {design}/ > 第一個
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        q_design = q.get("design", [None])[0]
        self.studio._migrate_if_needed()
        designs = designlib.list_designs()
        first = Path(designs[0]["dir"]).name if designs else "lvgl-console-ui"
        # 設計稿不限制副檔名（html/css/js/png 都要）
        saved = []
        for part in body.split(b"--" + boundary):
            if b"\r\n\r\n" not in part:
                continue
            head, content = part.split(b"\r\n\r\n", 1)
            fm = re.search(rb'filename="([^"]*)"', head)
            if not fm:
                continue
            fname = fm.group(1).decode("utf-8", "replace")
            content = content.rstrip(b"\r\n")
            if not fname:
                continue
            # 決定目標 design 與檔名
            if "/" in fname:
                design_name, fname2 = fname.split("/", 1)
            else:
                design_name, fname2 = q_design or first, fname
            d = designlib.DESIGN_LIB / design_name
            if not d.exists():
                designlib.create_design(design_name)
            safe2 = Path(fname2).name
            (d / safe2).write_bytes(content)
            saved.append(f"{design_name}/{safe2}")
            self.studio.log(f"↑ 已上傳 {saved[-1]} ({len(content)} bytes)")
        # 上傳後自動重新掃描(涉及到的 design)
        for design_name in {s.split("/")[0] for s in saved}:
            designlib.scan_design(design_name)
        self._json({"ok": True, "saved": saved})

    def _design_delete(self) -> None:
        data = json.loads(self._body() or b"{}")
        name = data.get("name", "")
        d = designlib.DESIGN_LIB / name
        if not d.exists():
            return self._err("design 不存在")
        shutil.rmtree(d)
        self.studio.log(f"🗑 刪除 design: {name}")
        self._json({"ok": True})

    def _design_import_zip(self) -> None:
        """上傳 ZIP 覆蓋指定 design。

        POST multipart/form-data 到 /api/design/importzip?design=NAME（或表單裡 design=NAME）
        欄位: zip=檔案（必填）, design=目標 design（建議 query 或 form 都可）

        流程:
          1. 解析目標 design（query 優先 > form 欄位 > 預設錯誤）
          2. 刪除目標 design 目錄下全部內容（含 .py / lvgl/ 等）
          3. 解壓 zip 內容到該 design 目錄（zip 根可以是 {design}/ 包一層或平鋪）
          4. 掃描 → 更新 design.json
        """
        ctype = self.headers.get("Content-Type", "")
        m = re.search(r"boundary=([^;]+)", ctype)
        if not m:
            return self._err("multipart 格式錯誤")
        boundary = m.group(1).strip().strip('"').encode()
        body = self._body()

        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        design_name = (q.get("design", [None])[0] or "").strip()

        zip_bytes: bytes | None = None
        form_design: str | None = None
        for part in body.split(b"--" + boundary):
            if b"\r\n\r\n" not in part:
                continue
            head, content = part.split(b"\r\n\r\n", 1)
            content = content.rstrip(b"\r\n")
            head_text = head.decode("latin-1", "replace")
            name_m = re.search(rb'name="([^"]*)"', head)
            field_name = name_m.group(1).decode("utf-8", "replace") if name_m else ""
            fm = re.search(rb'filename="([^"]*)"', head)
            if fm:
                fname = fm.group(1).decode("utf-8", "replace")
                if Path(fname).suffix.lower() == ".zip":
                    zip_bytes = content
            elif field_name == "design":
                form_design = content.decode("utf-8", "replace").strip()

        if not design_name and form_design:
            design_name = form_design
        if not design_name:
            return self._err("缺少目標 design 參數（?design=NAME 或 form design=NAME）")
        if not zip_bytes:
            return self._err("未找到 ZIP 檔")

        safe_name = re.sub(r"[^A-Za-z0-9_-]", "-", design_name).strip("-")
        if not safe_name:
            return self._err("design 名稱無效")

        dest = designlib.DESIGN_LIB / safe_name
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            extract_root = td_path / "in"
            extract_root.mkdir()
            try:
                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                    for name in zf.namelist():
                        parts = Path(name).parts
                        if ".." in parts:
                            return self._err(f"ZIP 包含不安全路徑: {name}")
                        if parts and (
                            parts[0] in ("/", "\\") or
                            (len(parts[0]) == 2 and parts[0][1] == ":")):
                            return self._err(f"ZIP 包含絕對路徑: {name}")
                    zf.extractall(extract_root)
            except zipfile.BadZipFile:
                return self._err("ZIP 檔損毀或不是有效的壓縮檔")

            candidates = [extract_root]
            top_dirs = [p for p in extract_root.iterdir() if p.is_dir()]
            top_files = [p for p in extract_root.iterdir() if p.is_file()]
            if len(top_dirs) == 1 and not top_files:
                candidates = [top_dirs[0]]
            elif any(d.name == safe_name for d in top_dirs):
                candidates = [d for d in top_dirs if d.name == safe_name]

            src = candidates[0]
            if not any(src.iterdir()):
                return self._err("ZIP 解壓後為空")

            def _looks_like_ui_root(path: Path) -> bool:
                """launcher.py (+ app.py) + page/ 目錄 + 無 lvgl/ = ui 根"""
                has_launcher = (path / "launcher.py").is_file()
                has_app = (path / "app.py").is_file()
                has_page_dir = (path / "page").is_dir()
                has_lvgl_dir = (path / "lvgl").is_dir()
                return (has_launcher or has_app) and has_page_dir and not has_lvgl_dir

            dest.mkdir(parents=True, exist_ok=True)
            # 關鍵：只清 LVGL 程式碼區（lvgl/, ui/, 根的非 web 檔），保留網頁區（HTML/CSS/design.json）
            designlib.clear_lvgl_code_only(safe_name, keep_web_assets=True)

            src_items = list(src.iterdir())
            web_like: list[str] = []
            for p in src_items:
                if p.is_file() and p.suffix.lower() in designlib.WEB_ASSET_EXTS:
                    if p.name != "design.json":
                        web_like.append(p.name)

            lvgl_root_pkg = any(
                (src / name).exists() and (src / name).is_dir()
                for name in designlib.LVGL_CODE_DIRS)
            # Case D（規範化）：ZIP 有 html/ 或 assets/ 子目錄 → 規範化三區結構，
            # 直接把各區 copytree 到 dest 對應目錄（html/、assets/ 必保留；lvgl/ 亦然）
            has_html_dir = (src / "html").is_dir()
            has_assets_dir = (src / designlib.ASSETS_DIR).is_dir()
            moved_to_ui = False
            if has_html_dir or has_assets_dir:
                # 規範化結構：逐區複製
                for region in ("html", designlib.ASSETS_DIR, "lvgl"):
                    s = src / region
                    if not s.exists():
                        continue
                    d = dest / region
                    if d.exists():
                        shutil.rmtree(d)
                    shutil.copytree(s, d)
                self.studio.log(
                    f"ℹ 規範化結構匯入: html/+lvgl/+assets/ 各區就位")
            elif lvgl_root_pkg:
                # Case A: ZIP 已經有 lvgl/ 或 ui/ 子目錄 → 直接放進 dest 根
                for name in designlib.LVGL_CODE_DIRS:
                    s = src / name
                    if not s.exists():
                        continue
                    d = dest / name
                    if d.exists():
                        shutil.rmtree(d)
                    shutil.copytree(s, d)
            elif _looks_like_ui_root(src):
                # Case B: ZIP 根本身就是 ui 內容 → 搬進 lvgl/ui/
                ui_dir = dest / "lvgl" / "ui"
                ui_dir.mkdir(parents=True, exist_ok=True)
                for p in src_items:
                    t = ui_dir / p.name
                    if t.exists():
                        if t.is_dir():
                            shutil.rmtree(t)
                        else:
                            t.unlink()
                    if p.is_dir():
                        shutil.copytree(p, t)
                    else:
                        shutil.copy2(p, t)
                moved_to_ui = True
            else:
                # Case C: 散落的 .py / page/ / src/ 等 → 裝進 lvgl/ui/
                ui_dir = dest / "lvgl" / "ui"
                ui_dir.mkdir(parents=True, exist_ok=True)
                for p in src_items:
                    t = ui_dir / p.name
                    if t.exists():
                        if t.is_dir():
                            shutil.rmtree(t)
                        else:
                            t.unlink()
                    if p.is_dir():
                        shutil.copytree(p, t)
                    else:
                        shutil.copy2(p, t)
                moved_to_ui = True

            if web_like:
                self.studio.log(
                    f"ℹ 匯入 ZIP 內含 {len(web_like)} 個網頁類檔案"
                    f"（{', '.join(web_like[:3])}…）已跳過，不覆蓋設計稿")
            if moved_to_ui:
                self.studio.log("ℹ 匯入的程式碼自動歸檔到 lvgl/ui/")

        designlib.scan_design(safe_name)
        meta = designlib.read_design(safe_name) or {}
        pages = len(meta.get("pages", []))
        kind = designlib.design_kind(safe_name)
        self.studio.log(
            f"📦 匯入 LVGL 程式碼到 {safe_name} [{kind}]: 清理程式碼區,"
            f" 解壓並掃描 ({pages} 頁,"
            f" {len(meta.get('interactions', []))} 互動)")
        self._json({"ok": True, "design": safe_name,
                    "pages": pages,
                    "kind": kind,
                    "moved_to_ui": moved_to_ui,
                    "skipped_web_assets": len(web_like),
                    "interactions": len(meta.get("interactions", []))})

    def _design_export_zip(self) -> None:
        """匯出指定 design 成 ZIP 下載。

        GET /api/design/exportzip?design=NAME
        → 回傳 application/zip 檔: {NAME}.zip（zip 根為 {NAME}/ 目錄）
        """
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        design_name = (q.get("design", [None])[0] or "").strip()
        if not design_name:
            return self._err("缺少 design 參數")
        src = designlib.DESIGN_LIB / design_name
        if not src.exists() or not src.is_dir():
            return self._err("design 不存在")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(src.rglob("*")):
                if not p.is_file():
                    continue
                arc = f"{design_name}/{p.relative_to(src).as_posix()}"
                zf.write(p, arc)
        data = buf.getvalue()
        dl_name = f"{design_name}.zip"
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition",
                         f'attachment; filename="{dl_name}"')
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
        self.studio.log(f"⬇ 匯出 design: {design_name} ({len(data)} bytes)")

    def _msnames(self) -> None:
        """Material Symbols 全部名稱→碼點（前端做字形預覽/查詢用）。"""
        try:
            _ttf, cps = icons.ensure_resources()
            return self._json({"ok": True, "names": cps})
        except Exception as e:
            return self._json({"ok": True, "names": {}, "error": str(e)})

    def _ui_state(self) -> None:
        """回傳 ui 框架產出狀態（檔清單 + 頁面 meta）。"""
        ui_dir = OUT_DIR / "ui"
        files = []
        for p in sorted(ui_dir.rglob("*.py")):
            files.append(str(p.relative_to(OUT_DIR)))
        # 頁面 meta:從產出的 page 檔粗抽 @register 參數
        pages = []
        for p in sorted((ui_dir / "page").glob("*.py")):
            if p.name == "__init__.py":
                continue
            txt = p.read_text(encoding="utf-8", errors="replace")
            m = re.search(
                r'@register\(id="([^"]+)", title="([^"]+)", icon="([^"]*)"',
                txt)
            if m:
                pages.append({"id": m.group(1), "title": m.group(2),
                              "icon": m.group(3), "file": p.name})
        self._json({
            "ok": True,
            "generated": ui_dir.exists() and any(ui_dir.iterdir()),
            "files": files,
            "pages": pages,
        })

    def do_HEAD(self) -> None:  # noqa: N802
        """HEAD = GET 但無 body（模擬器 wasm_file_api 用 HEAD 檢查檔案存在）。"""
        self.do_GET()

    # ---- POST ----
    def do_POST(self) -> None:  # noqa: N802
        url = urllib.parse.urlparse(self.path)
        try:
            if url.path == "/api/upload":
                return self._upload()
            if url.path == "/api/delete":
                return self._delete()
            if url.path == "/api/scan":
                data = json.loads(self._body() or b"{}")
                return self._json({"ok": True,
                                   "scan": self.studio.scan(
                                       data.get("design"))})
            if url.path == "/api/generate":
                return self._generate()
            if url.path == "/api/config":
                return self._config()
            if url.path == "/api/design/new":
                return self._design_new()
            if url.path == "/api/design/scan":
                return self._design_scan()
            if url.path == "/api/design/upload":
                return self._design_upload()
            if url.path == "/api/design/importzip":
                return self._design_import_zip()
            if url.path == "/api/design/delete":
                return self._design_delete()
            if url.path == "/api/design/savecode":
                return self._design_savecode()
            if url.path == "/api/design/file":
                return self._design_file_save()
            self._err("not found", 404)
        except Exception as e:
            self._err(str(e))

    def _upload(self) -> None:
        ctype = self.headers.get("Content-Type", "")
        m = re.search(r"boundary=([^;]+)", ctype)
        if not m:
            return self._err("multipart 格式錯誤")
        boundary = m.group(1).strip().strip('"').encode()
        body = self._body()
        allowed = {".html", ".css", ".design", ".json"}
        saved = []
        for part in body.split(b"--" + boundary):
            if b"\r\n\r\n" not in part:
                continue
            head, content = part.split(b"\r\n\r\n", 1)
            fm = re.search(rb'filename="([^"]*)"', head)
            if not fm:
                continue
            name = fm.group(1).decode("utf-8", "replace")
            content = content.rstrip(b"\r\n")
            if not name or Path(name).suffix.lower() not in allowed:
                self.studio.log(f"⚠ 忽略不支援檔案: {name}")
                continue
            # 防路徑穿越:只用 basename
            safe = Path(name).name
            (DESIGN_DIR / safe).write_bytes(content)
            saved.append(safe)
            self.studio.log(f"↑ 已上傳 {safe} ({len(content)} bytes)")
        self._json({"ok": True, "saved": saved})

    def _delete(self) -> None:
        data = json.loads(self._body() or b"{}")
        name = data.get("name", "")
        p = DESIGN_DIR / Path(name).name
        if p.exists():
            p.unlink()
            self.studio.log(f"🗑 刪除 {p.name}")
            return self._json({"ok": True})
        self._err("檔案不存在")

    def _generate(self) -> None:
        data = json.loads(self._body() or b"{}")
        task = data.get("task", "")
        if task not in ("icons", "zh", "fx", "tokens", "ui", "all"):
            return self._err(f"未知 task: {task}")
        mapping = data.get("icons_mapping") or {}
        extra = data.get("extra_chars", "")
        design = data.get("design")  # 可指定輸出到哪個 design 的 lvgl/
        # 記憶 config
        cfg = load_config()
        if mapping:
            cfg["icons"] = mapping
        if extra:
            cfg["extra_chars"] = extra
        save_config(cfg)
        self.studio.enqueue(task, mapping, extra, design)
        self._json({"ok": True, "task": task, "design": design})

    def _config(self) -> None:
        data = json.loads(self._body() or b"{}")
        cfg = load_config()
        if "icons" in data:
            cfg["icons"] = data["icons"]
        if "extra_chars" in data:
            cfg["extra_chars"] = data["extra_chars"]
        save_config(cfg)
        self._json({"ok": True})


def make_handler(studio: Studio) -> type[Handler]:
    class H(Handler):
        web_dir = WEB_DIR
    H.studio = studio  # 注意:不能寫 class body 內的 studio = studio(作用域問題)
    return H


# ============ main ============

def main() -> None:
    ap = argparse.ArgumentParser(
        description="LVGL UI Asset Studio — 設計稿 → LVGL 資產 Web 工具")
    ap.add_argument("--port", type=int, default=None,
                    help="HTTP 端口(預設 8600,被佔用自動 +1)")
    ap.add_argument("--no-browser", action="store_true",
                    help="不自動開啟瀏覽器")
    args = ap.parse_args()

    ensure_workspace()
    studio = Studio()
    # 離線資源:啟動時背景下載(模擬器/CDN),之後全離線
    threading.Thread(
        target=lambda: vendor.ensure_vendor(log=studio.log),
        daemon=True).start()

    port = args.port or 8600
    httpd = None
    for _ in range(20):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(studio))
            break
        except OSError:
            port += 1
    if httpd is None:
        print("ERROR: 找不到可用端口", file=__import__("sys").stderr)
        return 1

    url = f"http://localhost:{port}"
    print(f"LVGL UI Asset Studio: {url}  (工作區: {WORKSPACE})")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
