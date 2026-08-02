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
import json
import re
import shutil
import threading
import urllib.parse
import webbrowser
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
from assets import designlib, fxgen, icons, scanner, uiframe, vendor, zhfont

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
        # 輸出目標:design 模式下寫到 design/{name}/lvgl/{src|ui};否則 workspace/out
        if design:
            src_out = designlib.lvgl_src_path(design)
            ui_out = designlib.lvgl_path(design)
        else:
            src_out = OUT_DIR
            ui_out = OUT_DIR
        if task in ("icons", "all"):
            r = icons.generate_icons(mapping, self.log, out_root=src_out)
            self.log(f"✓ icons: {r['count']} 個圖示, 缺碼點 {r['missing_codepoints']}")
        if task in ("zh", "all"):
            # 掃描該 design（無指定則第一個有設計稿的）
            design_dir = self._design_dir(design)
            r = zhfont.generate_zh(design_dir, extra, log=self.log, out_root=src_out)
            self.log(f"✓ zh: {r['char_count']} 個字符, 缺 {r['missing']}")
        if task in ("fx", "all"):
            if not self.scan_cache or design != getattr(self, "_scan_design", None):
                self.scan_cache = self.scan(design)
                self._scan_design = design
            r = fxgen.generate_fx(self.scan_cache, self.log, out_root=src_out)
            self.log(f"✓ fx: {r['animations']} 動畫, {r['hover_states']} hover 狀態")
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
        if url.path == "/api/design/render":
            return self._design_render()
        if url.path == "/api/design/simcode":
            return self._design_simcode()
        if url.path == "/api/design/savecode":
            return self._design_savecode()
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
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
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
        """提供「離線完整 HTML」版設計稿（script 指本地 vendor,iframe 直接開）。"""
        parts = path[len("/preview/"):].split("/")
        if len(parts) < 2:
            return self._err("not found", 404)
        design_name, page_file = parts[0], Path(parts[1]).name
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
        """提供 design 庫內的檔（/dlib/{design}/{file}）。"""
        parts = path[len("/dlib/"):].split("/")
        if len(parts) < 2:
            return self._err("not found", 404)
        design_name = parts[0]
        fname = "/".join(parts[1:])
        p = (designlib.DESIGN_LIB / design_name / fname).resolve()
        # 防穿越:必須在該 design 目錄內
        base = designlib.DESIGN_LIB / design_name
        if not str(p).startswith(str(base.resolve())):
            return self._err("forbidden", 403)
        if not p.exists() or not p.is_file():
            return self._err("not found", 404)
        ctype = ("text/html" if p.suffix == ".html" else
                 "text/css" if p.suffix == ".css" else
                 "application/octet-stream")
        self._serve_file(p, ctype)

    def _designs(self) -> None:
        """design 庫清單（含每 design 的 meta + 互動 API 數 + lvgl 產出狀態）。"""
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
                "lvgl": designlib.lvgl_status(name),
            })
        self._json({"ok": True, "designs": out})

    def _design_pages(self, design_name: str | None = None
                      ) -> tuple[list[dict], dict, dict]:
        """依 design 組 PAGES + ROUTES + META。"""
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
        routes: dict[str, str] = {}
        # 路由:launcher 的 card-X → page-X;任何 btn-back → launcher
        launcher_id = next((p["id"] for p in pages if p["tag"] == "launcher"),
                           pages[0]["id"])
        for p in meta["pages"]:
            fname = p["file"]
            txt = (designlib.DESIGN_LIB / Path(meta["dir"]).name / fname
                   ).read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r'data-dom-id="([^"]+)"', txt):
                dom = m.group(1)
                if dom.startswith("card-"):
                    target = "page-" + dom[len("card-"):]
                    if any(x["id"] == target for x in pages):
                        routes[dom] = target
                elif dom == "btn-back":
                    routes[dom] = launcher_id
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
            code = designlib.FRAMEWORK_CODE.format(
                origin="http://localhost:{}".format(self.server.server_port),
                design=design_name)
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
        # 附頁面清單(供原生頁面按鈕列)
        meta = designlib.read_design(design_name) or {}
        r["pages"] = meta.get("pages", [])
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
            if url.path == "/api/design/delete":
                return self._design_delete()
            if url.path == "/api/design/savecode":
                return self._design_savecode()
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
        if task not in ("icons", "zh", "fx", "ui", "all"):
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
