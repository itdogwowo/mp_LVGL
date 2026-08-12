# simlab/server.py — SimLab 請求處理(純 stdlib,掛在既有 server 上)
#
# 路由全在 /simlab/* 命名空間:
#   /simlab/                → web/index.html(SimLab 單頁)
#   /simlab/sim/*           → 本地 runtime(wasm/js/lvgl.html/驅動 py)
#   /simlab/bin/{name}/*    → 跨倉 bin(字體/圖示,以 git root 相對路徑解析)
#   /simlab/proj/{name}/*   → 項目真機代碼(唯讀,防穿越)
#   /simlab/api/projects    → 項目清單
#   /simlab/api/code?proj=  → 渲染後的 shim 代碼(text/plain)
#   /simlab/api/files?proj= → 項目全部 .py {rel: content}(JS 預載用)
#   /simlab/api/bins?proj=  → 項目字體/圖示 {vfs, url}
#   /simlab/api/config      → perf 常數(GET/POST)
#   /simlab/api/runtime     → runtime 狀態
#
# 回覆統一借用 host handler 的 _serve_file/_json/_err/_body
# (ETag/304/CORS 等行為與 Asset Studio 一致),路徑解析與邏輯全在本檔。
from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from string import Template
from urllib.parse import parse_qs

HERE = Path(__file__).resolve().parent
WEB_DIR = HERE / "web"
SIM_DIR = HERE / "sim"
SHIM_DIR = HERE / "shim"
PROJECTS_FILE = HERE / "projects.json"
CONFIG_FILE = HERE / "config.json"
GIT_ROOT = HERE.parent.parent.parent  # tools/simlab → mp_LVGL/tools → mp_LVGL → git root

_CTYPES = {
    ".html": "text/html",
    ".js": "application/javascript",
    ".wasm": "application/wasm",
    ".json": "application/json",
    ".css": "text/css",
    ".py": "text/plain",
    ".bin": "application/octet-stream",
    ".ttf": "font/ttf",
    ".png": "image/png",
}


def _ctype(p: Path) -> str:
    return _CTYPES.get(p.suffix.lower(), "application/octet-stream")


# ============ 配置 ============

def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# ============ 項目 ============

def _load_projects() -> list[dict]:
    try:
        return json.loads(PROJECTS_FILE.read_text(encoding="utf-8")).get("projects", [])
    except (OSError, ValueError):
        return []


def _save_projects(projects: list[dict]) -> None:
    PROJECTS_FILE.write_text(
        json.dumps({"projects": projects}, ensure_ascii=False, indent=2), encoding="utf-8")


def _project(name: str) -> dict | None:
    for p in _load_projects():
        if p.get("name") == name:
            return p
    return None


def _proj_base(proj: dict) -> Path:
    """項目根(相對 git root 解析;防穿越到 git root 外)。"""
    base = (GIT_ROOT / proj["path"]).resolve()
    if not str(base).startswith(str(GIT_ROOT.resolve())):
        raise ValueError("project path outside git root")
    return base


def _files_for(proj: dict) -> dict[str, str]:
    """項目要預載的全部 .py(rel → content)。framework:根+page+src;mp_lvgl:根層(套 exclude)。"""
    base = _proj_base(proj)
    entry = proj.get("entry", {})
    kind = entry.get("kind", "framework")
    out: dict[str, str] = {}
    if kind == "framework":
        page_dir = entry.get("page_dir", "page")
        src_dir = entry.get("src_dir", "src")
        for p in sorted(base.rglob("*.py")):
            rel = p.relative_to(base).as_posix()
            head = rel.split("/", 1)[0]
            if "/" not in rel or head == page_dir or head == src_dir:
                out[rel] = p.read_text(encoding="utf-8", errors="replace")
    else:
        for p in sorted(base.glob("*.py")):
            if any(fnmatch.fnmatch(p.name, x) for x in entry.get("exclude", [])):
                continue
            out[p.name] = p.read_text(encoding="utf-8", errors="replace")
    return out


def _bins_for(proj: dict) -> list[dict]:
    """項目字體/圖示清單:[{vfs, url}]。bin 可跨到 git root 內其他倉(借字體);
    url 統一以 git root 相對路徑表示,由 /simlab/bin/{name}/{rel} 服務。"""
    entry = proj.get("entry", {})
    base = _proj_base(proj)
    out: list[dict] = []
    for vfs, rel in (entry.get("bins") or {}).items():
        src = (base / rel).resolve()
        if not src.is_file():
            continue
        if not str(src).startswith(str(GIT_ROOT.resolve())):
            continue
        gitrel = src.relative_to(GIT_ROOT).as_posix()
        out.append({"vfs": str(vfs).lstrip("/"),
                    "url": "/simlab/bin/{}/{}".format(proj["name"], gitrel)})
    return out


def _page_modules(proj: dict) -> list[str]:
    entry = proj.get("entry", {})
    if entry.get("kind") == "mp_lvgl":
        return list(entry.get("modules", []))
    base = _proj_base(proj)
    page_dir = base / entry.get("page_dir", "page")
    out: list[str] = []
    if page_dir.is_dir():
        out = sorted(p.stem for p in page_dir.glob("*.py")
                     if p.name != "__init__.py" and not p.name.startswith("_"))
    return out


def _project_tree(proj: dict) -> list[dict]:
    """代碼區摺疊式檔案樹:[{icon, title, items:[{name, path, size, url}]}]。
    🐍 lvgl 代碼(項目根 .py)+ 🖼 HTML 稿(html_dir)+ 📦 資源(bins)。"""
    entry = proj.get("entry", {})
    name = proj["name"]
    base = _proj_base(proj)
    groups: list[dict] = []
    # 🐍 LVGL 程式碼
    lv: list[dict] = []
    for p in sorted(base.rglob("*.py")):
        rel = p.relative_to(base).as_posix()
        lv.append({"name": p.name, "path": rel, "size": p.stat().st_size,
                   "url": "/simlab/proj/{}/{}".format(name, rel)})
    if lv:
        groups.append({"icon": "🐍", "title": "LVGL 程式碼 (lvgl/)", "items": lv})
    # 🖼 HTML 稿
    hdir = entry.get("html_dir")
    if hdir:
        hbase = (GIT_ROOT / hdir).resolve()
        html_items: list[dict] = []
        if hbase.is_dir() and str(hbase).startswith(str(GIT_ROOT.resolve())):
            for p in sorted(hbase.rglob("*")):
                if not p.is_file() or p.suffix.lower() not in (".html", ".css", ".js"):
                    continue
                gitrel = p.relative_to(GIT_ROOT).as_posix()
                html_items.append({"name": p.name,
                                   "path": p.relative_to(hbase).as_posix(),
                                   "size": p.stat().st_size,
                                   "url": "/simlab/bin/{}/{}".format(name, gitrel)})
        if html_items:
            groups.append({"icon": "🖼", "title": "網頁設計稿 (html/)", "items": html_items})
    # 📦 資源(字體/圖示)
    assets: list[dict] = []
    for vfs, rel in (entry.get("bins") or {}).items():
        src = (base / rel).resolve()
        if not src.is_file() or not str(src).startswith(str(GIT_ROOT.resolve())):
            continue
        gitrel = src.relative_to(GIT_ROOT).as_posix()
        assets.append({"name": Path(vfs).name, "path": vfs, "size": src.stat().st_size,
                       "url": "/simlab/bin/{}/{}".format(name, gitrel)})
    if assets:
        groups.append({"icon": "📦", "title": "共用資源 (assets/)", "items": assets})
    return groups


def _html_previews(proj: dict) -> list[dict]:
    """項目 HTML 設計稿清單:[{name, url}](跨倉,走 /simlab/bin/)。"""
    entry = proj.get("entry", {})
    hdir = entry.get("html_dir")
    if not hdir:
        return []
    base = (GIT_ROOT / hdir).resolve()
    if not base.is_dir() or not str(base).startswith(str(GIT_ROOT.resolve())):
        return []
    out: list[dict] = []
    for p in sorted(base.rglob("*.html")):
        if p.name.startswith("_"):
            continue
        rel = p.relative_to(GIT_ROOT).as_posix()
        out.append({"name": p.relative_to(base).as_posix(), "url": "/simlab/bin/{}/{}".format(proj["name"], rel)})
    return out


def _code_pairs(proj: dict) -> list[dict]:
    """HTML 稿 ↔ LVGL .py 頁面對照:[{id, html_name, py_name, html_url, py_url}]。
    framework:優先 design.json 的 pages(web_file/lvgl_file);否則慣例。
    mp_lvgl:html page/{stem}.html ↔ lvgl_page_{stem}.py。"""
    entry = proj.get("entry", {})
    kind = entry.get("kind", "framework")
    name = proj["name"]
    hdir = entry.get("html_dir")
    base = _proj_base(proj)
    pairs: list[dict] = []

    def _url(p: Path) -> str:
        return "/simlab/bin/{}/{}".format(name, p.relative_to(GIT_ROOT).as_posix())

    if kind == "framework":
        mapping: list[tuple[str, str, str]] = []  # (id, html_rel, py_rel)
        dj = None
        if hdir:
            cand = (GIT_ROOT / hdir).parent / "design.json"
            if cand.exists():
                try:
                    dj = json.loads(cand.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    dj = None
        if dj and dj.get("pages"):
            for pg in dj["pages"]:
                wf = pg.get("web_file") or ""
                lf = pg.get("lvgl_file") or ""
                if not wf or not lf:
                    continue
                html_rel = wf[len("html/"):] if wf.startswith("html/") else wf
                py_rel = lf[len("lvgl/ui/"):] if lf.startswith("lvgl/ui/") else lf
                mapping.append((pg.get("id", Path(html_rel).stem), html_rel, py_rel))
        if not mapping and hdir:
            # 慣例:launcher.html ↔ launcher.py;page/X.html ↔ page/X.py
            hbase = (GIT_ROOT / hdir).resolve()
            if hbase.is_dir():
                for hf in sorted(hbase.rglob("*.html")):
                    if hf.name.startswith("_"):
                        continue
                    html_rel = hf.relative_to(hbase).as_posix()
                    stem = hf.stem
                    py_rel = (stem + ".py") if "/" not in html_rel else (html_rel[:-5] + ".py")
                    mapping.append((stem, html_rel, py_rel))
        for pid, html_rel, py_rel in mapping:
            hf = (GIT_ROOT / hdir / html_rel).resolve() if hdir else None
            pf = (base / py_rel).resolve()
            if hf is not None and hf.is_file() and pf.is_file():
                pairs.append({"id": pid, "html_name": html_rel, "py_name": py_rel,
                              "html_url": _url(hf), "py_url": "/simlab/proj/{}/{}".format(name, py_rel)})
    else:
        # mp_lvgl:html {stem}.html ↔ lvgl_page_{stem}.py
        if hdir:
            hbase = (GIT_ROOT / hdir).resolve()
            if hbase.is_dir():
                for hf in sorted(hbase.rglob("*.html")):
                    if hf.name.startswith("_"):
                        continue
                    stem = hf.stem
                    py_rel = "lvgl_page_{}.py".format(stem)
                    pf = (base / py_rel).resolve()
                    if not pf.is_file():
                        continue
                    html_rel = hf.relative_to(hbase).as_posix()
                    pairs.append({"id": stem, "html_name": html_rel, "py_name": py_rel,
                                  "html_url": _url(hf),
                                  "py_url": "/simlab/proj/{}/{}".format(name, py_rel)})
    return pairs


_BRIDGE = """
<script>
// SimLab HTML 稿橋接:點 [data-dom-id] → 父頁跳轉對應 LVGL 頁面
document.addEventListener("click", function (e) {
  var el = e.target && e.target.closest ? e.target.closest("[data-dom-id]") : null;
  if (!el) return;
  var id = el.getAttribute("data-dom-id") || "";
  try { window.parent.postMessage({ type: "simlab-nav", page: id }, "*"); } catch (err) {}
  e.preventDefault();
  e.stopPropagation();
}, true);
</script>
"""


def _inject_html_bridge(html: str) -> str:
    if "simlab-nav" in html:
        return html
    if "</body>" in html:
        return html.replace("</body>", _BRIDGE + "</body>", 1)
    return html + _BRIDGE


def scan_project_path(path: str) -> dict:
    """從真機路徑掃描,建議 entry(供「從路徑掃描建項目」)。"""
    base = (GIT_ROOT / path).resolve()
    if not str(base).startswith(str(GIT_ROOT.resolve())):
        raise ValueError("path outside git root")
    if not base.is_dir():
        raise ValueError("path 不存在: {}".format(base))
    name = path.rstrip("/").split("/")[-1].replace("_", "-").replace(".", "-")
    suggest: dict = {"name": name, "title": name, "path": path,
                     "w": 320, "h": 240, "entry": {}}
    has_app = (base / "app.py").exists()
    page_dir = base / "page"
    src_dir = base / "src"
    if has_app and page_dir.is_dir():
        # framework 型(slave 系)
        pages = sorted(p.stem for p in page_dir.glob("*.py")
                       if p.name != "__init__.py" and not p.name.startswith("_"))
        modules = [m for m in ("registry", "ui_common", "nav", "launcher", "app")
                   if (base / (m + ".py")).exists()]
        entry: dict = {"kind": "framework", "page_dir": "page", "modules": modules}
        if src_dir.is_dir():
            entry["src_dir"] = "src"
            bins = {}
            for b in ("zh_hant_16.bin", "icons_16.bin"):
                if (src_dir / b).exists():
                    bins["ui/lvgl/src/" + b] = "src/" + b
            if bins:
                entry["bins"] = bins
        suggest["entry"] = entry
        suggest["pages"] = pages
    else:
        # mp_lvgl 型(平級頁面模組)
        lvpages = sorted(p.stem for p in base.glob("lvgl_page_*.py"))
        if lvpages:
            suggest["entry"] = {
                "kind": "mp_lvgl",
                "modules": lvpages,
                "exclude": ["lvgl_ui_app.py", "lvgl_shared.py", "gen_font.py",
                            "test_*.py", "lvgl_demo*.py"],
            }
            suggest["pages"] = lvpages
        else:
            raise ValueError("看不出 UI 結構:需要 app.py+page/ 或 lvgl_page_*.py")
    # html 稿同倉偵測
    for cand in ("html", "design/html", "web"):
        d = base / cand
        if d.is_dir() and any(d.rglob("*.html")):
            suggest["entry"]["html_dir"] = (GIT_ROOT / path / cand).as_posix()
            break
    return suggest


def _render_code(proj: dict) -> str:
    """渲染 shim 代碼:base.tpl(緩存模擬器+注入+perf 儀表)+ entry.tpl(framework/mp_lvgl)。"""
    entry = proj.get("entry", {})
    kind = entry.get("kind", "framework")
    base_tpl = (SHIM_DIR / "base.tpl").read_text(encoding="utf-8")
    kind_tpl = (SHIM_DIR / (kind + ".tpl")).read_text(encoding="utf-8")
    cfg = _load_config()
    echo_div = int((cfg.get("perf") or {}).get("echo_step_interval", 40))
    return Template(base_tpl + "\n" + kind_tpl).safe_substitute(
        W=proj.get("w", 320),
        H=proj.get("h", 240),
        PROJ=proj["name"],
        PROJ_URL="/simlab/proj/" + proj["name"],
        PAGE_MODULES=json.dumps(_page_modules(proj)),
        MODULES=json.dumps(entry.get("modules", [])),
        ECHO_DIV=echo_div,
    )


# ============ runtime 狀態 ============

_banner_cache: tuple[int, str | None] = (0, None)


def _wasm_banner() -> str | None:
    """從 firmware.wasm 抽 MicroPython banner(mtime 快取)。"""
    global _banner_cache
    f = SIM_DIR / "firmware.wasm"
    if not f.exists():
        return None
    mt = f.stat().st_mtime_ns
    if _banner_cache[0] == mt:
        return _banner_cache[1]
    try:
        data = f.read_bytes()
        m = re.search(rb"MicroPython v[^\x00\" ]+[^\x00\"]*", data)
        banner = m.group(0).decode("utf-8", errors="replace") if m else None
    except OSError:
        banner = None
    _banner_cache = (mt, banner)
    return banner


def _runtime_status() -> dict:
    cfg = _load_config()
    rt = dict(cfg.get("runtime") or {})
    rt["files"] = {n: (SIM_DIR / n).exists()
                   for n in ("firmware.wasm", "micropython.js", "lvgl.html")}
    f = SIM_DIR / "firmware.wasm"
    rt["wasm_size"] = f.stat().st_size if f.exists() else 0
    rt["banner"] = _wasm_banner()
    return rt


# ============ 路由 ============

def handle_get(h, url) -> None:
    p = url.path
    try:
        if p == "/simlab" or p == "/simlab/":
            return h._serve_file(WEB_DIR / "index.html", "text/html")
        if p.startswith("/simlab/sim/"):
            rel = p[len("/simlab/sim/"):]
            f = (SIM_DIR / rel).resolve()
            if not str(f).startswith(str(SIM_DIR.resolve())) or not f.is_file():
                return h._err("not found", 404)
            return h._serve_file(f, _ctype(f))
        if p.startswith("/simlab/bin/"):
            # 跨倉 bin(字體/圖示/HTML 稿):以 git root 相對路徑解析,防穿越
            rest = p[len("/simlab/bin/"):]
            name, _, gitrel = rest.partition("/")
            if _project(name) is None:
                return h._err("not found", 404)
            bf = (GIT_ROOT / gitrel).resolve()
            if not str(bf).startswith(str(GIT_ROOT.resolve())) or not bf.is_file():
                return h._err("not found", 404)
            if bf.suffix.lower() == ".html":
                # 設計稿 HTML:注入 [data-dom-id] 橋接(點按鈕 → simlab-nav 跳轉)
                html = _inject_html_bridge(
                    bf.read_text(encoding="utf-8", errors="replace"))
                body = html.encode("utf-8")
                h.send_response(200)
                h.send_header("Content-Type", "text/html; charset=utf-8")
                h.send_header("Content-Length", str(len(body)))
                h.send_header("Cache-Control", "no-cache")
                h.send_header("Access-Control-Allow-Origin", "*")
                h.end_headers()
                return h.wfile.write(body)
            return h._serve_file(bf, _ctype(bf))
        if p.startswith("/simlab/proj/"):
            rest = p[len("/simlab/proj/"):]
            name, _, rel = rest.partition("/")
            proj = _project(name)
            if proj is None:
                return h._err("not found", 404)
            base = _proj_base(proj)
            pf = (base / rel).resolve()
            if not str(pf).startswith(str(base.resolve())) or not pf.is_file():
                return h._err("not found", 404)
            return h._serve_file(pf, _ctype(pf))
        if p == "/simlab/api/projects":
            return h._json({"ok": True, "projects": [
                {"name": x["name"], "title": x.get("title", x["name"]),
                 "w": x.get("w", 320), "h": x.get("h", 240),
                 "path": x.get("path", ""),
                 "group": x.get("group", ""),
                 "kind": x.get("entry", {}).get("kind", "framework"),
                 "entry": x.get("entry", {}),
                 "html": _html_previews(x)}
                for x in _load_projects()]})
        if p == "/simlab/api/html":
            proj = _project((parse_qs(url.query).get("proj") or [""])[0])
            if proj is None:
                return h._err("project not found", 404)
            return h._json({"ok": True, "html": _html_previews(proj)})
        if p == "/simlab/api/code_pairs":
            proj = _project((parse_qs(url.query).get("proj") or [""])[0])
            if proj is None:
                return h._err("project not found", 404)
            return h._json({"ok": True, "pairs": _code_pairs(proj)})
        if p == "/simlab/api/tree":
            proj = _project((parse_qs(url.query).get("proj") or [""])[0])
            if proj is None:
                return h._err("project not found", 404)
            return h._json({"ok": True, "tree": _project_tree(proj)})
        if p == "/simlab/api/code":
            proj = _project((parse_qs(url.query).get("proj") or [""])[0])
            if proj is None:
                return h._err("project not found", 404)
            body = _render_code(proj).encode("utf-8")
            h.send_response(200)
            h.send_header("Content-Type", "text/plain; charset=utf-8")
            h.send_header("Content-Length", str(len(body)))
            h.send_header("Cache-Control", "no-cache")
            h.end_headers()
            return h.wfile.write(body)
        if p == "/simlab/api/files":
            proj = _project((parse_qs(url.query).get("proj") or [""])[0])
            if proj is None:
                return h._err("project not found", 404)
            return h._json({"ok": True, "files": _files_for(proj)})
        if p == "/simlab/api/bins":
            proj = _project((parse_qs(url.query).get("proj") or [""])[0])
            if proj is None:
                return h._err("project not found", 404)
            return h._json({"ok": True, "bins": _bins_for(proj)})
        if p == "/simlab/api/config":
            return h._json({"ok": True, "config": _load_config()})
        if p == "/simlab/api/runtime":
            return h._json({"ok": True, "runtime": _runtime_status()})
    except Exception as e:  # noqa: BLE001
        return h._err(str(e))
    return h._err("not found", 404)


def handle_post(h, url) -> None:
    try:
        body = json.loads(h._body() or b"{}")
    except ValueError:
        return h._err("bad json", 400)
    if url.path == "/simlab/api/projects":
        action = body.get("action")
        if action == "save":
            projects = body.get("projects")
            if not isinstance(projects, list):
                return h._err("projects 需為陣列", 400)
            # 輕量驗證:name/path 必填且不重複
            names = [p.get("name") for p in projects if p.get("name")]
            if len(names) != len(set(names)):
                return h._err("項目 name 重複", 400)
            for p in projects:
                if not p.get("path"):
                    return h._err("項目缺 path: {}".format(p.get("name", "?")), 400)
            _save_projects(projects)
            return h._json({"ok": True, "projects": projects})
        if action == "scan":
            path = (body.get("path") or "").strip()
            if not path:
                return h._err("缺 path", 400)
            try:
                suggest = scan_project_path(path)
            except ValueError as e:
                return h._err(str(e), 400)
            return h._json({"ok": True, "suggest": suggest})
        return h._err("未知 action: {}".format(action), 400)
    if url.path != "/simlab/api/config":
        return h._err("not found", 404)
    cfg = _load_config()
    if isinstance(body.get("perf"), dict):
        perf = dict(cfg.get("perf") or {})
        perf.update(body["perf"])
        cfg["perf"] = perf
    proj_name = body.get("project")
    if proj_name and isinstance(body.get("perf"), dict):
        projects = dict(cfg.get("projects") or {})
        pcfg = dict((projects.get(proj_name) or {}))
        pcfg["perf"] = body["perf"]
        projects[proj_name] = pcfg
        cfg["projects"] = projects
    if body.get("last_project"):
        cfg["last_project"] = body["last_project"]
    _save_config(cfg)
    return h._json({"ok": True, "config": cfg})
