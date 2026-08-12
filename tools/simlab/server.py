# simlab/server.py — SimLab 請求處理(純 stdlib,掛在既有 server 上)
#
# 項目儲存 = 本地完整複製件(自包含、可匯入匯出):
#   tools/simlab/projects/{name}/
#       lvgl/    真機 LVGL 代碼複製(page/ src/ + 根模組 .py)
#       html/    HTML 設計稿複製
#       assets/  字體/圖示 bin
#   projects.json = 索引(meta + entry 配置 + source 來源路徑)
#
# 路由全在 /simlab/* 命名空間:
#   /simlab/                → web/index.html(SimLab 單頁)
#   /simlab/sim/*           → 本地 runtime(wasm/js/lvgl.html/驅動 py)
#   /simlab/proj/{name}/*   → 項目本地複製件(lvgl/ html/ assets/,防穿越)
#   /simlab/api/projects    → 項目清單 / POST(save|scan|import|export)
#   /simlab/api/code?proj=  → 渲染後的 shim 代碼(text/plain)
#   /simlab/api/files?proj= → 項目 lvgl 全部 .py {rel: content}(JS 預載用)
#   /simlab/api/bins?proj=  → 項目字體/圖示 {vfs, url}
#   /simlab/api/code_pairs  → HTML ↔ LVGL 頁面對照
#   /simlab/api/tree        → 代碼區摺疊樹
#   /simlab/api/config      → perf 常數(GET/POST)
#   /simlab/api/runtime     → runtime 狀態
from __future__ import annotations

import fnmatch
import json
import re
import shutil
from pathlib import Path
from string import Template
from urllib.parse import parse_qs

HERE = Path(__file__).resolve().parent
WEB_DIR = HERE / "web"
SIM_DIR = HERE / "sim"
SHIM_DIR = HERE / "shim"
PROJ_ROOT = HERE / "projects"
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


# ============ 項目(本地複製件) ============

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


def _proj_dir(proj: dict) -> Path:
    """本地複製件根:tools/simlab/projects/{name}。"""
    return PROJ_ROOT / proj["name"]


def _proj_base(proj: dict) -> Path:
    """LVGL 代碼目錄(本地複製件)。"""
    return _proj_dir(proj) / "lvgl"


def _proj_html(proj: dict) -> Path:
    return _proj_dir(proj) / "html"


def _proj_assets(proj: dict) -> Path:
    return _proj_dir(proj) / "assets"


def _entry(proj: dict) -> dict:
    return proj.get("entry") or {}


def _kind(proj: dict) -> str:
    return _entry(proj).get("kind", "framework")


def _files_for(proj: dict) -> dict[str, str]:
    """項目 lvgl 要預載的全部 .py(rel → content)。framework:根+page+src;mp_lvgl:根層(套 exclude)。"""
    base = _proj_base(proj)
    entry = _entry(proj)
    out: dict[str, str] = {}
    if not base.is_dir():
        return out
    if _kind(proj) == "framework":
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
    """字體/圖示清單:[{vfs, url}](本地 projects/{name}/assets/)。"""
    entry = _entry(proj)
    d = _proj_dir(proj)
    out: list[dict] = []
    for vfs, rel in (entry.get("bins") or {}).items():
        src = (d / rel).resolve()  # rel 形如 "assets/zh_hant_16.bin"
        if not src.is_file() or not str(src).startswith(str(d.resolve())):
            continue
        out.append({"vfs": str(vfs).lstrip("/"),
                    "url": "/simlab/proj/{}/{}".format(proj["name"], rel)})
    return out


def _html_previews(proj: dict) -> list[dict]:
    """HTML 設計稿清單:[{name, url}](本地 html/)。"""
    hbase = _proj_html(proj)
    out: list[dict] = []
    if not hbase.is_dir():
        return out
    for p in sorted(hbase.rglob("*.html")):
        if p.name.startswith("_"):
            continue
        out.append({"name": p.relative_to(hbase).as_posix(),
                    "url": "/simlab/proj/{}/html/{}".format(proj["name"], p.relative_to(hbase).as_posix())})
    return out


def _code_pairs(proj: dict) -> list[dict]:
    """HTML 稿 ↔ LVGL .py 頁面對照(本地複製件)。
    framework:優先 design.json 的 pages(web_file/lvgl_file);否則慣例。
    mp_lvgl:html {stem}.html ↔ lvgl_page_{stem}.py。"""
    name = proj["name"]
    hbase = _proj_html(proj)
    lvbase = _proj_base(proj)
    pairs: list[dict] = []

    def _url(p: Path) -> str:
        rel = p.relative_to(_proj_dir(proj)).as_posix()
        return "/simlab/proj/{}/{}".format(name, rel)

    if _kind(proj) == "framework":
        mapping: list[tuple[str, str, str]] = []  # (id, html_rel, py_rel)
        dj = None
        djf = _proj_dir(proj) / "design.json"
        if djf.exists():
            try:
                dj = json.loads(djf.read_text(encoding="utf-8"))
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
        if not mapping and hbase.is_dir():
            for hf in sorted(hbase.rglob("*.html")):
                if hf.name.startswith("_"):
                    continue
                html_rel = hf.relative_to(hbase).as_posix()
                stem = hf.stem
                py_rel = (stem + ".py") if "/" not in html_rel else (html_rel[:-5] + ".py")
                mapping.append((stem, html_rel, py_rel))
        for pid, html_rel, py_rel in mapping:
            hf = (hbase / html_rel).resolve()
            pf = (lvbase / py_rel).resolve()
            if hf.is_file() and pf.is_file():
                pairs.append({"id": pid, "html_name": html_rel, "py_name": py_rel,
                              "html_url": _url(hf), "py_url": _url(pf)})
    else:
        if hbase.is_dir():
            for hf in sorted(hbase.rglob("*.html")):
                if hf.name.startswith("_"):
                    continue
                stem = hf.stem
                py_rel = "lvgl_page_{}.py".format(stem)
                pf = (lvbase / py_rel).resolve()
                if not pf.is_file():
                    continue
                html_rel = hf.relative_to(hbase).as_posix()
                pairs.append({"id": stem, "html_name": html_rel, "py_name": py_rel,
                              "html_url": _url(hf), "py_url": _url(pf)})
    return pairs


def _project_tree(proj: dict) -> list[dict]:
    """代碼區摺疊樹:🐍 lvgl / 🖼 html / 📦 assets(本地複製件)。"""
    name = proj["name"]
    lvbase = _proj_base(proj)
    groups: list[dict] = []
    lv: list[dict] = []
    if lvbase.is_dir():
        for p in sorted(lvbase.rglob("*.py")):
            rel = p.relative_to(lvbase).as_posix()
            lv.append({"name": p.name, "path": rel, "size": p.stat().st_size,
                       "url": "/simlab/proj/{}/lvgl/{}".format(name, rel)})
    if lv:
        groups.append({"icon": "🐍", "title": "LVGL 程式碼 (lvgl/)", "items": lv})
    hbase = _proj_html(proj)
    html_items: list[dict] = []
    if hbase.is_dir():
        for p in sorted(hbase.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in (".html", ".css", ".js"):
                continue
            rel = p.relative_to(hbase).as_posix()
            html_items.append({"name": p.name, "path": rel, "size": p.stat().st_size,
                               "url": "/simlab/proj/{}/html/{}".format(name, rel)})
    if html_items:
        groups.append({"icon": "🖼", "title": "網頁設計稿 (html/)", "items": html_items})
    assets = _proj_assets(proj)
    aitems: list[dict] = []
    if assets.is_dir():
        for p in sorted(assets.rglob("*")):
            if not p.is_file():
                continue
            aitems.append({"name": p.name, "path": "assets/" + p.name,
                           "size": p.stat().st_size,
                           "url": "/simlab/proj/{}/assets/{}".format(name, p.name)})
    if aitems:
        groups.append({"icon": "📦", "title": "共用資源 (assets/)", "items": aitems})
    return groups


# ============ 匯入 / 匯出 ============

def _scan_source(path: str) -> dict:
    """從真機路徑掃描,建議 entry + 檔案清單(供匯入)。"""
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
    files: list[str] = []
    if has_app and page_dir.is_dir():
        pages = sorted(p.stem for p in page_dir.glob("*.py")
                       if p.name != "__init__.py" and not p.name.startswith("_"))
        modules = [m for m in ("registry", "ui_common", "nav", "launcher", "app")
                   if (base / (m + ".py")).exists()]
        entry: dict = {"kind": "framework", "page_dir": "page", "modules": modules}
        if src_dir.is_dir():
            entry["src_dir"] = "src"
        suggest["entry"] = entry
        suggest["pages"] = pages
        for p in sorted(base.rglob("*.py")):
            rel = p.relative_to(base).as_posix()
            head = rel.split("/", 1)[0]
            if "/" not in rel or head == "page" or head == "src":
                files.append(rel)
    else:
        lvpages = sorted(p.stem for p in base.glob("lvgl_page_*.py"))
        if lvpages:
            suggest["entry"] = {
                "kind": "mp_lvgl",
                "modules": lvpages,
                "exclude": ["lvgl_ui_app.py", "lvgl_shared.py", "gen_font.py",
                            "test_*.py", "lvgl_demo*.py"],
            }
            suggest["pages"] = lvpages
            files = [p.name for p in sorted(base.glob("*.py"))
                     if not any(fnmatch.fnmatch(p.name, x)
                                for x in suggest["entry"]["exclude"])]
        else:
            raise ValueError("看不出 UI 結構:需要 app.py+page/ 或 lvgl_page_*.py")
    # 同倉 html 稿偵測
    html_dir = ""
    for cand in ("html", "design/html", "web"):
        d = base / cand
        if d.is_dir() and any(d.rglob("*.html")):
            html_dir = (GIT_ROOT / path / cand).as_posix()
            break
    # bins
    bins: list[str] = []
    for b in ("zh_hant_16.bin", "icons_16.bin"):
        if (src_dir / b).exists() if src_dir.exists() else False:
            bins.append("src/" + b)
    suggest["files"] = files
    suggest["html_dir"] = html_dir
    suggest["bin_files"] = bins
    return suggest


def import_project(name: str, title: str, group: str, path: str,
                   html_dir: str, entry: dict, w: int, h: int,
                   bins_src: str = "") -> dict:
    """把真機項目複製成本地複製件(projects/{name}/{lvgl,html,assets})。
    bins_src:跨倉字體借用來源目錄(相對 git root,如 mp_Net-Core/.../src)。"""
    if not name or not path:
        raise ValueError("name 與 path 必填")
    src = (GIT_ROOT / path).resolve()
    if not src.is_dir() or not str(src).startswith(str(GIT_ROOT.resolve())):
        raise ValueError("來源不存在: {}".format(src))
    d = _proj_dir({"name": name})
    lvgl_dir = d / "lvgl"
    html_dir_local = d / "html"
    assets_dir = d / "assets"
    # 清掉舊的(重新匯入 = 全新複製)
    if d.exists():
        shutil.rmtree(d)
    lvgl_dir.mkdir(parents=True)
    html_dir_local.mkdir(parents=True)
    assets_dir.mkdir(parents=True)

    kind = entry.get("kind", "framework")
    src_dir = None
    if kind == "framework":
        page_dir = entry.get("page_dir", "page")
        src_dir = entry.get("src_dir", "src")
        for p in sorted(src.rglob("*.py")):
            rel = p.relative_to(src).as_posix()
            head = rel.split("/", 1)[0]
            if "/" not in rel or head == page_dir or head == src_dir:
                dst = lvgl_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst)
    else:
        for p in sorted(src.glob("*.py")):
            if any(fnmatch.fnmatch(p.name, x) for x in entry.get("exclude", [])):
                continue
            shutil.copy2(p, lvgl_dir / p.name)
    # html 稿
    if html_dir:
        hsrc = (GIT_ROOT / html_dir).resolve()
        if hsrc.is_dir():
            for p in sorted(hsrc.rglob("*")):
                if not p.is_file() or p.suffix.lower() not in (".html", ".css", ".js"):
                    continue
                rel = p.relative_to(hsrc).as_posix()
                dst = html_dir_local / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst)
            # design.json 一併複製(頁面對照用)
            dj = hsrc.parent / "design.json"
            if dj.is_file():
                shutil.copy2(dj, d / "design.json")
    # bins:framework 自動抓 src/*.bin;再加顯式借用(bins_src / entry.bins)
    bins_map: dict[str, str] = {}
    if kind == "framework" and src_dir and (src / src_dir).is_dir():
        for b in sorted((src / src_dir).glob("*.bin")):
            shutil.copy2(b, assets_dir / b.name)
            bins_map.setdefault("ui/lvgl/src/" + b.name, "assets/" + b.name)
    if bins_src:
        bdir = (GIT_ROOT / bins_src).resolve()
        if bdir.is_dir() and str(bdir).startswith(str(GIT_ROOT.resolve())):
            for b in ("zh_hant_16.bin", "icons_16.bin"):
                if (bdir / b).is_file():
                    vfs = ("ui/lvgl/src/" if kind == "framework" else "") + b
                    shutil.copy2(bdir / b, assets_dir / b)
                    bins_map[vfs] = "assets/" + b
    for vfs, rel in (entry.get("bins") or {}).items():
        bsrc = (GIT_ROOT / rel).resolve()
        if bsrc.is_file() and str(bsrc).startswith(str(GIT_ROOT.resolve())):
            fname = Path(vfs).name
            shutil.copy2(bsrc, assets_dir / fname)
            bins_map[vfs] = "assets/" + fname
    entry["bins"] = bins_map

    meta = {
        "name": name,
        "title": title or name,
        "group": group or "",
        "source": path,
        "source_html": html_dir or "",
        "w": w or 320,
        "h": h or 240,
        "entry": entry,
    }
    return meta


def export_project(proj: dict) -> dict:
    """把本地複製件寫回來源(source / source_html / bins)。"""
    name = proj["name"]
    d = _proj_dir(proj)
    src = (GIT_ROOT / proj.get("source", "")).resolve()
    if not str(src).startswith(str(GIT_ROOT.resolve())):
        raise ValueError("來源路徑不合法: {}".format(proj.get("source")))
    written: list[str] = []
    if not src.is_dir():
        raise ValueError("來源不存在(先建目錄?): {}".format(src))
    lvgl_dir = d / "lvgl"
    if lvgl_dir.is_dir():
        for p in sorted(lvgl_dir.rglob("*.py")):
            rel = p.relative_to(lvgl_dir).as_posix()
            dst = src / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            written.append("lvgl/" + rel)
    # html 寫回 source_html
    sh = proj.get("source_html", "")
    if sh:
        hsrc = (GIT_ROOT / sh).resolve()
        if str(hsrc).startswith(str(GIT_ROOT.resolve())):
            hdir = d / "html"
            if hdir.is_dir():
                for p in sorted(hdir.rglob("*")):
                    if not p.is_file():
                        continue
                    rel = p.relative_to(hdir).as_posix()
                    dst = hsrc / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, dst)
                    written.append("html/" + rel)
    # bins 寫回(entry.bins 的 vfs 目標;framework → src/,mp_lvgl → 根)
    entry = _entry(proj)
    for vfs, rel in (entry.get("bins") or {}).items():
        if not rel.startswith("assets/"):
            continue
        bsrc = d / rel
        if not bsrc.is_file():
            continue
        if _kind(proj) == "framework":
            tgt_dir = src / entry.get("src_dir", "src")
        else:
            tgt_dir = src
        tgt_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bsrc, tgt_dir / Path(vfs).name)
        written.append("assets/" + tgt_dir.name + "/" + Path(vfs).name)
    return {"ok": True, "written": written}


def _page_modules(proj: dict) -> list[str]:
    entry = _entry(proj)
    if _kind(proj) == "mp_lvgl":
        return list(entry.get("modules", []))
    base = _proj_base(proj)
    page_dir = base / entry.get("page_dir", "page")
    out: list[str] = []
    if page_dir.is_dir():
        out = sorted(p.stem for p in page_dir.glob("*.py")
                     if p.name != "__init__.py" and not p.name.startswith("_"))
    return out


def _render_code(proj: dict) -> str:
    """渲染 shim 代碼:base.tpl(緩存模擬器+注入+perf 儀表)+ entry.tpl(framework/mp_lvgl)。"""
    entry = _entry(proj)
    kind = _kind(proj)
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
        if p.startswith("/simlab/proj/"):
            # 本地複製件:lvgl/ html/ assets/(+ design.json)
            rest = p[len("/simlab/proj/"):]
            name, _, rel = rest.partition("/")
            proj = _project(name)
            if proj is None:
                return h._err("not found", 404)
            base = _proj_dir(proj)
            pf = (base / rel).resolve()
            if not str(pf).startswith(str(base.resolve())) or not pf.is_file():
                return h._err("not found", 404)
            if pf.suffix.lower() == ".html" and rel.startswith("html/"):
                # 設計稿 HTML:注入 [data-dom-id] 橋接(點按鈕 → simlab-nav 跳轉)
                html = _inject_html_bridge(
                    pf.read_text(encoding="utf-8", errors="replace"))
                body = html.encode("utf-8")
                h.send_response(200)
                h.send_header("Content-Type", "text/html; charset=utf-8")
                h.send_header("Content-Length", str(len(body)))
                h.send_header("Cache-Control", "no-cache")
                h.send_header("Access-Control-Allow-Origin", "*")
                h.end_headers()
                return h.wfile.write(body)
            return h._serve_file(pf, _ctype(pf))
        if p == "/simlab/api/projects":
            return h._json({"ok": True, "projects": [
                {"name": x["name"], "title": x.get("title", x["name"]),
                 "w": x.get("w", 320), "h": x.get("h", 240),
                 "group": x.get("group", ""),
                 "source": x.get("source", ""),
                 "kind": _kind(x),
                 "entry": _entry(x),
                 "html": _html_previews(x)}
                for x in _load_projects()]})
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
        if p == "/simlab/api/config":
            return h._json({"ok": True, "config": _load_config()})
        if p == "/simlab/api/runtime":
            return h._json({"ok": True, "runtime": _runtime_status()})
    except Exception as e:  # noqa: BLE001
        return h._err(str(e))
    return h._err("not found", 404)


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
            names = [p.get("name") for p in projects if p.get("name")]
            if len(names) != len(set(names)):
                return h._err("項目 name 重複", 400)
            for p in projects:
                if not p.get("name"):
                    return h._err("項目缺 name", 400)
            _save_projects(projects)
            return h._json({"ok": True, "projects": projects})
        if action == "scan":
            path = (body.get("path") or "").strip()
            if not path:
                return h._err("缺 path", 400)
            try:
                suggest = _scan_source(path)
            except ValueError as e:
                return h._err(str(e), 400)
            return h._json({"ok": True, "suggest": suggest})
        if action == "import":
            # 匯入:掃描 + 複製成本地複製件 + 寫入 projects.json
            path = (body.get("path") or "").strip()
            try:
                suggest = _scan_source(path)
            except ValueError as e:
                return h._err(str(e), 400)
            entry = body.get("entry") or suggest.get("entry") or {}
            try:
                meta = import_project(
                    name=(body.get("name") or "").strip() or suggest["name"],
                    title=(body.get("title") or "").strip() or suggest["title"],
                    group=(body.get("group") or "").strip() or "",
                    path=path,
                    html_dir=entry.pop("html_dir", None) or suggest.get("html_dir", ""),
                    entry=entry,
                    w=int(body.get("w") or suggest.get("w", 320)),
                    h=int(body.get("h") or suggest.get("h", 240)),
                    bins_src=(body.get("bins_src") or "").strip(),
                )
            except ValueError as e:
                return h._err(str(e), 400)
            projects = _load_projects()
            projects = [p for p in projects if p.get("name") != meta["name"]]
            projects.append(meta)
            _save_projects(projects)
            return h._json({"ok": True, "project": meta,
                            "pages": suggest.get("pages", [])})
        if action == "export":
            name = (body.get("name") or "").strip()
            proj = _project(name)
            if proj is None:
                return h._err("project not found", 404)
            try:
                r = export_project(proj)
            except ValueError as e:
                return h._err(str(e), 400)
            return h._json(r)
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
